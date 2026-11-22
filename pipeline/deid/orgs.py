"""Organisation and copyright-holder discovery anywhere in the visible text of a file (precision comes from the legal-form / institution
word, recall from not looking at the page layout). Vendors, manufacturers, universities and publishers are all in; only generic heads
('Precision Engineering'), standards bodies and software products are out. Candidates are (kind, value[, 'label']); 'label' = weaker
evidence accepted by ident.strict_ok (copyright / property-of statements)."""
from __future__ import annotations
import re

# legal forms: case-insensitive ones, and ones that are only accepted as spelled (short words that are also ordinary words)
_LEGAL_CI = {"inc", "incorporated", "llc", "ltd", "limited", "gmbh", "kg", "corp", "corporation", "company", "mfg", "pty", "plc", "sarl", "srl", "spa", "ohg",
             "gbr", "ltda", "bhd", "sdn", "kk", "s.a", "s.a.", "s.r.l", "s.r.l.", "s.p.a", "s.p.a.", "b.v", "b.v.", "n.v", "n.v.", "k.k", "k.k.", "e.v", "e.v.",
             "a/s", "gmbh&co", "kft", "sas", "aktiengesellschaft", "manufacturing", "co.,", "inc.,", "ltd.,"}
_LEGAL_CS = {"Co", "Co.", "CO", "CO.", "AG", "SA", "AB", "Oy", "OY", "BV", "NV", "AS", "A/S", "Oyj", "LP", "LLP", "PLC"}
_WEAK_CI = {"technologies", "technology", "industries", "systems", "robotics", "electronics", "electric", "instruments", "laboratories", "labs", "optics",
            "photonics", "motors", "controls", "automation", "tooling", "tools", "machinery", "products", "solutions", "plastics", "engineering"}
_INST = {"university", "universität", "universitat", "université", "universite", "universidad", "università", "universiteit", "universidade", "institute", "institut",
         "instituto", "istituto", "college", "laboratory", "laboratorium", "laboratoire", "academy", "hochschule", "polytechnic", "akademie", "observatory"}
_CONN = {"of", "for", "de", "der", "di", "von", "zu", "du", "für", "van", "and", "&", "und", "del", "la", "le", "the"}
_LEAD_DROP = {"the", "a", "an", "by", "from", "at", "our", "your", "its", "this", "these", "all", "see", "visit", "contact", "copyright", "property", "of", "to", "and", "for",
              "with", "in", "on", "as", "is", "are", "was", "www", "http", "https", "email", "e-mail", "tel", "fax", "phone", "date", "drawn", "checked", "approved",
              "made", "manufactured", "produced", "designed", "supplied", "courtesy", "owned", "belongs", "licensed", "provided", "published", "printed", "prepared", "submitted",
              "customer", "client", "supplier", "vendor", "manufacturer", "company", "name", "title", "page", "sheet", "scale", "material", "revision", "rev", "unit", "units",
              "proprietary", "confidential", "internal", "external", "mr", "mrs", "ms", "dr", "prof"}
_COUNTRY = {"switzerland", "germany", "france", "italy", "spain", "usa", "america", "china", "japan", "india", "england", "canada", "europe", "australia", "uk", "us", "korea",
            "netherlands", "sweden", "norway", "denmark", "finland", "austria", "belgium", "poland", "brazil", "mexico", "russia", "taiwan", "singapore", "ireland", "portugal"}
_STANDARDS = {"iso", "din", "ansi", "asme", "iec", "jis", "bsi", "astm", "sae", "ieee", "nema", "ul", "csa", "en", "api", "aws", "asm", "nfpa", "ansi/asme", "iso/iec"}
_TOK = re.compile(r"[^\s]+")
_HOLDER_CUT = re.compile(r"(?i)\ball\s+rights|\bunauthori[sz]ed|\bthis\s+(?:document|drawing|file|work|material)|\bis\s+(?:the|a|an)\b|[;|]|\s[-–—]\s|\s{3,}|\bwww\.|https?://|@|\bpage\b|\bplease\b|\bpermission\b|\bcontact\b|\bsee\b")
_CPY = re.compile(r"(?i)(?:©|\(c\)|\bcopyright\b)[\s:]*(?:\(c\)|©)?[\s:]*(?:(?:19|20)\d{2}(?:\s*[-–,/]\s*(?:19|20)?\d{2,4})*[\s,.:;-]*)*([^\n]{3,100})")
_PROP = re.compile(r"(?i)\b(?:property\s+of|proprietary\s+(?:to|of)|confidential(?:\s+and\s+proprietary)?(?:\s+property)?\s+(?:to|of)|owned\s+by|courtesy\s+of|"
                   r"eigentum\s+(?:der|des|von)|propiedad\s+de|propriété\s+(?:de|du))[:\s]+([^\n]{3,100})")
_dict = None


def _d():
    global _dict
    if _dict is None:
        from .ident import english_words
        _dict = english_words()
    return _dict


def _strip(t: str) -> str:
    return t.strip(",;:()[]{}\"'“”‘’")


def _is_legal(t: str) -> bool:
    s = _strip(t)
    s2 = s.rstrip(".,")
    return (s.lower() in _LEGAL_CI or s2.lower() in _LEGAL_CI or s in _LEGAL_CS or s2 in _LEGAL_CS)


_YEARISH = re.compile(r"^(?:19|20)\d{2}(?:[-–/,.]\d{2,4})*$|^\d+$")
GENERIC_HEADS = {"research", "technology", "technical", "mechanical", "engineering", "applied", "advanced", "general", "national", "international", "state", "public",
                 "private", "royal", "federal", "central", "new", "old", "school", "design", "science", "sciences", "medical", "medicine", "physics", "chemistry",
                 "computer", "electrical", "industrial", "civil", "aerospace", "robotics", "standards", "standard", "standardization", "normung", "mechanics", "materials",
                 "manufacturing", "production", "department", "faculty", "global", "american", "european", "united", "states", "precision"}


def _capital(t: str) -> bool:
    s = _strip(t)
    if not s or s.endswith(":") or _YEARISH.match(s):
        return False
    return (s[0].isupper() or (s[0].isdigit() and any(c.isalpha() for c in s))) and not _is_legal(t)


def _proper_head(tokens) -> list:
    """Drop leading sentence words / countries / labels; returns the remaining head tokens."""
    from .pdftext import STOP
    out = list(tokens)
    while out:
        w = _strip(out[0]).lower().rstrip(".")
        if w in _LEAD_DROP or w in _COUNTRY or (w in STOP and w not in _d() - STOP) or w in _STANDARDS:
            out.pop(0)
        else:
            break
    return out


def _bad_head(head) -> bool:
    from .pdftext import STOP
    lows = [_strip(t).lower().rstrip(".") for t in head]
    if not lows:
        return True
    if any(w in _STANDARDS for w in lows):
        return True
    if any(w in STOP and len(w) > 2 for w in lows) and all(w in STOP or w in _d() for w in lows):
        return True
    if any(w in ("standards", "standard", "standardization", "normung") for w in lows):
        return True
    return all(w in _d() or w in _CONN or len(w) < 2 for w in lows)       # nothing proper in the head ('Final Engineering')


def _bad_inst(body) -> bool:
    lows = [_strip(t).lower().rstrip(".") for t in body]
    if not lows or any(w in _STANDARDS or w in ("standards", "standard", "normung") for w in lows):
        return True
    return all(w in GENERIC_HEADS or w in _CONN or len(w) < 2 for w in lows)


def _org_in_line(toks: list, out: list):
    n = len(toks)
    i = 0
    while i < n:
        t = toks[i]
        low = _strip(t).lower().rstrip(".")
        kind = None
        if _is_legal(t):
            kind = "legal"
        elif low in _INST:
            kind = "inst"
        elif low in _WEAK_CI:
            kind = "weak"
        if kind is None:
            i += 1
            continue
        # extend the tail over a run of legal tokens (Co. Ltd, Mfg Co, Sdn Bhd)
        j = i
        if kind == "weak" and i + 1 < n and (_is_legal(toks[i + 1]) or _strip(toks[i + 1]).lower().rstrip(".") in _WEAK_CI):
            i += 1
            continue
        if kind == "legal":
            while True:
                if j + 1 < n and _is_legal(toks[j + 1]):
                    j += 1
                elif j + 2 < n and _strip(toks[j + 1]).lower() in ("&", "und", "and") and _is_legal(toks[j + 2]):
                    j += 2
                else:
                    break
        end = j + 1
        # institutions: 'University of X Y', 'Institute for X'
        if kind in ("inst",) and j + 2 < n and _strip(toks[j + 1]).lower() in _CONN:
            k = j + 2
            while k < n and k < j + 5 and (_capital(toks[k]) or _strip(toks[k]).lower() in ("of", "for", "de", "and", "&")) and not toks[k - 1].endswith((".", ";", ":")):
                k += 1
            while k > j + 2 and _strip(toks[k - 1]).lower() in _CONN:
                k -= 1
            if k > j + 2:
                end = k
        # head: capitalised tokens before the keyword
        s = i
        while s > 0 and i - s < 5:
            pv = toks[s - 1]
            if s < i and pv.endswith((",", ".", ";", ":", "!")) and not (pv.endswith(".") and len(_strip(pv)) <= 3):
                break
            if _is_legal(pv):
                break
            if _capital(pv) or _strip(pv).lower() in ("&", "and", "und", "of", "de", "van", "von", "du"):
                s -= 1
            else:
                break
        head = _proper_head(toks[s:i])
        while head and _strip(head[-1]).lower() in _CONN:
            head.pop()
        tail_has_name = end > j + 1
        cand = head + toks[i:end]
        ok = False
        if kind == "legal":
            ok = bool(head) and not _bad_head(head)
        elif kind == "weak":
            ok = bool(head) and not _bad_head(head) and any(_strip(w).lower() not in _d() for w in head)
        else:  # institution: proper words either side
            body = head + toks[j + 2:end]
            ok = bool(body) and not _bad_inst(body) if (head or tail_has_name) else False
        if ok and 2 <= len(cand) <= 9:
            v = " ".join(cand).strip(" ,;:.-")
            v = re.sub(r"\s+,", ",", v)
            if len(v) >= 6:
                out.append(("company", v))
        i = end if end > i else i + 1


def org_candidates(text: str) -> list:
    out: list = []
    lines = [re.sub(r"[\s ]+", " ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    for k, ln in enumerate(lines):
        if len(ln) > 300:
            continue
        toks = _TOK.findall(ln)
        _org_in_line(toks, out)
        # name wrapped over two lines: 'Werkzeug-Einrichtungen' / 'GmbH' (second line starts with the legal form)
        if k + 1 < len(lines) and len(toks) <= 6:
            nt = _TOK.findall(lines[k + 1])
            if nt and _is_legal(nt[0]) and not _is_legal(toks[-1]):
                _org_in_line(toks + nt[:2], out)
    return out


def _holder(raw: str):
    s = re.sub(r"[\s ]+", " ", raw).strip()
    m = _HOLDER_CUT.search(s)
    if m:
        s = s[: m.start()]
    s = s.strip(" ,;:.-–—*•|©")
    s = re.sub(r"\s*\((?:c|r|tm)\)\s*$", "", s, flags=re.I).strip(" ,;:-")
    toks = s.split()
    if not toks or len(toks) > 8 or len(s) < 3 or not (s[0].isupper() or s[0].isdigit()):
        return None
    while toks and _strip(toks[0]).lower() in _LEAD_DROP and _strip(toks[0]).lower() not in ("the",):
        toks.pop(0)
    if toks and _strip(toks[0]).lower() == "the":
        toks.pop(0)
    if not toks:
        return None
    if re.search(r"\d{3,}|[<>=]", " ".join(toks)):
        return None
    if any(w[0].islower() and w.lower() not in _CONN and not _is_legal(w) for w in toks):
        # sentence continues in lower case ('Acme Inc is ...'): keep the capitalised prefix
        k = 0
        while k < len(toks) and (toks[k][0].isupper() or toks[k].lower() in _CONN or _is_legal(toks[k])):
            k += 1
        toks = toks[:k]
        if not toks:
            return None
    while toks and _strip(toks[-1]).lower() in _CONN:
        toks.pop()
    v = " ".join(toks).strip(" ,;:.-")
    return v if len(v) >= 3 else None


def holder_candidates(text: str) -> list:
    out: list = []
    for rx in (_CPY, _PROP):
        for m in rx.finditer(text):
            v = _holder(m.group(1))
            if not v:
                continue
            from . import ident
            toks = v.split()
            if any(_is_legal(t) for t in toks) or any(_strip(t).lower() in _INST for t in toks):
                out.append(("company", v, "label"))
            elif len(toks) >= 2 and ident.strict_ok("person", v, True):
                out.append(("person", v, "label"))
            else:
                out.append(("company", v, "label"))
    return out


def candidates(text: str) -> list:
    return org_candidates(text) + holder_candidates(text)
