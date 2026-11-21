"""Conservative identity detectors for free text and structured fields. Nothing here touches numbers/geometry."""
from __future__ import annotations
import re

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@((?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,24})(?![\w-])")
TLDS = "com net org io de uk fr nl se ch eu us ca info dev edu gov co it es at be pl cz dk no fi jp cn kr au nz ru br in tw app xyz ai me".split()
_TLD_ALT = "|".join(sorted(TLDS, key=len, reverse=True))
DOMAIN_RE = re.compile(r"(?<![\w@.-])((?:[A-Za-z0-9][A-Za-z0-9-]{0,62}\.)+(?:%s))(?![\w-])" % _TLD_ALT, re.I)
URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s'\"<>)\]]+", re.I)
PHONE_RE = re.compile(r"(?i)\b(?:tel(?:ephone)?|phone|fax|mobile|mob|cell|gsm)\b\.?\s*[:=]?\s*(\+?\d[\d\s().\-/]{6,18}\d)")
COPY_RE = re.compile(r"(?i)(?:copyright\s*(?:\(c\)|©)?|©|\(c\))\s*(?:\d{4}(?:\s*[-,–]\s*\d{4})*\s*)?(?:by\s+)?([A-Z][^\n\r<>|*\"]{2,60}?)(?=\s*(?:[.,;<\n\r]|all rights|\*/|$))")
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
        h = m.group(1).strip(" .,;:-")
        if len(h) >= 3 and not is_generic_person(h) and h.lower() not in ("the authors", "the author", "contributors", "the contributors"):
            out.append(h)
    return out


def find_phones(text: str):
    return [m.group(1).strip() for m in PHONE_RE.finditer(text)]
