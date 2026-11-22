"""Per-file identity handling: the identity FIELD values of one file (see fields.py) become pseudonyms that are applied
  * to those fields themselves (any length, any wording),
  * to the rest of the same file (page text, other streams) when the value is specific enough to be safe (fields.content_safe).
Pseudonyms come from Registry.meta_pseudonym: one per case-insensitive value, identical in every file and every format."""
from __future__ import annotations
import re
from . import fields
from .matcher import Matcher
from .registry import _case_like

_AL = "A-Za-z0-9À-￿"


class FileIds:
    def __init__(self, reg, raw_values):
        self.map: dict[str, tuple[str, str]] = {}          # lower -> (spelling, pseudonym)
        if reg is not None:
            for c in fields.field_identities(raw_values):
                p = reg.meta_pseudonym(c)
                if p and p.lower() != c.lower():
                    self.map[c.lower()] = (c, p)
        pats = sorted(self.map, key=len, reverse=True)
        self.rx = re.compile(r"(?<![%s])(?:%s)(?![%s])" % (_AL, "|".join(re.escape(x) for x in pats), _AL), re.I) if pats else None
        content = [(o, p) for o, p in self.map.values() if fields.content_safe(o)]
        self.m = Matcher(content, min_len=4) if content else None              # page text and the like
        allv = [(o, p) for o, p in self.map.values() if len(o) >= 4]
        self.m_all = Matcher(allv, min_len=4) if allv else None                # binary stream of OLE containers (whole tokens)

    def __bool__(self):
        return bool(self.map)

    def _sub(self, m):
        spelling, canon = self.map[m.group(0).lower()]
        t = m.group(0)
        return canon if t == spelling else _case_like(canon, t)

    def apply_text(self, s: str):
        """Replace every identity component in a field text (whole tokens, case-insensitive). Returns (text, count)."""
        if not self.rx or not s:
            return s, 0
        return self.rx.subn(self._sub, s)

    def fit(self, new: str, nbytes: int, wide: bool) -> bytes:
        """Encode a replaced field text to exactly nbytes (pad with letters from the text itself if the original had multi-byte characters)."""
        enc = "utf-16le" if wide else "utf-8"
        b = new.encode(enc, "replace")
        if len(b) > nbytes:
            b = b[:nbytes]
        while len(b) < nbytes:
            b += "x".encode(enc)
        return b[:nbytes]
