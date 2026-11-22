"""Multi-pattern replacement of registry identities in bytes / str (ASCII, UTF-8, UTF-16LE, %20 and case variants)."""
from __future__ import annotations
import re
from urllib.parse import quote
try:
    import ahocorasick_rs as _ac
except Exception:  # pragma: no cover
    _ac = None

_SEPS = "-_ ."


def distinctive(o: str, long_len: int = 12) -> bool:
    """True when o may be replaced inside a longer token (digits, separators, @, CamelCase or very long). Plain words may only
    be replaced as whole tokens, so 'finition' never changes 'Definition'."""
    return (any(c.isdigit() for c in o) or any(c in "-_ .@/\\" for c in o) or len(o) >= long_len
            or any(c.isupper() for c in o[1:]) and any(c.islower() for c in o))


def _variants(orig: str, pseudo: str):
    """Yield (original_variant, pseudonym_variant) pairs. Same length always."""
    seen = set()
    def add(a, b):
        if a and a not in seen and len(a) == len(b):
            seen.add(a)
            yield a, b
    yield from add(orig, pseudo)
    yield from add(orig.lower(), pseudo.lower())
    yield from add(orig.upper(), pseudo.upper())
    if re.search(r"[-_ ]", orig):
        for sep in "-_ ":
            o2 = re.sub(r"[-_ ]", sep, orig)
            p2 = re.sub(r"[-_ ]", sep, pseudo)
            yield from add(o2, p2)
            yield from add(o2.lower(), p2.lower())
            yield from add(o2.upper(), p2.upper())


class Matcher:
    def __init__(self, items, min_len=4, boundary_len=7):
        """items: iterable of (original, pseudonym). Originals shorter than min_len are ignored. Originals shorter than
        boundary_len only match as whole tokens (neighbours not alphanumeric)."""
        self.pats8: list[bytes] = []
        self.rep8: list[bytes] = []
        self.need_b8: list[bool] = []
        self.pats16: list[bytes] = []
        self.rep16: list[bytes] = []
        self.need_b16: list[bool] = []
        self.str_map: dict[str, str] = {}
        seen8, seen16 = set(), set()
        for o, p in items:
            if len(o) < min_len or o == p:
                continue
            nb_o = not distinctive(o)
            for ov, pv in _variants(o, p):
                nb = nb_o
                try:
                    b8, r8 = ov.encode("utf-8"), pv.encode("utf-8")
                except UnicodeEncodeError:
                    continue
                if b8 not in seen8 and len(b8) == len(r8):
                    seen8.add(b8); self.pats8.append(b8); self.rep8.append(r8); self.need_b8.append(nb)
                elif b8 not in seen8:   # non-ASCII original: text-only replacement, no byte patch
                    pass
                self.str_map[ov] = pv
                b16, r16 = ov.encode("utf-16le"), pv.encode("utf-16le")
                if b16 not in seen16:
                    seen16.add(b16); self.pats16.append(b16); self.rep16.append(r16); self.need_b16.append(nb)
                if " " in ov:
                    q = quote(ov, safe="/")
                    qp = quote(pv, safe="/")
                    if q != ov and q.encode() not in seen8:
                        seen8.add(q.encode()); self.pats8.append(q.encode()); self.rep8.append(qp.encode()); self.need_b8.append(nb)
                        self.str_map[q] = qp
        self.ac8 = self._build(self.pats8)
        self.ac16 = self._build(self.pats16)
        # str side: longest-first regex is fine for path-length strings; use AC over utf-8 for large text too
        self._str_keys = sorted(self.str_map, key=len, reverse=True)
        self._nonascii_keys = [k for k in self._str_keys if not k.isascii()]

    @staticmethod
    def _build(pats):
        if not pats or _ac is None:
            return None
        return _ac.AhoCorasick([p.decode('latin-1') for p in pats], matchkind=_ac.MatchKind.LeftmostLongest)  # latin-1: 1 char == 1 byte

    # ---- bytes ----------------------------------------------------------------------------------------------
    @staticmethod
    def _isal(b: int) -> bool:
        return (48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122) or b >= 128

    def _apply(self, data: bytes, ac, pats, reps, need_b, wide: bool):
        if ac is None or not data:
            return data, 0
        ms = ac.find_matches_as_indexes(data.decode('latin-1'), overlapping=False)
        if not ms:
            return data, 0
        out = bytearray(data)
        n = 0
        step = 2 if wide else 1
        for idx, s, e in ms:
            if need_b[idx]:
                if wide:
                    if s >= 2 and data[s - 1] == 0 and self._isal(data[s - 2]):
                        continue
                    if e + 1 < len(data) and data[e + 1] == 0 and self._isal(data[e]):
                        continue
                else:
                    if (s > 0 and self._isal(data[s - 1])) or (e < len(data) and self._isal(data[e])):
                        continue
            if wide and s % 2 and False:
                continue
            out[s:e] = reps[idx]
            n += 1
        return (bytes(out), n) if n else (data, 0)

    def _patches(self, data, ac, reps, need_b, wide):
        if ac is None or not data:
            return []
        out = []
        for idx, s, e in ac.find_matches_as_indexes(data.decode('latin-1'), overlapping=False):
            if need_b[idx]:
                if wide:
                    if s >= 2 and data[s - 1] == 0 and self._isal(data[s - 2]):
                        continue
                    if e + 1 < len(data) and data[e + 1] == 0 and self._isal(data[e]):
                        continue
                elif (s > 0 and self._isal(data[s - 1])) or (e < len(data) and self._isal(data[e])):
                    continue
            out.append((s, reps[idx]))
        return out

    def patches(self, data: bytes):
        """[(offset, replacement_bytes)] for an in-place equal-length patch of data (ASCII/UTF-8 and UTF-16LE)."""
        p = self._patches(data, self.ac8, self.rep8, self.need_b8, False)
        p += self._patches(data, self.ac16, self.rep16, self.need_b16, True)
        return p

    max_pat = property(lambda self: max([len(x) for x in self.pats8 + self.pats16] + [1]))

    def replace_bytes(self, data: bytes):
        data, n1 = self._apply(data, self.ac8, self.pats8, self.rep8, self.need_b8, False)
        data, n2 = self._apply(data, self.ac16, self.pats16, self.rep16, self.need_b16, True)
        return data, n1 + n2

    def count_bytes(self, data: bytes) -> int:
        return self.replace_bytes(data)[1]

    # ---- text -----------------------------------------------------------------------------------------------
    def replace_str(self, s: str):
        if not s or not self._str_keys:
            return s, 0
        if s.isascii() and not self._nonascii_keys:
            pass
        b, n = self._apply(s.encode("utf-8", "surrogatepass"), self.ac8, self.pats8, self.rep8, self.need_b8, False)
        if n:
            return b.decode("utf-8", "surrogatepass"), n
        # non-ASCII originals (str-only)
        n = 0
        for k in self._nonascii_keys:
            if k in s:
                s = s.replace(k, self.str_map[k]); n += 1
        return s, n

    def find_str(self, s: str):
        """[(matched_text, replacement)] for every registry identity occurring in s (whole-token rules applied)."""
        b = s.encode("utf-8", "surrogatepass")
        out = []
        if self.ac8 is None:
            return out
        for idx, st, e in self.ac8.find_matches_as_indexes(b.decode('latin-1'), overlapping=False):
            if self.need_b8[idx] and ((st > 0 and self._isal(b[st - 1])) or (e < len(b) and self._isal(b[e]))):
                continue
            out.append((b[st:e].decode("utf-8", "replace"), self.rep8[idx].decode("utf-8", "replace")))
        return out


class Chain:
    """Per-file matcher plus the global one, same interface as Matcher for the calls the rewriters make. Both automata scan the ORIGINAL
    data and the per-file matches win where they overlap, so a pseudonym that happens to equal a registered original is never rewritten again."""
    def __init__(self, first, second):
        self.first, self.second = first, second

    max_pat = property(lambda self: max(self.first.max_pat, self.second.max_pat))

    def patches(self, data):
        p1 = self.first.patches(data)
        if not p1:
            return self.second.patches(data)
        spans = sorted((o, o + len(r)) for o, r in p1)
        out = list(p1)
        import bisect
        starts = [a for a, _ in spans]
        for o, r in self.second.patches(data):
            e = o + len(r)
            i = bisect.bisect_right(starts, o) - 1
            if (i >= 0 and spans[i][1] > o) or (i + 1 < len(spans) and spans[i + 1][0] < e):
                continue
            out.append((o, r))
        return sorted(out)

    def replace_bytes(self, data):
        pt = self.patches(data)
        if not pt:
            return data, 0
        out = bytearray(data)
        last = -1
        n = 0
        for o, r in pt:
            if o < last:          # equal-length patches of the same automaton never overlap; belt and braces
                continue
            out[o:o + len(r)] = r
            last = o + len(r)
            n += 1
        return bytes(out), n

    def replace_str(self, s):
        if not s:
            return s, 0
        if self.first._nonascii_keys or self.second._nonascii_keys:      # str-only (non-ASCII) originals: sequential, rare
            s, n1 = self.first.replace_str(s)
            s, n2 = self.second.replace_str(s)
            return s, n1 + n2
        b = s.encode("utf-8", "surrogatepass")
        # UTF-16 patches do not apply to a text string: UTF-8 ones only
        p1 = self.first._patches(b, self.first.ac8, self.first.rep8, self.first.need_b8, False)
        p2 = self.second._patches(b, self.second.ac8, self.second.rep8, self.second.need_b8, False)
        spans = [(o, o + len(r)) for o, r in p1]
        out = list(p1) + [(o, r) for o, r in p2 if not any(a < o + len(r) and o < e for a, e in spans)]
        if not out:
            return s, 0
        buf = bytearray(b)
        for o, r in sorted(out):
            buf[o:o + len(r)] = r
        return buf.decode("utf-8", "surrogatepass"), len(out)

    def find_str(self, s):
        return self.first.find_str(s) + self.second.find_str(s)

    def count_bytes(self, data):
        return self.replace_bytes(data)[1]
