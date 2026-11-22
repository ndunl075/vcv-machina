"""Per-file identity handling: the identity FIELD values of one file (see fields.py) become pseudonyms that are applied
  * to those fields themselves (any length, any wording),
  * to the rest of the same file (page text, other streams) when the value is specific enough to be safe (fields.content_safe).
Pseudonyms come from Registry.meta_pseudonym: one per case-insensitive value, identical in every file and every format."""
from __future__ import annotations
import re
from . import fields
from .matcher import Matcher
from .registry import _case_like, Overlay

_BARE_TLDS = {"com", "net", "org", "io", "de", "uk", "fr", "nl", "se", "ch", "eu", "info", "edu", "gov", "dev", "ai", "app", "biz", "us", "ca", "au"}
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
        allv = [(o, p) for o, p in self.map.values() if fields.content_safe(o) or o.lower() in fields.ACCOUNT_LIKE]
        self.m_all = Matcher(allv, min_len=4) if allv else None                # binary stream of OLE containers (whole tokens)

    def add_content(self, pairs):
        """More (original, pseudonym) pairs for page text / stream content (emails, domains, names found in the file's own text)."""
        pairs = [(o, p) for o, p in pairs if o != p and len(o) == len(p)]
        if not pairs:
            return
        have = {o for o, _ in self.map.values()}
        base = [(o, p) for o, p in self.map.values() if fields.content_safe(o)]
        self.m = Matcher(base + [x for x in pairs if x[0] not in have], min_len=4)

    def __bool__(self):
        return bool(self.map)

    def _sub(self, m):
        t = m.group(0)
        ent = self.map.get(t.lower())
        if ent is None:          # lower-casing changed the length / the regex matched through case folding: leave the text alone
            return t
        spelling, canon = ent
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


def person_forms(orig: str, pseudo: str):
    """Other spellings of a 'First [M.] Last' name that must map consistently: 'Last, First', 'Last First', 'F. Last'."""
    a, b = orig.split(" "), pseudo.split(" ")
    if len(a) == 2 and len(b) == 2 and all(a) and all(b):
        return [(f"{a[1]}, {a[0]}", f"{b[1]}, {b[0]}"), (f"{a[1]} {a[0]}", f"{b[1]} {b[0]}"), (f"{a[0][0]}. {a[1]}", f"{b[0][0]}. {b[1]}")]
    if len(a) == 3 and len(b) == 3 and all(a) and all(b):
        return [(f"{a[0]} {a[2]}", f"{b[0]} {b[2]}"), (f"{a[0][0]}. {a[2]}", f"{b[0][0]}. {b[2]}")]
    return []


def text_candidates(text: str) -> list:
    """Candidate identities (kind, value) that the visible text of one file reveals; shared by apply (text_identities) and harvest-meta so
    that every identity apply can find has been registered globally first."""
    from . import detect, harvest, names
    cands: list = []
    try:
        harvest.generic_text_candidates(text, cands)
        from . import orgs
        cands += orgs.candidates(text)
        for n in names.find_person_names(text):
            cands.append(("person", n))
        for d in detect.find_domains(text):       # bare host names ('example.org/wiki'): common registries only, label of 4+ letters
            dl = d.lower()
            tld = dl.rsplit(".", 1)[-1]
            lab = dl.split(".")[-2] if "." in dl else ""
            if tld in _BARE_TLDS and len(lab) >= 4 and re.search(r"[a-z]{3}", lab):
                bare = d[4:] if dl.startswith("www.") else d
                if len(tld) == 2 and not (dl.startswith("www.") or re.search(r"https?://(?:www\.)?" + re.escape(bare), text, re.I)
                                          or re.search(r"@" + re.escape(bare), text, re.I)):
                    continue          # 'use.it' in prose without a missing space
                cands.append(("domain", bare))
    except Exception:
        return []
    return cands


def text_identities(reg, text: str):
    """Identities that only the text of one file reveals: e-mail addresses, domains, phone numbers, user-name paths, copyright
    holders (harvest detectors) and person names (name lists). Pseudonyms: the registry's when it knows the identity, else the
    deterministic first candidate (same generators, same seed), so every file agrees."""
    from . import ident
    cands = text_candidates(text)
    if not cands:
        return []
    tmp = Overlay(reg)          # registered identities come from the registry, the rest from the pure function: no per-file probing
    try:
        ident.register_candidates(tmp, cands, source="text", strict=True)
        out = []
        for o, (k, p) in tmp.map.items():
            g = reg.map.get(o)
            if g is not None and reg.scope.get(o) == "all":
                continue                      # the global matcher already handles it
            pp = g[1] if g is not None else p
            out.append((o, pp))
            if k == "person":
                out.extend(person_forms(o, pp))
        # the exact spellings used in this text (host names and e-mail addresses are case-insensitive: 'Example.Org')
        known = {o for o, _ in out}
        for o, pp in list(out):
            if len(o) < 5:
                continue
            for m in re.finditer(re.escape(o), text, re.I):
                sp = m.group(0)
                if sp not in known:
                    known.add(sp)
                    out.append((sp, pp.lower() if not sp.isupper() else pp.upper()))
        return out
    finally:
        pass
