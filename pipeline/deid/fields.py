"""Identity FIELD extraction: values that sit in author / last-saved-by / owner / company style fields of one file.
Unlike the content registry these are taken whatever they look like (short, dictionary words, account names): a field that
exists to hold an identity is an identity. Pure functions, no registry access.

  * OLE property sets (SummaryInformation, DocumentSummaryInformation and the obfuscated copies Inventor keeps): parsed here so a
    value of any length can be located and patched in place (equal length)
  * PDF: Info dictionary, XMP creator-style elements, annotation authors
"""
from __future__ import annotations
import re, struct

FMT_SUMMARY = bytes.fromhex("e085 9ff2 f94f 6810 ab91 0800 2b27 b3d9".replace(" ", ""))
FMT_DOCSUM = bytes.fromhex("02d5 cdd5 9c2e 1b10 9397 0800 2b2c f9ae".replace(" ", ""))
# property ids holding an identity: SummaryInformation 4 author, 8 last saved by; DocumentSummaryInformation 14 manager, 15 company
# Inventor keeps the same facts in its own property sets: Summary Information 4/8, Design Tracking Properties 41, Design Tracking Control 16
FMT_INV_SUMMARY = bytes.fromhex("39de383d8805144cbb3718f4d5dd31c7")
FMT_INV_TRACK = bytes.fromhex("0f3f85324434d1119e930060b03c1ca6")
FMT_INV_CONTROL = bytes.fromhex("30fb61d83631d1119e920060b03c1ca6")
IDENT_PIDS = {FMT_SUMMARY: (4, 8), FMT_DOCSUM: (14, 15), FMT_INV_SUMMARY: (4, 8), FMT_INV_TRACK: (41,), FMT_INV_CONTROL: (16,)}

PLACEHOLDERS = {"", "unknown", "anonymous", "(anonymous)", "none", "n/a", "na", "null", "undefined", "-", "--", "?", "tbd", "nobody",
                "author", "name", "your name", "company", "organization", "organisation", "blank", "default user", "(unknown)", "(none)"}
# never replaced inside page text / stream content, only in the field that holds them
GENERIC_CONTENT = {"administrator", "admin", "user", "users", "owner", "operator", "guest", "default", "master", "first", "student", "test",
                   "demo", "root", "pc", "laptop", "desktop", "portable", "engineer", "designer", "drafter", "author", "name", "company",
                   "nx", "unknown", "anonymous", "none", "support", "service", "office", "home", "work", "main", "mechanical", "design",
                   "engineering", "windows", "mac", "dell", "hp", "lenovo", "cad", "draw", "drawing", "cncs", "autocad", "solidworks",
                   "inventor", "creo", "catia", "autodesk", "dassault", "microsoft", "adobe", "unnamed", "noname", "sample", "temp"}


# ------------------------------------------------------------------------------------------------------ OLE property sets
def _decode(raw: bytes, cp: int | None) -> str:
    for enc in ((("utf-8",) if cp in (65001, None) else ()) + ((f"cp{cp}",) if cp and cp not in (65001, 1200) else ()) + ("cp1252", "latin-1")):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


def parse_propset(data: bytes):
    """Yield (fmtid, pid, kind, offset, nbytes, text) for every string property of a property-set stream.
    kind 'a' = ANSI/UTF-8 bytes (offset/nbytes = the characters without the NUL), 'w' = UTF-16LE. Never raises."""
    out = []
    try:
        if len(data) < 48 or data[:2] != b"\xfe\xff":
            return out
        nsets = struct.unpack_from("<I", data, 24)[0]
        if not 1 <= nsets <= 4:
            return out
        for si in range(nsets):
            fmtid = data[28 + si * 20: 44 + si * 20]
            soff = struct.unpack_from("<I", data, 44 + si * 20)[0]
            if soff + 8 > len(data):
                continue
            size, cnt = struct.unpack_from("<II", data, soff)
            if cnt > 400:
                continue
            props = {}
            for i in range(cnt):
                pid, poff = struct.unpack_from("<II", data, soff + 8 + i * 8)
                props[pid] = soff + poff
            cp = None
            if 1 in props and props[1] + 6 <= len(data) and struct.unpack_from("<I", data, props[1])[0] == 2:
                cp = struct.unpack_from("<H", data, props[1] + 4)[0]
            for pid, off in props.items():
                if off + 8 > len(data):
                    continue
                vt = struct.unpack_from("<I", data, off)[0] & 0xFFFF
                if vt not in (0x1E, 0x1F):
                    continue
                n = struct.unpack_from("<I", data, off + 4)[0]
                if vt == 0x1E:
                    raw = data[off + 8: off + 8 + n]
                    if len(raw) < n:
                        continue
                    raw = raw.split(b"\x00", 1)[0]
                    if raw:
                        out.append((fmtid, pid, "a", off + 8, len(raw), _decode(raw, cp)))
                else:
                    raw = data[off + 8: off + 8 + 2 * n]
                    if len(raw) < 2 * n:
                        continue
                    try:
                        txt = raw.decode("utf-16le")
                    except UnicodeDecodeError:
                        continue
                    txt = txt.split("\x00", 1)[0]
                    if txt:
                        out.append((fmtid, pid, "w", off + 8, 2 * len(txt), txt))
    except Exception:
        return out
    return out


def ole_field_slots(ole):
    """[(stream_path, offset, nbytes, kind, text)] for the identity properties of every property-set stream of an OleFileIO."""
    slots = []
    for sp in ole.listdir(streams=True, storages=False):
        if not sp or not sp[-1].startswith("\x05"):
            continue
        try:
            if ole.get_size(sp) > 400_000:
                continue
            d = ole.openstream(sp).read()
        except Exception:
            continue
        for fmtid, pid, kind, off, nb, txt in parse_propset(d):
            if fmtid in IDENT_PIDS and pid in IDENT_PIDS[fmtid]:
                slots.append((sp, off, nb, kind, txt))
    return slots


# ------------------------------------------------------------------------------------------------------ value handling
_WINUSER = re.compile(r"^([A-Za-z0-9_.-]{2,40})\\([^\\()]{1,60}?)(?:\s*\(([^)]{1,40})\))?$")
_TRAILPAR = re.compile(r"^(.{3,}?)\s+\(([^()]{2,30})\)$")


def clean(v: str) -> str:
    return re.sub(r"[\x00-\x1f�]+", " ", v).strip().strip("'\"").strip()


def components(v: str):
    """'DOMAIN\\user (HOST)' -> [DOMAIN, user, HOST]; 'Name (INI)' -> [Name, INI]; otherwise [v]. Placeholders and e-mail addresses dropped."""
    v = clean(v)
    if not v or v.lower() in PLACEHOLDERS or "@" in v:
        return []
    m = _WINUSER.match(v)
    parts = [m.group(1), m.group(2), m.group(3)] if m else None
    if parts is None:
        m = _TRAILPAR.match(v)
        parts = [m.group(1), m.group(2)] if m else [v]
    out, seen = [], set()
    for p in parts:
        p = clean(p or "")
        if p and p.lower() not in PLACEHOLDERS and p.lower() not in seen and re.search(r"[A-Za-z0-9À-￿]", p):
            seen.add(p.lower())
            out.append(p)
    return out


def content_safe(v: str) -> bool:
    """May this field value also be replaced inside page text / binary streams of the same file? (not generic accounts, not
    tiny, not pure numbers, which could be dimensions)"""
    return len(v) >= 4 and v.lower() not in GENERIC_CONTENT and re.search(r"[A-Za-z\u00c0-\uffff]", v) is not None


# ------------------------------------------------------------------------------------------------------ PDF
_XMP_TAGS = ("dc:creator", "dc:publisher", "dc:contributor", "pdf:Author", "pdfx:Company", "pdfx:Manager", "xmpRights:Owner",
             "xmp:Author", "photoshop:Credit", "Iptc4xmpCore:CreatorContactInfo", "xmpDM:artist")
_XMP_RE = re.compile(r"<(%s)\b[^>]*>(.*?)</\1>" % "|".join(re.escape(t) for t in _XMP_TAGS), re.S)
_TXT = re.compile(r">([^<>]+)<")
INFO_KEYS = ("/Author", "/Manager", "/Company", "/LastAuthor", "/LastModifiedBy", "/Operator")


def pdf_field_values(pdf) -> list[str]:
    """Raw identity field values of an open pikepdf document (Info, XMP, annotation authors)."""
    import pikepdf
    vals = []
    try:
        for k in INFO_KEYS:
            v = pdf.docinfo.get(k)
            if v is not None:
                vals.append(str(v))
    except Exception:
        pass
    try:
        md = pdf.Root.get("/Metadata")
        if md is not None:
            x = md.read_bytes().decode("utf-8", "replace")
            for m in _XMP_RE.finditer(x):
                for t in _TXT.findall("<x>" + m.group(2) + "</x>"):
                    if t.strip():
                        vals.append(t.strip())
    except Exception:
        pass
    try:
        for pg in pdf.pages:
            for a in pg.get("/Annots", []) or []:
                try:
                    if a.get("/Subtype") != "/Widget" and a.get("/T") is not None:
                        vals.append(str(a.get("/T")))
                except Exception:
                    continue
    except Exception:
        pass
    return vals


def field_identities(values) -> list[str]:
    """Distinct identity components (original spelling, first seen) of a list of raw field values."""
    out, seen = [], set()
    for v in values:
        for c in components(v):
            if c.lower() not in seen:
                seen.add(c.lower())
                out.append(c)
    return out
