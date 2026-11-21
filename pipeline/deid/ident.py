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
ptc.com siemens.com dassault.com 3ds.com catia.com kicad.org altium.com ansys.com""".split())

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


def add_email(reg: Registry, local: str, domain: str, source: str):
    """Register an e-mail address: local part -> account-style pseudonym, registered domain -> domain pseudonym
    (public mail / vendor domains keep their domain). Both parts stay consistent with their stand-alone entries."""
    full = f"{local}@{domain}"
    if len(local) < 3 or reg.readonly or full in reg.map:
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
    if p == full:
        return
    with reg.lock:
        reg.map[full] = ("email", p)
        reg.scope[full] = "all"
        reg.used.add(p.lower())
        reg.con.execute("INSERT OR IGNORE INTO identity(original,kind,pseudonym,source,scope) VALUES(?,?,?,?,?)", (full, "email", p, source, "all"))


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


def register_candidates(reg: Registry, cands: list[tuple], source: str = ""):
    """cands: (kind_hint, value[, extra]) tuples produced by harvesters. Applies all guards."""
    for c in cands:
        kind, v = c[0], c[1]
        v = v.strip().strip("'\"").strip()
        if not v or len(v) < 3 or len(v) > 90 or not plausible(kind, v):
            continue
        if kind == "email":
            local, _, dom = v.partition("@")
            if local and dom and "." in dom and len(local) >= 3 and not local.lower().startswith(("noreply", "no-reply", "info@")):
                add_email(reg, local, dom, source)
        elif kind == "domain":
            d = v.lower()
            sub, rd = split_domain(d)
            if rd in PUBLIC_DOMAINS or d in PUBLIC_DOMAINS or len(rd) < 6:
                continue
            reg.pseudonym(rd, "domain", source)
        elif kind == "phone":
            digits = re.sub(r"\D", "", v)
            if 7 <= len(digits) <= 15:
                reg.pseudonym(v, "phone", source)
        elif kind == "userpath":
            if v.lower() not in detect.GEN_USERS and not detect.is_generic_person(v):
                reg.pseudonym(v, "account", source, scope="path" if is_generic_phrase(v) else "all")
        elif kind in ("person", "author"):
            if detect.is_generic_person(v) or "\n" in v:
                continue
            k = classify_person_or_company(v)
            if k == "email":
                local, _, dom = v.partition("@")
                add_email(reg, local, dom, source)
            elif is_generic_phrase(v) and k != "company":
                continue
            else:
                reg.pseudonym(v, k, source)
        elif kind in ("company", "org"):
            if detect.is_generic_person(v):
                continue
            reg.pseudonym(v, "company", source, scope="path" if is_generic_phrase(v) else "all")
        elif kind in ("account", "project", "partnumber"):
            reg.pseudonym(v, kind, source, scope="path" if is_generic_phrase(v) else "all")
