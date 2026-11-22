"""Identity replacement inside zlib blocks of OLE streams (SolidWorks *__ZLB, Inventor and Solid Edge compressed streams) and a few
small OLE helpers (unowned-byte mask, short account matcher, trailing-garbage ASCII pass).

Compressed blocks are found by a sequential scan for zlib headers (78 01/5E/9C/DA) that inflate cleanly to a stream end (the Adler-32
check makes a false positive practically impossible). The inflated bytes get the same equal-length replacement as raw stream bytes,
are deflated again and must fill EXACTLY the span of the original block, so no size field, stream length or sector chain changes.
Fit: (1) plain deflate at levels 9..1 / strategies when the length happens to be identical, (2) otherwise deflate + sync flush, then
empty stored blocks (5 bytes each, valid deflate any reader accepts) and a 2- or 5-byte final empty block pad up to the span.
Every rewritten block is re-inflated and must equal the intended plaintext, else the original bytes stay."""
from __future__ import annotations
import re, struct, zlib, io, time, itertools

_HDR = re.compile(rb"\x78[\x01\x5e\x9c\xda]")
MAX_STREAM = 400_000_000
_PAD_STORED = b"\x00\x00\x00\xff\xff"
_FINALS = (b"\x03\x00", b"\x01\x00\x00\xff\xff")          # empty final fixed-Huffman block (10 bits) / empty final stored block
_PARAMS = [(l, m, s) for s in (0, 1) for m in (8, 9, 7, 6) for l in (1, 9, 6, 8, 7, 5, 4, 3, 2)]
_FLEVEL_LEVELS = {0: (1,), 1: (5, 4, 3, 2), 2: (6,), 3: (9, 8, 7)}          # zlib header FLEVEL bits -> the levels that write them


_STORED_FIRST = [(6, 8, 0), (9, 8, 0), (1, 8, 0)]


def _ordered_params(hdr: bytes):
    pref = _FLEVEL_LEVELS.get(hdr[1] >> 6, ())
    return sorted(_PARAMS, key=lambda p: (p[0] not in pref, _PARAMS.index(p)))


BLOCK_SECS_BASE, BLOCK_SECS_PER_MB, BLOCK_SECS_MAX = 1.0, 3.0, 5.0     # per block: min(5 s, 1 s + 3 s per MB of plaintext)
BLOCK_MAX_COMPRESS = 400                                                # compress calls per block
FILE_SECS = 20.0                                                        # all blocks of one file
SCAN_MAX_PROBES, SCAN_MAX_FULL, SCAN_SECS = 60000, 300, 10.0
MAX_INFLATE, SCAN_MAX_BLOCKS = 64 << 20, 5000                          # inflated bytes per block / blocks per stream            # find_blocks: header candidates / full inflate attempts / seconds per stream


class OutOfBudget(Exception):
    pass


class _Budget:
    def __init__(self, secs, calls):
        self.end = time.monotonic() + secs
        self.calls = calls

    def tick(self):
        self.calls -= 1
        if self.calls < 0 or time.monotonic() > self.end:
            raise OutOfBudget()


_BUD = None


def _co(lvl, mem, strat):
    """zlib.compressobj that charges the current block budget (called once per full deflate pass)."""
    if _BUD is not None:
        _BUD.tick()
    return zlib.compressobj(lvl, zlib.DEFLATED, -15, mem, strat)


def _inflate_at(mv, s, n):
    """(plaintext, end_offset) of the complete zlib stream starting at s, or None (incomplete, corrupt, or inflating past MAX_INFLATE).
    Fed in bounded chunks so neither the output nor the unused_data copies can blow up."""
    dec = zlib.decompressobj()
    out, total, pos, chunk = [], 0, s, 8192
    while pos < n:
        piece = mv[pos:pos + chunk]
        x = dec.decompress(piece, MAX_INFLATE - total + 1)
        total += len(x)
        out.append(x)
        if total > MAX_INFLATE or dec.unconsumed_tail:
            return None
        if dec.eof:
            return b"".join(out), pos + len(piece) - len(dec.unused_data)
        pos += len(piece)
        chunk = min(chunk * 2, 1 << 20)
    return None


def find_blocks(d: bytes):
    """[(start, end, plaintext)] of non-overlapping complete zlib streams in d (bounded: probes, full attempts, seconds, blocks)."""
    out = []
    if len(d) > MAX_STREAM:
        return out
    mv = memoryview(d)
    i = 0
    probes = full = 0
    t_end = time.monotonic() + SCAN_SECS
    while len(out) < SCAN_MAX_BLOCKS:
        m = _HDR.search(d, i)
        if not m:
            break
        probes += 1
        if probes > SCAN_MAX_PROBES or full > SCAN_MAX_FULL or (probes & 255 == 0 and time.monotonic() > t_end):
            break
        s = m.start()
        try:
            probe = zlib.decompressobj()
            probe.decompress(mv[s:s + 512], 1 << 14)           # cheap rejection of false headers
            full += 1
            r = _inflate_at(mv, s, len(d))
        except Exception:
            r = None
        if r is None:
            i = s + 1
            continue
        out.append((s, r[1], r[0]))
        i = r[1]
    return out


def _fit_candidates(plain: bytes, total: int, params=None, splits=True):
    """Yield zlib streams (with the 2 header bytes of the caller prepended later) as raw deflate bodies of exact length total-6."""
    target = total - 6
    ad = struct.pack(">I", zlib.adler32(plain) & 0xFFFFFFFF)
    seen = set()
    for lvl, mem, strat in (params or _PARAMS):
        try:
            c = _co(lvl, mem, strat)
            base = c.compress(plain) + c.flush(zlib.Z_SYNC_FLUSH)
        except zlib.error:
            continue
        # (1) exact length without padding
        try:
            c2 = _co(lvl, mem, strat)
            full = c2.compress(plain) + c2.flush()
            if len(full) == target:
                yield full, ad, "exact"
        except zlib.error:
            pass
        for body in (_bases(plain, lvl, mem, strat, base) if splits else (base,)):
            b = len(body)
            if b in seen:
                continue
            seen.add(b)
            for fin in _FINALS:
                g = target - b - len(fin)
                if g >= 0 and g % 5 == 0:
                    yield body + _PAD_STORED * (g // 5) + fin, ad, "pad"


def _stored_tail(plain, lvl, mem, strat, target):
    """Fine-grained fit: deflate plain[:n-k] with a sync flush, then a final STORED block carrying the last k plaintext bytes
    (5 header bytes + k). The size grows with k, so k is found by bisection plus a short local scan."""
    n = len(plain)

    def build(k):
        c = _co(lvl, mem, strat)
        head = c.compress(plain[:n - k]) + c.flush(zlib.Z_SYNC_FLUSH)
        tail = plain[n - k:]
        return head + b"\x01" + struct.pack("<HH", len(tail), len(tail) ^ 0xFFFF) + tail
    hi = min(n, 65535)
    if len(build(0)) > target:
        return
    lo = 0
    if len(build(hi)) < target:
        return
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if len(build(mid)) < target:
            lo = mid
        else:
            hi = mid
    for k in range(max(0, lo - 6), min(65535, n, hi + 6) + 1):
        b = build(k)
        if len(b) == target:
            yield b


def _stored_head(plain, lvl, mem, strat, target):
    """Fit without a flush cost: a non-final STORED block carrying the first k plaintext bytes (5 + k bytes), then the rest as an
    ordinary final deflate stream. Size is monotone in k (roughly), so bisection plus a local scan finds the exact length."""
    n = len(plain)

    def build(k):
        c = _co(lvl, mem, strat)
        rest = c.compress(plain[k:]) + c.flush()
        return (b"\x00" + struct.pack("<HH", k, k ^ 0xFFFF) + plain[:k] if k else b"") + rest
    hi = min(n - 1, 65535)
    if hi < 1 or len(build(0)) > target or len(build(hi)) < target:
        return
    lo = 0
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if len(build(mid)) < target:
            lo = mid
        else:
            hi = mid
    for k in range(max(0, lo - 8), min(65535, n - 1, hi + 8) + 1):
        b = build(k)
        if len(b) == target:
            yield b
            return


def _bases(plain, lvl, mem, strat, first):
    """Sync-flushed deflate bodies of the same plaintext with different flush points (each changes the size by a few bytes)."""
    yield first
    n = len(plain)
    if n > 3_000_000:
        return
    for k in (n // 2, n // 3, 2 * n // 3, n // 4, 3 * n // 4, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987):
        if not 0 < k < n:
            continue
        try:
            c = _co(lvl, mem, strat)
            yield c.compress(plain[:k]) + c.flush(zlib.Z_SYNC_FLUSH) + c.compress(plain[k:]) + c.flush(zlib.Z_SYNC_FLUSH)
        except zlib.error:
            continue


def _fit_stored_tail(plain, total, params):
    ad = struct.pack(">I", zlib.adler32(plain) & 0xFFFFFFFF)
    for lvl, mem, strat in params:
        for gen, how in ((_stored_head, "head"), (_stored_tail, "tail")):
            for body in gen(plain, lvl, mem, strat, total - 6):
                yield body, ad, how


def refit(block: bytes, plain: bytes, budget_secs: float | None = None):
    """A zlib stream of exactly len(block) bytes that inflates to plain, or None (no fit, or out of budget: OutOfBudget is caught).
    Order: the levels the header hints at (exact length, flush + pad), then the stored head/tail fits for those, then the full sweep."""
    global _BUD
    if len(block) < 12:
        return None
    hdr = block[:2]
    params = _ordered_params(hdr)
    first = params[:6]
    if budget_secs is None:
        budget_secs = min(BLOCK_SECS_MAX, BLOCK_SECS_BASE + BLOCK_SECS_PER_MB * len(plain) / 1e6)
    _BUD = _Budget(budget_secs, BLOCK_MAX_COMPRESS)
    try:
        for body, ad, how in itertools.chain(_fit_candidates(plain, len(block), first[:3], False),       # cheap, most often successful
                                             _fit_stored_tail(plain, len(block), _STORED_FIRST + first[:2]),
                                             _fit_candidates(plain, len(block), first[3:], False),
                                             _fit_candidates(plain, len(block), first, True),
                                             _fit_stored_tail(plain, len(block), params[2:8]),
                                             _fit_candidates(plain, len(block), params[6:], True)):
            cand = hdr + body + ad
            if len(cand) != len(block):
                continue
            try:
                dec = zlib.decompressobj()
                if dec.decompress(cand) == plain and dec.eof and not dec.unused_data:
                    return cand, how
            except Exception:
                continue
    except OutOfBudget:
        return None
    finally:
        _BUD = None
    return None


def rewrite_blocks(d: bytes, matcher, file_budget=None):
    """(new_bytes, stats, block_spans). stats: rewritten / nofit / failed / blocks / pads. Stream length never changes."""
    st = {"blocks": 0, "rewritten": 0, "nofit": 0, "failed": 0, "padded": 0}
    blocks = find_blocks(d)
    spans = [(s, e) for s, e, _ in blocks]
    if not blocks:
        return d, st, spans
    out = bytearray(d)
    for s, e, plain in blocks:
        st["blocks"] += 1
        try:
            new, n = matcher.replace_bytes(plain)
        except Exception:
            st["failed"] += 1
            continue
        if not n or new == plain:
            continue
        assert len(new) == len(plain)
        if file_budget is not None and file_budget["left"] <= 0:
            st["nofit"] += 1                     # file budget spent: leave the block unchanged
            continue
        t0 = time.monotonic()
        try:
            r = refit(bytes(d[s:e]), new)
        except Exception:
            r = None
        if file_budget is not None:
            file_budget["left"] -= time.monotonic() - t0
        if r is None:
            st["nofit"] += 1
            continue
        cand, how = r
        try:
            if zlib.decompress(cand) != new or len(cand) != e - s:
                st["failed"] += 1
                continue
        except Exception:
            st["failed"] += 1
            continue
        out[s:e] = cand
        st["rewritten"] += 1
        if how == "pad":
            st["padded"] += 1
    return bytes(out), st, spans


def apply_patches_outside(m, data: bytes, spans):
    """Equal-length patches of matcher m on data, skipping any patch that touches one of the (start, end) spans. Patches are sorted
    by offset and overlaps resolved like Matcher/Chain.replace_bytes (first one wins)."""
    pt = sorted(m.patches(data), key=lambda x: (x[0], -len(x[1])))
    if not pt:
        return data, 0
    protect = bytearray(len(data))
    for a, e in spans:
        protect[a:e] = b"\x01" * (e - a)
    return _apply_masked(data, pt, protect)


def _apply_masked(data, pt, protect):
    out = bytearray(data)
    n = 0
    last = -1
    for o, r in pt:
        e = o + len(r)
        if o < last or e > len(data) or any(protect[o:e]):
            continue
        out[o:e] = r
        last = e
        n += 1
    return bytes(out), n


def stream_pieces(o, sp):
    """[(stream_offset, container_offset, length)] of one stream of an open OleFileIO (regular or mini stream)."""
    sid = o._find(sp)
    e = o.direntries[sid]
    ss, ms = o.sectorsize, o.mini_sector_size
    fat = o.fat

    def chain(start, tab):
        r, x, seen = [], start, set()
        while tab is not None and x < 0xFFFFFFFA and x not in seen and x < len(tab):
            seen.add(x); r.append(x); x = tab[x]
        return r
    out, left, so = [], e.size, 0
    if e.size < o.minisectorcutoff:
        if o.minifat is None:
            o.loadminifat()
        rootchain = chain(o.root.isectStart, fat)
        per = ss // ms
        for s in chain(e.isectStart, o.minifat):
            if s // per >= len(rootchain):
                break
            take = min(ms, left)
            out.append((so, (rootchain[s // per] + 1) * ss + (s % per) * ms, take))
            so += take; left -= take
    else:
        for s in chain(e.isectStart, fat):
            take = min(ss, left)
            out.append((so, (s + 1) * ss, take))
            so += take; left -= take
    return out


def container_spans(out_bytes: bytes, stream_spans: dict):
    """Map {stream path: [(start, end) in stream]} to a protect mask (1 = compressed block byte) over the whole container."""
    import olefile
    protect = bytearray(len(out_bytes))
    if not stream_spans:
        return protect
    o = olefile.OleFileIO(io.BytesIO(out_bytes))
    try:
        for sp, spans in stream_spans.items():
            pieces = stream_pieces(o, list(sp))
            for a, e in spans:
                for so, co, ln in pieces:
                    lo, hi = max(a, so), min(e, so + ln)
                    if lo < hi:
                        protect[co + lo - so: co + hi - so] = b"\x01" * (hi - lo)
    finally:
        o.close()
    return protect


def patch_container(m, raw: bytes, protect):
    """Equal-length patches of m over the whole container, never touching protected (compressed block) bytes."""
    pt = sorted(m.patches(raw), key=lambda x: (x[0], -len(x[1])))
    return _apply_masked(raw, pt, protect) if pt else (raw, 0)


def unowned_mask(raw: bytes):
    """bytearray, 1 where a byte belongs to a stream's data, 0 elsewhere (free sectors, slack, FAT/directory, free mini sectors)."""
    import olefile
    n = len(raw)
    bm = bytearray(n)
    o = olefile.OleFileIO(io.BytesIO(raw))
    try:
        ss, ms = o.sectorsize, o.mini_sector_size
        if o.minifat is None:
            o.loadminifat()
        fat = o.fat

        def chain(start, tab):
            s, x, seen = [], start, set()
            while x < 0xFFFFFFFA and x not in seen and tab is not None and x < len(tab):
                seen.add(x); s.append(x); x = tab[x]
            return s
        rootchain = chain(o.root.isectStart, fat)
        mini_off = [(s + 1) * ss for s in rootchain]
        for e in o.direntries:
            if e is None or e.entry_type != 2:
                continue
            if e.size < o.minisectorcutoff:
                left = e.size
                for s in chain(e.isectStart, o.minifat):
                    per = ss // ms
                    if s // per >= len(mini_off):
                        break
                    p = mini_off[s // per] + (s % per) * ms
                    take = min(ms, left)
                    bm[p:min(p + take, n)] = b"\x01" * max(0, min(p + take, n) - p)
                    left -= ms
            else:
                left = e.size
                for s in chain(e.isectStart, fat):
                    p = (s + 1) * ss
                    take = min(ss, left)
                    bm[p:min(p + take, n)] = b"\x01" * max(0, min(p + take, n) - p)
                    left -= ss
    finally:
        o.close()
    return bm


def structural_mask(raw: bytes):
    """1 for the header, directory, FAT / DIFAT / mini-FAT sectors (never patched)."""
    import olefile
    bm = bytearray(len(raw))
    o = olefile.OleFileIO(io.BytesIO(raw))
    try:
        ss = o.sectorsize
        bm[0:ss] = b"\x01" * min(ss, len(raw))
        fat = o.fat

        def mark(s):
            p = (s + 1) * ss
            bm[p:p + ss] = b"\x01" * max(0, min(ss, len(raw) - p))
        for i, v in enumerate(fat):
            if v in (0xFFFFFFFD, 0xFFFFFFFC):
                mark(i)
        for first in (o.first_dir_sector, o.first_mini_fat_sector):
            x, seen = first, set()
            while x < 0xFFFFFFFA and x not in seen and x < len(fat):
                seen.add(x); mark(x); x = fat[x]
    finally:
        o.close()
    return bm


def patch_unowned(m, raw: bytes, protect=None):
    """Apply matcher m only where every patched byte is unowned by any stream (free sectors, slack after stream ends, free mini
    sectors) and outside header / directory / FAT sectors and compressed blocks."""
    pt = sorted(m.patches(raw), key=lambda x: (x[0], -len(x[1])))
    if not pt:
        return raw, 0
    bm = unowned_mask(raw)
    st = structural_mask(raw)
    mask = bytearray(a | b for a, b in zip(bm, st))
    if protect is not None:
        mask = bytearray(a | b for a, b in zip(mask, protect))
    return _apply_masked(raw, pt, mask)


def short_matcher(fmap):
    """Matcher for 3-character field-derived accounts (whole tokens) that are not dictionary words or generic words."""
    from .matcher import Matcher
    from . import fields
    try:
        from .ident import english_words
        words = english_words()
    except Exception:
        words = set()
    items = []
    for o, p in fmap.values():
        low = o.lower()
        if (len(o) == 3 and o.isalpha() and low not in words and low not in fields.GENERIC_CONTENT and low not in fields.PLACEHOLDERS
                and len(p) == 3):
            items.append((o, p))
    return Matcher(items, min_len=3) if items else None


def ascii_tail_pass(fmap, data: bytes, spans=()):
    """ISolidWorksInformation style streams: an ASCII value followed by non-text bytes (high bytes) is not a token for the
    byte matcher. Replace whole-ASCII-token occurrences (neighbours not [A-Za-z0-9]) of the field values, high bytes ignored."""
    from .registry import _case_like
    from . import fields
    items = [(o, p) for o, p in fmap.values() if len(o) >= 4 and o.isascii() and len(p) == len(o)
             and (fields.content_safe(o) or o.lower() in getattr(fields, "ACCOUNT_LIKE", ()))]
    if not items:
        return data, 0
    items.sort(key=lambda x: -len(x[0]))
    look = {o.lower(): (o, p) for o, p in items}
    rx = re.compile(rb"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % b"|".join(re.escape(o.encode()) for o, _ in items), re.I)
    out = bytearray(data)
    n = 0
    for m in rx.finditer(data):
        if any(a < m.end() and m.start() < e for a, e in spans):          # never inside a compressed block
            continue
        o, p = look[m.group(0).decode().lower()]
        t = m.group(0).decode()
        out[m.start():m.end()] = (p if t == o else _case_like(p, t)).encode()
        n += 1
    return bytes(out), n


_ANSI_ENCODINGS = ("utf-8", "cp1252", "gbk", "big5", "shift_jis", "cp949")


class AnsiMatcher:
    """Field values with non-ASCII characters (accented names) as single-byte ANSI text (cp1252) in binary streams. The registry
    matcher only patches ASCII / UTF-16 forms. Whole-token rule on ASCII alphanumerics only (high bytes next to a value do not
    block it: such streams are fixed-size text buffers). Same patches()/replace_bytes() interface as Matcher for OLE use."""
    _nonascii_keys: list = []
    _str_keys: list = []
    str_map: dict = {}
    max_pat = 1

    def __init__(self, fmap, min_len=4):
        from .registry import _case_like
        self.pairs = {}
        for o, p in fmap.values():
            if len(o) < min_len or o.isascii() or len(o) != len(p):
                continue
            for var in {o, o.lower(), o.upper(), o.title()}:
                if var != o and (var.isascii() or len(var) != len(o)):      # e.g. 'ß'.upper() -> 'SS': would rewrite plain ASCII text
                    continue
                pv = p if var == o else _case_like(p, var)
                for enc in _ANSI_ENCODINGS:
                    try:
                        bo = var.encode(enc)
                    except UnicodeEncodeError:
                        continue
                    br = pv.encode("ascii", "replace")
                    if len(br) > len(bo) or bo in self.pairs:
                        continue
                    self.pairs[bo] = br + b"x" * (len(bo) - len(br))       # multi-byte originals: pad like OleField.fit does
        self.rx = (re.compile(rb"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % b"|".join(re.escape(k) for k in sorted(self.pairs, key=len, reverse=True)))
                   if self.pairs else None)

    def __bool__(self):
        return self.rx is not None

    def patches(self, data):
        if self.rx is None:
            return []
        return [(m.start(), self.pairs[m.group(0)]) for m in self.rx.finditer(data)]

    def replace_bytes(self, data):
        out = bytearray(data)
        n = 0
        for o, r in self.patches(data):
            out[o:o + len(r)] = r
            n += 1
        return (bytes(out), n) if n else (data, 0)
