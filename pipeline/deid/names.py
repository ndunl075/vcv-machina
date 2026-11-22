"""Person names in running text: 'First [M.] Last' where the first token is a known given name and the last a known surname
(public name lists, no corpus data). A token that also occurs in lower case in the same text is a common word and rejects the match."""
from __future__ import annotations
import gzip, os, re

_G = None
_RX = re.compile(r"\b([A-Z][a-z]{2,}|[A-Z]{3,})(?: ([A-Z]\.?))? ([A-Z][a-z]{2,}|[A-Z]{3,})\b")


def gazetteer():
    global _G
    if _G is None:
        d = os.path.join(os.path.dirname(__file__), "..", "data")
        out = []
        for fn in ("first_names.txt.gz", "last_names.txt.gz"):
            try:
                with gzip.open(os.path.join(d, fn), "rt") as f:
                    out.append({w.strip().lower() for w in f if w.strip()})
            except OSError:
                out.append(set())
        _G = tuple(out)
    return _G


def find_person_names(text: str):
    F, L = gazetteer()
    if not F or not L or len(text) < 8:
        return []
    lower_used = set(re.findall(r"\b[a-z]{3,}\b", text))
    out, seen = [], set()
    for m in _RX.finditer(text):
        f, mi, l = m.group(1), m.group(2), m.group(3)
        if f.isupper() != l.isupper():
            continue
        fl, ll = f.lower(), l.lower()
        if fl in F and ll in L and fl not in lower_used and ll not in lower_used:
            s = m.group(0)
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out
