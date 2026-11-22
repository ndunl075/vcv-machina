"""Turning raw strings found in files into registry entries (classification + generic-word guards)."""
from __future__ import annotations
import gzip, os, re
from . import detect
from .registry import Registry, split_domain

PUBLIC_DOMAINS = set("""gmail.com googlemail.com outlook.com hotmail.com live.com yahoo.com icloud.com me.com aol.com protonmail.com proton.me
github.com gitlab.com bitbucket.org githubusercontent.com example.com example.org example.net localhost autodesk.com solidworks.com
microsoft.com adobe.com w3.org apache.org gnu.org freecadweb.org freecad.org opencascade.com iso.org nist.gov khronos.org python.org
openscad.org inkscape.org creativecommons.org mozilla.org wikipedia.org google.com schemas.microsoft.com purl.org dublincore.org
sourceforge.net readthedocs.io npmjs.com pypi.org stackoverflow.com youtube.com facebook.com twitter.com linkedin.com instagram.com
ptc.com siemens.com dassault.com 3ds.com catia.com kicad.org altium.com ansys.com doi.org orcid.org arxiv.org amazon.com amazon.de ebay.com alibaba.com
aliexpress.com europa.eu sourceforge.net huggingface.co researchgate.net grabcad.com thingiverse.com printables.com mcmaster.com
creativecommons.org osf.io hackaday.io instructables.com
swagelok.com 8020.net misumiusa.com misumi.com semanticscholar.org openreview.net skf.com makerbot.com spie.org wiktionary.org reddit.com microsoft.net
cambridge.org tandfonline.com sidefx.com igus.de igus.com schunk.com boschrexroth.com coopertools.com a360.co vention.io oerlikon.com spacex.com esa.int
taobao.com tumblr.com feedburner.com speedtest.net fast.com freenode.net ubuntu-fr.org engineeringtoolbox.com alldatasheet.com prusa3d.com lulzbot.com
octoprint.org smoothieware.org repetier.com abbyy.com autohotkey.com astm.org asme.org ansi.org din.de beuth.de sae.org ieee.org springer.com wiley.com
elsevier.com sciencedirect.com mdpi.com nature.com acm.org jstor.org scribd.com pinterest.com apple.com mathworks.com festo.com bosch.com abb.com
parker.com timken.com nsk.com ntn.co.jp thk.com hiwin.com omron.com keyence.com sick.com phoenixcontact.com wago.com lenze.com sew-eurodrive.com
mouser.com digikey.com rs-online.com farnell.com newark.com grainger.com fastenal.com mcmaster.com onlinemetals.com protolabs.com xometry.com
sparkfun.com adafruit.com pololu.com banggood.com aliexpress.com dropbox.com wordpress.com blogspot.com wixsite.com""".split())
PUBLIC_SUFFIXES = (".gov", ".mil", ".edu", ".int", ".ac.uk", ".gov.uk", ".edu.au", ".ac.jp", ".go.jp", ".edu.br", ".gov.br", ".edu.cn", ".ac.at")
VENDOR_TOKENS = {"tdk", "smc", "schunk", "misumi", "mcmaster", "loctite", "festo", "bosch", "skf", "igus", "parker", "timken", "omron", "keyence", "yaskawa", "fanuc",
                 "siemens", "abb", "ptc", "autodesk", "dassault", "kuka", "mitsubishi", "hiwin", "thk", "nsk", "ntn", "norelem", "swagelok", "cooper", "apex", "cleco",
                 "taiyo", "murata", "kemet", "vishay", "panasonic", "samsung", "texas", "analog", "microchip", "infineon", "stmicroelectronics", "bourns", "molex", "amphenol"}
_LEGAL = {"gmbh", "inc", "inc.", "ltd", "ltd.", "llc", "corp", "corp.", "co.", "ag", "sa", "s.a.", "s.r.l.", "srl", "spa", "s.p.a.", "bv", "b.v.", "oy", "ab", "plc",
          "kg", "ltda", "pty", "limited", "incorporated", "university", "universität", "universitat", "universidad", "université", "universite", "università",
          "universiteit", "institute", "institut", "instituto", "istituto", "college", "laboratory", "laboratories", "laboratorium", "hochschule", "fachhochschule",
          "polytechnic", "e.v.", "ev", "sarl", "sas"}
_DATEISH = re.compile(r"^\d{1,4}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{1,4}$")
_gaz = None


def _public_host(d: str) -> bool:
    d = d.lower()
    return d in PUBLIC_DOMAINS or d.endswith(PUBLIC_SUFFIXES) or any(d.endswith("." + x) for x in ("google.com", "google.com.mx", "microsoft.com", "wikipedia.org"))


def strict_ok(kind: str, v: str) -> bool:
    """Precision guards for identities found only in a file's visible text (weak detectors)."""
    global _gaz
    if kind in ("project", "address"):
        return False
    if kind == "phone":
        digits = re.sub(r"\D", "", v)
        return len(digits) >= 7 and not _DATEISH.match(v.strip()) and (re.search(r"[+()\-. ]", v) is not None)
    toks = [t for t in re.split(r"\s+", v.strip()) if t]
    if kind in ("person", "author"):
        words = [t for t in toks if len(t.strip(".")) > 1]
        if len(words) < 2:
            return False
        if _gaz is None:
            from .names import gazetteer
            from .pdftext import STOP, ALL_LABELS, _PERSON_BAD
            _gaz = (*gazetteer(), STOP, ALL_LABELS, _PERSON_BAD)
        F, L, STOP, LABELS, BAD = _gaz
        low = [w.lower().strip(".,'-") for w in words]
        if any(w in STOP or w in LABELS or w in BAD or w in VENDOR_TOKENS for w in low):
            return False
        if not any(w in F or w in L for w in low):
            return False
        d = english_words()
        if all(w in d for w in low):
            return False
        return True
    if kind in ("company", "org"):
        low = [t.lower().strip(",()") for t in toks]
        if not any(t in _LEGAL or t.strip(".") in _LEGAL for t in low):
            return False
        if any(t in VENDOR_TOKENS for t in low):
            return False
        d = english_words()
        other = [t for t in low if t not in _LEGAL and t.strip(".") not in _LEGAL and t not in ("of", "the", "for", "und", "and", "&", "de", "der", "für")]
        if not other or all(t in d or t in _LEGAL or len(t) < 2 for t in other):
            return False
        return True
    return True



COMPANY_WORDS = re.compile(r"(?i)\b(inc|ltd|llc|gmbh|corp|corporation|co|company|ag|bv|sa|sarl|srl|spa|oy|ab|as|plc|university|universit[a-z]*|institute|"
                           r"college|school|labs?|laboratory|technologies|technology|systems|industries|engineering|robotics|group|foundation|"
                           r"association|society|consortium|team|club|department|dept|gmbh & co|kg|ltda)\b\.?")

_dict = None


def english_words() -> set[str]:
    global _dict
    if _dict is None:
        _dict = set()
        for p in (os.path.join(os.path.dirname(__file__), "..", "data", "generic_words.txt.gz"),):
            try:
                with gzip.open(p, "rt") as f:
                    _dict = {w.strip() for w in f if w.strip()}
            except OSError:
                pass
    return _dict


def tokens(s: str):
    parts = re.split(r"[-_ .]+", s)
    out = []
    for p in parts:
        out += re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", p)
    return [t for t in out if t]


def is_generic_phrase(s: str) -> bool:
    """True when the string is built only from dictionary words / software names: it must not be replaced inside content."""
    low = s.lower().strip()
    if low in detect.SOFTWARE_WORDS or low in detect.PERSON_PLACEHOLDERS:
        return True
    d = english_words()
    toks = [t.lower() for t in tokens(s)]
    if not toks:
        return True
    if any(t.isdigit() for t in toks):
        return False
    return len(toks) == 1 and (toks[0] in d or toks[0] in detect.SOFTWARE_WORDS)


def classify_person_or_company(v: str) -> str:
    if "@" in v:
        return "email"
    if COMPANY_WORDS.search(v):
        return "company"
    if re.search(r"\s", v.strip()):
        return "person"
    return "account"


def valid_domain(d: str) -> bool:
    """A real host name: at least two labels, last label (or last two, e.g. co.uk) a known TLD, label characters only."""
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", d):
        return False
    labels = d.split(".")
    return labels[-1] in detect.TLDS or ".".join(labels[-2:]) in detect.TLDS


def add_email(reg: Registry, local: str, domain: str, source: str):
    """Register an e-mail address: local part -> account-style pseudonym, registered domain -> domain pseudonym
    (public mail / vendor domains keep their domain). Both parts stay consistent with their stand-alone entries."""
    full = f"{local}@{domain}"
    if len(local) < 3 or reg.readonly or full in reg.map or not valid_domain(domain.lower()):
        return
    d = domain.lower()
    sub, rd = split_domain(d)
    if rd in PUBLIC_DOMAINS or d in PUBLIC_DOMAINS or len(rd) < 6:
        dpseudo = domain
    else:
        dp = reg.pseudonym(rd, "domain", source)
        dpseudo = (domain[: len(domain) - len(rd)] + dp) if sub else dp
    lp = reg.pseudonym(local, "account", source, scope="path") if len(local) >= 4 else local
    p = lp + "@" + dpseudo
    if p == full or len(p) != len(full):
        return
    with reg.lock:
        reg._put(full, "email", p, "all", source)


_OK_CHARS = re.compile(r"^[A-Za-z0-9\u00c0-\u024f .,'_@&()/+:\\-]+$")


def plausible(kind: str, v: str) -> bool:
    """Reject garbage (decoded binary, control characters, symbol soup)."""
    if not _OK_CHARS.match(v):
        return False
    if kind in ("person", "author", "company", "org", "account", "project") and len(v) < 5:
        return False
    letters = sum(c.isalpha() for c in v)
    if letters < max(2, len(v) * 0.5) and kind in ("person", "author", "company", "org", "account", "project"):
        return False
    if kind in ("person", "author", "company", "org"):
        if not re.search(r"[aeiouyAEIOUY\u00c0-\u00ff]", v):
            return False
        # random mixed case inside a single token (aBcDeF) is almost never a name
        for tkn in v.split():
            if len(tkn) > 3 and len(re.findall(r"[a-z][A-Z]", tkn)) >= 2 and not re.match(r"^(Mc|Mac)", tkn):
                return False
    return True


def register_candidates(reg: Registry, cands: list[tuple], source: str = "", strict: bool = False):
    """cands: (kind_hint, value[, extra]) tuples produced by harvesters. Applies all guards."""
    for c in cands:
        kind, v = c[0], c[1]
        v = v.strip().strip("'\"").strip()
        if not v or len(v) < 3 or len(v) > 90 or not plausible(kind, v):
            continue
        if strict and not strict_ok(kind, v):
            continue
        if kind == "email":
            local, _, dom = v.partition("@")
            if local and dom and "." in dom and len(local) >= 3 and not local.lower().startswith(("noreply", "no-reply", "info@")):
                add_email(reg, local, dom, source)
        elif kind == "domain":
            d = v.lower()
            if not valid_domain(d):
                continue
            sub, rd = split_domain(d)
            if rd in PUBLIC_DOMAINS or d in PUBLIC_DOMAINS or len(rd) < 6 or (strict and _public_host(rd)):
                continue
            reg.pseudonym(rd, "domain", source)
        elif kind == "phone":
            digits = re.sub(r"\D", "", v)
            if 7 <= len(digits) <= 15:
                reg.pseudonym(v, "phone", source)
        elif kind == "userpath":
            if re.search(r"[a-z][A-Z][a-z]", v):
                continue
            if v.lower() not in detect.GEN_USERS and not detect.is_generic_person(v):
                reg.pseudonym(v, "account", source, scope="path" if is_generic_phrase(v) else "all")
        elif kind in ("person", "author"):
            if detect.is_generic_person(v) or "\n" in v:
                continue
            if "@" in v:       # "Name (user@host.tld)" -> register the e-mail(s) and the name part separately
                for l, d in detect.find_emails(v):
                    add_email(reg, l, d, source)
                v = re.sub(r"\s*[(<\[]?\s*[\w.+-]+@[\w.-]+\s*[)>\]]?", "", v).strip(" ,;()<>")
                if len(v) < 5 or not plausible("person", v):
                    continue
            k = classify_person_or_company(v)
            if k == "email":
                continue
            elif is_generic_phrase(v) and k != "company":
                continue
            else:
                reg.pseudonym(v, k, source)
        elif kind in ("company", "org"):
            if detect.is_generic_person(v):
                continue
            reg.pseudonym(v, "company", source, scope="path" if is_generic_phrase(v) else "all")
        elif kind == "address":
            reg.pseudonym(v, "address", source)
        elif kind in ("account", "project", "partnumber"):
            reg.pseudonym(v, kind, source, scope="path" if is_generic_phrase(v) else "all")
