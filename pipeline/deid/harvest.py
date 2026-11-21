"""Pass 1: find identity candidates (kind, value) inside one blob. Pure functions, no registry access."""
from __future__ import annotations
import io, re, struct, zipfile
from . import detect

HEAD = 1 << 20          # bytes of head scanned for big text files
TAIL = 1 << 16
FULL_LIMIT = 24 << 20   # files up to this size are scanned entirely


def _text(data: bytes) -> str:
    return data.decode("latin-1")


def _window(data: bytes) -> bytes:
    return data if len(data) <= FULL_LIMIT else data[:HEAD] + b"\n" + data[-TAIL:]


def parse_step_args(s: str):
    """Parse '(a,(b,c),'x')' into nested python lists of str (quotes removed, '' unescaped)."""
    i, n = 0, len(s)
    def val():
        nonlocal i
        while i < n and s[i] in " \t\r\n":
            i += 1
        if i >= n:
            return None
        if s[i] == "(":
            i += 1
            out = []
            while i < n:
                while i < n and s[i] in " \t\r\n,":
                    i += 1
                if i < n and s[i] == ")":
                    i += 1
                    return out
                v = val()
                if v is None:
                    break
                out.append(v)
            return out
        if s[i] == "'":
            i += 1
            buf = []
            while i < n:
                if s[i] == "'":
                    if i + 1 < n and s[i + 1] == "'":
                        buf.append("'"); i += 2; continue
                    i += 1
                    break
                buf.append(s[i]); i += 1
            return "".join(buf)
        j = i
        while i < n and s[i] not in ",)":
            i += 1
        return s[j:i].strip()
    return val()


def _flat(x):
    if isinstance(x, list):
        for y in x:
            yield from _flat(y)
    elif isinstance(x, str):
        yield x


def generic_text_candidates(txt: str, out: list):
    if "@" in txt:
        for l, d in detect.find_emails(txt):
            out.append(("email", f"{l}@{d}"))
    if "://" in txt or "www." in txt:
        for m in re.finditer(r"(?i)\b(?:https?|ftp)://([A-Za-z0-9.-]+\.[A-Za-z]{2,24})", txt):
            out.append(("domain", m.group(1)))
        for m in re.finditer(r"(?i)\bwww\.([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})\b", txt):
            out.append(("domain", m.group(1)))
    if "/home/" in txt or "/Users/" in txt or ":\\" in txt or ":/" in txt:
        for u in detect.find_user_paths(txt):
            out.append(("userpath", u))
    if "opyright" in txt or "(c)" in txt or "(C)" in txt or "©" in txt or "\xa9" in txt:
        for h in detect.find_copyright_holders(txt):
            out.append(("company" if re.search(detect_company_words, h) else "person", h))
    if re.search(r"(?i)tel|phone|fax|mobile", txt):
        for p in detect.find_phones(txt):
            out.append(("phone", p))


detect_company_words = r"(?i)\b(inc|ltd|llc|gmbh|corp|co|company|university|institute|labs?|technologies|systems|industries|engineering|robotics|group|foundation)\b"


def step_candidates(txt: str, out: list):
    head = txt[:200000]
    m = re.search(r"FILE_NAME\s*\(", head)
    if m:
        end = head.find(");", m.end())
        body = head[m.end() - 1: end + 1 if end > 0 else m.end() + 2000]
        args = parse_step_args(body)
        if isinstance(args, list) and len(args) >= 7:
            name, _ts, authors, orgs = args[0], args[1], args[2], args[3]
            for a in _flat(authors):
                out.append(("person", a))
            for o in _flat(orgs):
                out.append(("org", o))
            if isinstance(name, str):
                for u in detect.find_user_paths(name):
                    out.append(("userpath", u))
            auth = args[6] if len(args) > 6 else ""
            if isinstance(auth, str) and auth and not detect.is_generic_person(auth):
                out.append(("person", auth))
    m = re.search(r"FILE_DESCRIPTION\s*\(", head)
    if m:
        end = head.find(");", m.end())
        args = parse_step_args(head[m.end() - 1: end + 1 if end > 0 else m.end() + 2000])
        if isinstance(args, list) and args:
            for s in _flat(args[0]):
                generic_text_candidates(s, out)


def iges_candidates(txt: str, out: list):
    lines = txt.split("\n")[:400]
    g = "".join(l[:72] for l in lines if len(l) >= 73 and l[72] == "G")
    if g:
        try:
            pd, rd = ",", ";"
            i = 0
            if g.startswith(","):
                i = 1
            elif g.startswith("1H"):
                pd = g[2]; i = 4
            fields = []
            while i < len(g) and len(fields) < 26:
                m = re.match(r"(\d+)H", g[i:])
                if m:
                    ln = int(m.group(1)); s = g[i + len(m.group(0)): i + len(m.group(0)) + ln]
                    fields.append(s); i += len(m.group(0)) + ln
                    i = g.find(pd, i) + 1 if g.find(pd, i) >= 0 else len(g)
                else:
                    j = i
                    while j < len(g) and g[j] not in (pd, ";"):
                        j += 1
                    fields.append(g[i:j]); i = j + 1
            for idx in (20, 21):
                if idx < len(fields):
                    out.append(("person" if idx == 20 else "org", fields[idx]))
            if len(fields) > 3:
                for u in detect.find_user_paths(fields[3]):
                    out.append(("userpath", u))
        except Exception:
            pass
    s_sec = "".join(l[:72] + "\n" for l in lines if len(l) >= 73 and l[72] == "S")
    generic_text_candidates(s_sec, out)


def svg_candidates(txt: str, out: list):
    head = txt[:300000]
    for m in re.finditer(r"<dc:creator>.*?</dc:creator>|<dc:publisher>.*?</dc:publisher>|<dc:contributor>.*?</dc:contributor>|<cc:Agent>.*?</cc:Agent>", head, re.S):
        for t in re.findall(r"<dc:title>([^<]{2,80})</dc:title>", m.group(0)):
            out.append(("person", t.strip()))
        if not re.search(r"<dc:title>", m.group(0)):
            for t in re.findall(r">([^<>]{3,80})<", m.group(0)):
                out.append(("person", t.strip()))
    for m in re.finditer(r"(?:sodipodi:docname|inkscape:export-filename)=\"([^\"]+)\"", head):
        for u in detect.find_user_paths(m.group(1)):
            out.append(("userpath", u))


def freecad_candidates(txt: str, out: list):
    for m in re.finditer(r'<Property name="(CreatedBy|LastModifiedBy|Company|Contact)"[^>]*>\s*<String value="([^"]*)"', txt[:300000]):
        v = m.group(2)
        if v:
            out.append(("company" if m.group(1) == "Company" else "person", v))


def threemf_candidates(txt: str, out: list):
    for m in re.finditer(r'<metadata name="(Designer|DesignerUserId|Copyright|Author|Creator|Organization)"[^>]*>([^<]*)<', txt[:300000], re.I):
        v = m.group(2).strip()
        if v:
            k = m.group(1).lower()
            if k == "copyright":
                generic_text_candidates("Copyright " + v, out)
            else:
                out.append(("person", v))


def dxf_candidates(txt: str, out: list):
    head = txt[:200000]
    for m in re.finditer(r"\$(LASTSAVEDBY|PROJECTNAME|TITLE|AUTHOR)\r?\n\s*\d+\r?\n([^\r\n]+)", head):
        v = m.group(2).strip()
        if m.group(1) in ("LASTSAVEDBY", "AUTHOR") and not detect.is_generic_person(v):
            out.append(("person", v))


def raw_candidates(name: str, data: bytes, out: list):
    low = name.lower()
    w = _window(data)
    txt = _text(w)
    ext = low.rsplit(".", 1)[-1] if "." in low else ""
    if ext in ("step", "stp", "p21", "stpz"):
        step_candidates(txt, out)
    elif ext in ("iges", "igs"):
        iges_candidates(txt, out)
    elif ext == "svg":
        svg_candidates(txt, out)
    elif ext == "dxf":
        dxf_candidates(txt, out)
    elif ext == "xml" and "Document.xml" in name:
        freecad_candidates(txt, out)
    elif ext == "model" or name.endswith("3D/3dmodel.model"):
        threemf_candidates(txt, out)
    generic_text_candidates(txt, out)
    # UTF-16LE strings (OLE / Windows metadata)
    if b"@\x00" in w or b"C\x00o\x00p\x00y\x00" in w or b"\\\x00U\x00s\x00e\x00r\x00s" in w:
        t16 = w.decode("utf-16le", "ignore")
        generic_text_candidates(t16, out)
        t16b = w[1:].decode("utf-16le", "ignore")
        generic_text_candidates(t16b, out)


def ole_candidates(path_or_bytes, out: list):
    import olefile
    try:
        ole = olefile.OleFileIO(path_or_bytes)
    except Exception:
        return False
    try:
        try:
            md = ole.get_metadata()
        except Exception:
            md = None
        if md is not None:
            def dec(v):
                if v is None:
                    return None
                if isinstance(v, bytes):
                    for enc in ("utf-8", "cp1252", "latin-1"):
                        try:
                            return v.decode(enc)
                        except Exception:
                            pass
                return str(v)
            for attr, kind in (("author", "person"), ("last_saved_by", "person"), ("company", "org"), ("manager", "person")):
                v = dec(getattr(md, attr, None))
                if v:
                    out.append((kind, v.strip("\x00")))
            for attr in ("title", "subject", "comments", "keywords", "category", "revision_number"):
                v = dec(getattr(md, attr, None))
                if v:
                    generic_text_candidates(v, out)
        for sp in ole.listdir(streams=True, storages=False):
            nm = "/".join(sp)
            if re.search(r"(?i)summary|properties|SwDocMgr|xml|Config", nm):
                try:
                    d = ole.openstream(sp).read(2_000_000)
                except Exception:
                    continue
                generic_text_candidates(d.decode("latin-1"), out)
                if b"\x00" in d[:200]:
                    generic_text_candidates(d.decode("utf-16le", "ignore"), out)
    finally:
        ole.close()
    return True


def pdf_candidates(data: bytes, out: list):
    import pikepdf
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except Exception:
        return False
    try:
        info = pdf.docinfo
        for k, v in list(info.items()):
            try:
                s = str(v)
            except Exception:
                continue
            kn = str(k)
            if kn in ("/Author", "/Manager"):
                out.append(("person", s))
            elif kn in ("/Company", "/Organization", "/Organisation"):
                out.append(("org", s))
            elif kn in ("/Title", "/Subject", "/Keywords", "/Creator", "/Producer"):
                generic_text_candidates(s, out)
            else:
                if kn not in ("/CreationDate", "/ModDate", "/Trapped"):
                    generic_text_candidates(s, out)
        try:
            with pdf.open_metadata() as m:
                for key in ("dc:creator", "pdf:Author", "xmpRights:Owner", "dc:publisher", "dc:contributor"):
                    try:
                        v = m.get(key)
                    except Exception:
                        v = None
                    if v:
                        for s in (v if isinstance(v, (list, set, tuple)) else [v]):
                            out.append(("person", str(s)))
                for key in ("dc:rights", "xmpRights:UsageTerms", "pdfx:Company", "pdfx:SourceModified"):
                    try:
                        v = m.get(key)
                    except Exception:
                        v = None
                    if v:
                        generic_text_candidates(str(v), out)
        except Exception:
            pass
        for name, att in list(pdf.attachments.items()):
            out.append(("__attachment__", name))
        for page in pdf.pages[:6]:
            try:
                for a in page.get("/Annots", []) or []:
                    u = a.get("/A", {}).get("/URI") if hasattr(a, "get") else None
                    if u is not None:
                        generic_text_candidates(str(u), out)
                    c = a.get("/Contents") if hasattr(a, "get") else None
                    if c is not None:
                        generic_text_candidates(str(c), out)
            except Exception:
                pass
    finally:
        pdf.close()
    # visible text of the first pages
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        txt = []
        for i, pg in enumerate(doc):
            if i >= 8:
                break
            txt.append(pg.get_text())
        doc.close()
        generic_text_candidates("\n".join(txt), out)
    except Exception:
        pass
    return True
