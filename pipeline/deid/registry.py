"""Identity registry: original identity -> (kind, pseudonym), deterministic from a secret seed.

Design rules
  * Every pseudonym has exactly the same number of characters as the original (ASCII), so any binary format
    survives in-place replacement and no length field ever needs repairing.
  * pseudonym = f(seed, kind, normalised original, probe); probe > 0 only when two identities would collide.
  * The table lives in a private SQLite file (work folder), never in the output.
"""
from __future__ import annotations
import hashlib, hmac, itertools, os, re, sqlite3, threading
from functools import lru_cache
from . import words as W

KINDS = ("person", "company", "account", "domain", "email", "phone", "address", "project", "partnumber", "path", "other")
_ALNUM = re.compile(r"[A-Za-z0-9]")


def _h(seed: bytes, *parts: str) -> int:
    m = hmac.new(seed, "\x1f".join(parts).encode("utf-8", "surrogatepass"), hashlib.sha256).digest()
    return int.from_bytes(m[:8], "big")


def _stream(seed: bytes, *parts: str):
    """Endless deterministic byte stream."""
    c = 0
    while True:
        yield from hmac.new(seed, ("\x1f".join(parts) + f"\x1e{c}").encode("utf-8", "surrogatepass"), hashlib.sha256).digest()
        c += 1


@lru_cache(maxsize=None)
def _person_index() -> dict[int, list[str]]:
    d: dict[int, list[str]] = {}
    for f in W.FIRST:
        for l in W.LAST:
            d.setdefault(len(f) + 1 + len(l), []).append(f"{f} {l}")
    return d


@lru_cache(maxsize=None)
def _company_index() -> dict[int, list[str]]:
    d: dict[int, list[str]] = {}
    for a in W.COMPANY_A:
        for b in W.COMPANY_B:
            d.setdefault(len(a) + 1 + len(b), []).append(f"{a} {b}")
            for s in W.COMPANY_SUFFIX:
                d.setdefault(len(a) + 1 + len(b) + 1 + len(s), []).append(f"{a} {b} {s}")
    for a in W.COMPANY_A:
        for b in W.COMPANY_A:
            if a != b:
                d.setdefault(len(a) + len(b), []).append(f"{a}{b.lower()}")  # one word, e.g. CedarFalcon
    return d


@lru_cache(maxsize=None)
def _word_index() -> dict[int, list[str]]:
    """lower-case concatenations adjective+noun (account / domain label style)."""
    d: dict[int, list[str]] = {}
    for a in W.ADJ:
        for n in W.NOUN:
            d.setdefault(len(a) + len(n), []).append(a + n)
    for n in W.NOUN:
        for m in W.NOUN:
            if n != m:
                d.setdefault(len(n) + len(m), []).append(n + m)
    return d


def _pad_word(stream, n: int, upper_first=False) -> str:
    cons, vow = "bcdfghklmnprstvz", "aeiou"
    out = []
    for i in range(n):
        b = next(stream)
        out.append((vow if i % 2 else cons)[b % (len(vow) if i % 2 else len(cons))])
    s = "".join(out)
    return s.capitalize() if upper_first else s


def _pick(index: dict[int, list[str]], n: int, h: int, probe: int):
    lst = index.get(n)
    if not lst:
        return None
    return lst[(h + probe * 7919) % len(lst)]


def _digits_tail(s: str, stream, probe: int) -> str:
    """Same-length variation for collisions: overwrite trailing letters by digits."""
    if probe == 0 or len(s) < 3:
        return s
    k = min(len(s) - 2, 1 + probe // 10)
    tail = "".join(str(next(stream) % 10) for _ in range(k))
    return s[: len(s) - k] + tail


def _split_sep(orig: str):
    m = re.search(r"[-_ .]", orig)
    return m.group(0) if m else ""


@lru_cache(maxsize=None)
def _person_index2() -> dict[tuple, list[str]]:
    """(len(first), len(last)) -> names: keeps each token's length so 'Last, First' variants stay equal-length too."""
    d: dict[tuple, list[str]] = {}
    for f in W.FIRST:
        for l in W.LAST:
            d.setdefault((len(f), len(l)), []).append(f"{f} {l}")
    return d


@lru_cache(maxsize=None)
def _long_person_index(n: int):
    """'First Mid Last' / 'First M. Last' names of exactly n characters (for long original names)."""
    mids = {}
    for f in W.FIRST:
        mids.setdefault(len(f), []).append(f)
    mids.setdefault(2, []).extend(chr(c) + "." for c in range(65, 91))
    out = []
    for f in W.FIRST[::3]:
        for l in W.LAST[::2]:
            r = n - len(f) - len(l) - 2
            for m in mids.get(r, [])[:6]:
                out.append(f"{f} {m} {l}")
    return out


def gen_person(seed, orig, probe=0):
    n = len(orig)
    h = _h(seed, "person", orig.lower())
    toks = orig.split(" ")
    s = None
    if len(toks) == 2 and all(toks):
        lst = _person_index2().get((len(toks[0]), len(toks[1])))
        if lst:
            s = lst[(h + probe * 7919) % len(lst)]
    if s is None:
        s = _pick(_person_index(), n, h, probe)
    st = _stream(seed, "person", orig.lower(), str(probe))
    if s is None and n > 12:
        lst = _long_person_index(n)
        if lst:
            s = lst[(h + probe * 7919) % len(lst)]
    if s is None:
        if n >= 7:  # "A. Surname" style
            last = _pick(_word_index(), n - 3, h, probe)
            s = (chr(65 + h % 26) + ". " + (last.capitalize() if last else _pad_word(st, n - 3, True)))
        else:
            s = _pad_word(st, n, True)
    return _digits_tail(s, st, probe) if probe else s


def gen_company(seed, orig, probe=0):
    n = len(orig)
    h = _h(seed, "company", orig.lower())
    s = _pick(_company_index(), n, h, probe)
    st = _stream(seed, "company", orig.lower(), str(probe))
    if s is None:
        s = _pad_word(st, n, True)
    return _digits_tail(s, st, probe) if probe else s


def _fit_tokens(seed, kind, orig, probe, sep, lower=True):
    """Build 'adj-noun[-noun]' style text of exactly len(orig) characters."""
    n = len(orig)
    st = _stream(seed, kind, orig.lower(), str(probe))
    h = _h(seed, kind, orig.lower())
    if not sep:
        s = _pick(_word_index(), n, h, probe)
        if s is None:
            s = _pad_word(st, n)
        return s
    # words joined by sep, trying 2 then 3 words
    for k in (2, 3, 4):
        total = n - (k - 1)
        if total < k * 2:
            continue
        # choose word lengths from candidate pool greedily with hash-driven choices
        pool = W.ADJ + W.NOUN
        by_len: dict[int, list[str]] = {}
        for w in pool:
            by_len.setdefault(len(w), []).append(w)
        res, left = [], total
        for i in range(k):
            remaining = k - i - 1
            options = [L for L in by_len if left - L >= 2 * remaining and (remaining or left == L) and (remaining == 0 or left - L <= 9 * remaining)]
            if not options:
                break
            L = sorted(options)[(h >> (i * 5) + probe) % len(options)]
            lst = by_len[L]
            res.append(lst[(h >> (i * 7 + 3)) % len(lst) if probe == 0 else (h + probe * 31 + i) % len(lst)])
            left -= L
        else:
            if left == 0:
                return sep.join(res)
    return _pad_word(st, n)


def gen_account(seed, orig, probe=0):
    sep = _split_sep(orig)
    s = _fit_tokens(seed, "account", orig, probe, sep)
    st = _stream(seed, "account", orig.lower(), str(probe), "d")
    if probe:
        s = _digits_tail(s, st, probe)
    # mimic case style: Capitalised if original starts uppercase
    if orig[:1].isupper() and orig[1:].lower() == orig[1:]:
        s = s[:1].upper() + s[1:]
    return s


def gen_project(seed, orig, probe=0):
    sep = _split_sep(orig)
    s = _fit_tokens(seed, "project", orig, probe, sep)
    st = _stream(seed, "project", orig.lower(), str(probe), "d")
    if probe:
        s = _digits_tail(s, st, probe)
    if orig[:1].isupper():
        s = s[:1].upper() + s[1:]
    return s


def gen_partnumber(seed, orig, probe=0):
    """Same pattern: digits->digits, letters->letters (case kept), everything else kept."""
    st = _stream(seed, "partnumber", orig, str(probe))
    out = []
    for ch in orig:
        b = next(st)
        if ch.isdigit():
            out.append(str(b % 10))
        elif "a" <= ch <= "z":
            out.append(chr(97 + b % 26))
        elif "A" <= ch <= "Z":
            out.append(chr(65 + b % 26))
        else:
            out.append(ch)
    s = "".join(out)
    return s if s != orig else gen_partnumber(seed, orig, probe + 1000)


def gen_phone(seed, orig, probe=0):
    st = _stream(seed, "phone", orig, str(probe))
    return "".join(str(next(st) % 10) if c.isdigit() else c for c in orig)


def split_domain(dom: str):
    labels = dom.lower().strip(".").split(".")
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "ac", "gov", "edu", "net") and len(labels[-1]) == 2:
        return ".".join(labels[:-3]), ".".join(labels[-3:])
    if len(labels) >= 2:
        return ".".join(labels[:-2]), ".".join(labels[-2:])
    return "", dom.lower()


def gen_domain(seed, orig, probe=0):
    """orig is a registered domain like 'acme-tools.com' (any case); the TLD is kept, the label replaced."""
    dom = orig
    if "." not in dom:
        return gen_account(seed, orig, probe)
    label, _, tld = dom.partition(".")
    if "." in tld and len(tld) > 6:  # something like a.b.c.com -> treat first label only
        pass
    st = _stream(seed, "domain", orig.lower(), str(probe))
    s = _fit_tokens(seed, "domain", label, probe, "-" if "-" in label else "")
    if probe:
        s = _digits_tail(s, st, probe)
    s = s.lower() if label.islower() else s
    return s + "." + tld


GEN = {"person": gen_person, "company": gen_company, "account": gen_account, "project": gen_project,
       "partnumber": gen_partnumber, "phone": gen_phone, "domain": gen_domain,
       "address": gen_company, "other": gen_account, "path": gen_account}


def norm_key(original: str) -> str:
    return re.sub(r"\s+", " ", original.strip())


class Registry:
    """Thread-safe-ish registry. `readonly=True` for pass 2 workers (no DB writes, falls back to pure function)."""

    def __init__(self, db_path: str, seed: bytes, readonly: bool = False):
        self.seed = seed
        self.db_path = db_path
        self.readonly = readonly
        self.lock = threading.Lock()
        self.map: dict[str, tuple[str, str]] = {}       # norm original -> (kind, pseudonym)
        self.scope: dict[str, str] = {}                  # norm original -> "all" | "path"
        self.used: set[str] = set()                      # lowercase pseudonyms in use
        self.rev: dict[str, str] = {}
        self.con = sqlite3.connect(db_path, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS identity(
            original TEXT PRIMARY KEY, kind TEXT NOT NULL, pseudonym TEXT NOT NULL, source TEXT, scope TEXT DEFAULT 'all', hits INTEGER DEFAULT 0)""")
        self.con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_pseudo ON identity(lower(pseudonym))")
        for o, k, p, sc in self.con.execute("SELECT original, kind, pseudonym, scope FROM identity"):
            self.map[o] = (k, p)
            self.scope[o] = sc or "all"
            self.used.add(p.lower())
        if readonly:
            self.con.close()
            self.con = None
        self._originals_lower = {o.lower() for o in self.map}

    def get(self, original: str):
        return self.map.get(norm_key(original))

    def pseudonym(self, original: str, kind: str = "other", source: str = "", scope: str = "all") -> str:
        """Return the pseudonym for original, creating it (collision-free) when this registry is writable."""
        key = norm_key(original)
        if not key:
            return original
        hit = self.map.get(key)
        if hit:
            if scope == "all" and self.scope.get(key) == "path" and not self.readonly:
                self.scope[key] = "all"
                self.con.execute("UPDATE identity SET scope='all' WHERE original=?", (key,))
            return hit[1]
        gen = GEN.get(kind, gen_account)
        with self.lock:
            hit = self.map.get(key)
            if hit:
                return hit[1]
            if self.readonly:
                return gen(self.seed, key, 0)
            probe = 0
            while True:
                p = gen(self.seed, key, probe)
                if p.lower() not in self.used and p.lower() != key.lower() and p.lower() not in self._originals_lower:
                    break
                probe += 1
                if probe > 400:   # tiny identities have too few candidates: leave them alone (reported by verify)
                    self.skipped = getattr(self, "skipped", 0) + 1
                    return key
            self.map[key] = (kind, p)
            self.scope[key] = scope
            self.used.add(p.lower())
            self._originals_lower.add(key.lower())
            self.con.execute("INSERT OR IGNORE INTO identity(original,kind,pseudonym,source,scope) VALUES(?,?,?,?,?)", (key, kind, p, source, scope))
            return p

    def commit(self):
        if self.con:
            self.con.commit()

    def items(self, scope: str | None = None):
        """(original, kind, pseudonym) for all entries, or only those usable at the given scope ('all' = content too)."""
        return [(o, k, p) for o, (k, p) in self.map.items() if scope is None or self.scope.get(o) == scope or scope == "path"]

    def repair(self) -> int:
        """Regenerate entries whose pseudonym length differs from the original (left by an older generator). Returns count."""
        if self.readonly:
            return 0
        lower_o = {o.lower() for o in self.map}
        bad = [(o, k, self.scope.get(o, "all")) for o, (k, p) in self.map.items()
               if len(o) != len(p) or (p.lower() in lower_o and p.lower() != o.lower())]
        for o, k, sc in bad:
            if k == "email":
                from .ident import add_email
                old = self.map.pop(o)[1]
                self.used.discard(old.lower())
                self.con.execute("DELETE FROM identity WHERE original=?", (o,))
                local, _, dom = o.partition("@")
                add_email(self, local, dom, "repair")
                continue
            old = self.map.pop(o)[1]
            self.used.discard(old.lower())
            self.con.execute("DELETE FROM identity WHERE original=?", (o,))
            self.pseudonym(o, k, "repair", scope=sc)
        self.commit()
        return len(bad)
