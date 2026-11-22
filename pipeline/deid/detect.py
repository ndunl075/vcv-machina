"""Conservative identity detectors for free text and structured fields. Nothing here touches numbers/geometry."""
from __future__ import annotations
import re

TLDS = ("com net org io de uk fr nl se ch eu us ca info dev edu gov co it es at be pl cz dk no fi jp cn kr au nz ru br in tw app xyz ai me "
        "biz mil int pt ie gr hu ro sk si hr rs bg ua lt lv ee is lu mt cy tr il ae sa eg za ng ke ma mx ar cl pe ve co.uk ac.uk com.au com.br "
        "co.jp co.nz tech online store site cloud design engineering").split()
_TLD_ALT = "|".join(sorted((re.escape(t) for t in TLDS), key=len, reverse=True))
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@((?:[A-Za-z0-9-]{1,63}\.)+(?:TLDS))(?![\w-])".replace("TLDS", _TLD_ALT), re.I)
DOMAIN_RE = re.compile(r"(?<![\w@.-])((?:[A-Za-z0-9][A-Za-z0-9-]{0,62}\.)+(?:%s))(?![\w-])" % _TLD_ALT, re.I)
URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s'\"<>)\]]+", re.I)
PHONE_RE = re.compile(r"(?i)\b(?:tel(?:ephone)?|phone|fax|mobile|mob|cell|gsm)\b\.?\s*[:=]?\s*(\+?\d[\d\s().\-/]{6,18}\d)")
COPY_RE = re.compile(r"(?:[Cc]opyright|COPYRIGHT)\s*(?:\([cC]\)|\u00a9)?\s*(?:\d{4}(?:\s*[-,\u2013]\s*\d{4})*\s*)?(?:by\s+)?"
                     r"|(?:\u00a9|\([cC]\))\s*(?:\d{4}(?:\s*[-,\u2013]\s*\d{4})*\s*)(?:by\s+)?")
_HOLDER = re.compile(r"([A-Z\u00c0-\u00dc][^\n\r<>|*\"]{2,60}?)(?=\s*(?:[.,;<\n\r]|[Aa]ll rights|\*/|$))")
HOLDER_BAD_FIRST = {"all", "the", "free", "notice", "holder", "owner", "protected", "information", "by", "of", "and", "in", "this", "owned",
                    "for", "to", "or", "is", "a", "an", "as", "with", "see", "license", "licence", "permission", "statement", "law", "laws"}
USERPATH_RE = re.compile(r"(?:(?<![\w])/(?:home|Users)/|[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/])([A-Za-z0-9._ -]{2,32}?)(?=[\\/])")
GEN_USERS = {"user", "users", "admin", "administrator", "root", "public", "default", "guest", "shared", "owner", "pi", "ubuntu", "test",
             "student", "all users", "default user", "runner", "build", "vagrant", "docker", "tmp", "temp", "home", "nobody", "share", "pc", "laptop",
             "desktop", "dell", "mac", "macbook", "workspace", "work", "john", "anonymous", "unknown", "author", "username", "name", "your name"}

PERSON_PLACEHOLDERS = {"", "unknown", "author", "none", "n/a", "na", "-", "anonymous", "user", "admin", "administrator", "owner", "me", "noname",
                       "undefined", "null", "tbd", "name", "your name", "creator", "company", "organization", "organisation", "autodesk",
                       "solidworks", "dassault systemes", "freecad", "inventor", "microsoft", "adobe", "pc", "default", "test", "sample", "student"}
SOFTWARE_WORDS = {"freecad", "solidworks", "autodesk", "inventor", "fusion", "fusion 360", "catia", "creo", "ptc", "pro/engineer", "siemens", "nx",
                  "solid edge", "onshape", "blender", "open cascade", "opencascade", "microsoft", "adobe", "acrobat", "illustrator", "inkscape",
                  "libreoffice", "openoffice", "word", "excel", "cadquery", "openscad", "kicad", "altium", "eagle", "step", "iges", "dassault",
                  "dassault systemes", "parasolid", "acis", "spatial", "ansys", "cadence", "mentor", "draftsight", "autocad", "ilogic", "revit",
                  "sketchup", "rhino", "rhinoceros", "mcneel", "bentley", "microstation", "vectorworks", "nanocad", "bricscad", "librecad", "qcad",
                  "cadmai", "tinkercad", "meshlab", "cura", "slic3r", "prusaslicer", "simplify3d", "netfabb", "materialise", "3d systems", "stratasys"}


def is_generic_person(v: str) -> bool:
    t = v.strip().strip("'\"").lower()
    if t in PERSON_PLACEHOLDERS or t in SOFTWARE_WORDS:
        return True
    if len(t) < 3 or not re.search(r"[a-z]", t):
        return True
    if re.fullmatch(r"[\d\W_]+", t):
        return True
    return False


def find_emails(text: str):
    return [(m.group(1), m.group(2)) for m in EMAIL_RE.finditer(text)]


def find_domains(text: str):
    return [m.group(1) for m in DOMAIN_RE.finditer(text)]


def find_user_paths(text: str):
    out = []
    for m in USERPATH_RE.finditer(text):
        u = m.group(1).strip()
        if u.lower() not in GEN_USERS and len(u) >= 3:
            out.append(u)
    return out


def find_copyright_holders(text: str):
    out = []
    for m in COPY_RE.finditer(text):
        hm = _HOLDER.match(text, m.end())
        if not hm:
            continue
        h = hm.group(1).strip(" .,;:-")
        toks = h.split()
        if len(h) < 5 or len(toks) > 6 or toks[0].lower() in HOLDER_BAD_FIRST or is_generic_person(h):
            continue
        if h.lower() in ("the authors", "the author", "contributors", "the contributors"):
            continue
        out.append(h)
    return out


def find_phones(text: str):
    return [m.group(1).strip() for m in PHONE_RE.finditer(text)]
