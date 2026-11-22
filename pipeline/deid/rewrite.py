"""Pass 2: rewrite one blob (file or container member) with equal-length pseudonym replacement.
process_blob() returns the new bytes, or None when nothing changed (the caller then clones the original)."""
from __future__ import annotations
import gzip, io, os, re, shutil, struct, tarfile, tempfile, zipfile, zlib
from typing import Optional

MAX_DEPTH = 5
BIG = 700 << 20


class Ctx:
    """Per-process context: matchers + name rewriting + a place to record notes."""
    def __init__(self, matcher, path_matcher, notes: list, reg=None):
        self.m = matcher
        self.pm = path_matcher
        self.notes = notes
        self.reg = reg                  # registry for per-file identity FIELD values (None: content matcher only)
        self.trace: dict[str, int] = {}
        self.pdfm = None                # identities that only PDF text revealed (scope "pdf"): applied inside PDFs only

    def t(self, label: str, n: int = 1):
        if n:
            self.trace[label] = self.trace.get(label, 0) + n

    def name(self, s: str) -> str:
        """Rewrite a path / member name (every component)."""
        out, _ = self.pm.replace_str(s)
        return out


def sniff(name: str, data: bytes) -> str:
    h = data[:8]
    if h[:4] == b"PK\x03\x04" or h[:4] == b"PK\x05\x06":
        return "zip"
    if h[:5] == b"%PDF-":
        return "pdf"
    if h[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"
    if h[:2] == b"\x1f\x8b":
        return "gzip"
    if len(data) > 512 and data[257:262] == b"ustar":
        return "tar"
    return "raw"


def process_blob(ctx: Ctx, name: str, data: bytes, depth: int = 0) -> Optional[bytes]:
    kind = sniff(name, data)
    try:
        if depth < MAX_DEPTH:
            if kind == "zip":
                return do_zip(ctx, name, data, depth)
            if kind == "pdf":
                return do_pdf(ctx, name, data, depth)
            if kind == "ole":
                return do_ole(ctx, name, data)
            if kind == "gzip":
                return do_gzip(ctx, name, data, depth)
            if kind == "tar":
                return do_tar(ctx, name, data, depth)
    except Exception as e:  # fall back to raw replacement, keep going
        ctx.notes.append(f"{kind}-handler-failed:{type(e).__name__}:{name.rsplit('/',1)[-1][-40:]}")
    new, n = ctx.m.replace_bytes(data)
    ctx.t("raw-bytes", n)
    return new if n else None


# ---------------------------------------------------------------------------------------------------- zip
def do_zip(ctx: Ctx, name: str, data: bytes, depth: int):
    zin = zipfile.ZipFile(io.BytesIO(data))
    changed = False
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            nn = ctx.name(info.filename)
            if info.is_dir():
                payload = b""
                new = None
            else:
                if info.file_size > BIG:
                    ctx.notes.append("zip-member-too-big-copied")
                    payload = zin.read(info)
                    new = None
                else:
                    payload = zin.read(info)
                    new = process_blob(ctx, info.filename, payload, depth + 1)
            if nn != info.filename:
                ctx.t("zip-member-name")
            if new is not None:
                ctx.t("zip-member-content")
            if nn != info.filename or new is not None:
                changed = True
            zi = zipfile.ZipInfo(nn, date_time=info.date_time)
            zi.compress_type = info.compress_type if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) else zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zi.create_system = info.create_system
            zi.comment = ctx.m.replace_bytes(info.comment)[0] if info.comment else b""
            if zi.comment != info.comment:
                changed = True
            zout.writestr(zi, new if new is not None else payload)
        if zin.comment:
            c, n = ctx.m.replace_bytes(zin.comment)
            zout.comment = c
            changed = changed or n > 0
    return buf.getvalue() if changed else None


# ---------------------------------------------------------------------------------------------------- gzip / tar
def do_gzip(ctx: Ctx, name: str, data: bytes, depth: int):
    raw = gzip.decompress(data)
    inner_name = name[:-3] if name.lower().endswith(".gz") else name
    new = process_blob(ctx, inner_name, raw, depth + 1)
    hdr_name_changed = False
    # header FNAME
    flg = data[3]
    if flg & 8:
        i = 10
        if flg & 4:
            i += 2 + struct.unpack("<H", data[10:12])[0]
        j = data.index(b"\x00", i)
        fn = data[i:j]
        fn2, n = ctx.m.replace_bytes(fn)
        hdr_name_changed = n > 0
    if new is None and not hdr_name_changed:
        return None
    payload = new if new is not None else raw
    mtime = struct.unpack("<I", data[4:8])[0]
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=mtime) as g:
        g.write(payload)
    return out.getvalue()


def do_tar(ctx: Ctx, name: str, data: bytes, depth: int):
    tin = tarfile.open(fileobj=io.BytesIO(data))
    out = io.BytesIO()
    changed = False
    with tarfile.open(fileobj=out, mode="w", format=tin.format) as tout:
        for ti in tin.getmembers():
            nn = ctx.name(ti.name)
            payload = None
            new = None
            if ti.isfile():
                payload = tin.extractfile(ti).read()
                new = process_blob(ctx, ti.name, payload, depth + 1)
            uname, _ = ctx.m.replace_str(ti.uname or "")
            gname, _ = ctx.m.replace_str(ti.gname or "")
            lname = ctx.name(ti.linkname) if ti.linkname else ti.linkname
            if nn != ti.name or new is not None or uname != ti.uname or gname != ti.gname or lname != ti.linkname:
                changed = True
            ti2 = tarfile.TarInfo(nn)
            for a in ("mode", "mtime", "type", "uid", "gid"):
                setattr(ti2, a, getattr(ti, a))
            ti2.uname, ti2.gname, ti2.linkname = uname, gname, lname
            body = new if new is not None else payload
            ti2.size = len(body) if body is not None else 0
            tout.addfile(ti2, io.BytesIO(body) if body is not None else None)
    return out.getvalue() if changed else None


# ---------------------------------------------------------------------------------------------------- OLE
def do_ole(ctx: Ctx, name: str, data: bytes):
    import olefile
    from . import fields, perfile
    from .matcher import Chain
    from . import olez
    # Streams can be split over sectors, so always go stream by stream.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ole")
    saved_m = ctx.m
    file_m = None            # per-file matcher (field values) for the container-level passes
    try:
        tmp.write(data); tmp.close()
        ole = olefile.OleFileIO(tmp.name, write_mode=True)
        changed = 0
        try:
            # identity fields (author, last saved by, manager, company ...) of every property set, whatever their length or wording
            fids = None
            by_stream: dict = {}
            if ctx.reg is not None:
                try:
                    slots = fields.ole_field_slots(ole)
                    fids = perfile.FileIds(ctx.reg, [x[4] for x in slots])
                except Exception as e:
                    slots, fids = [], None
                    ctx.notes.append(f"ole-fields-failed:{type(e).__name__}")
                if fids:
                    for sp, off, nb, kind, txt in slots:
                        by_stream.setdefault(tuple(sp), []).append((off, nb, kind, txt))
                    m3 = olez.short_matcher(fids.map)
                    file_m = fids.m_all if m3 is None else (m3 if fids.m_all is None else Chain(m3, fids.m_all))
                    if file_m is not None:
                        ctx.m = Chain(file_m, saved_m)
            # every stream, read once and written once (olefile serves stale mini-stream data after a write):
            # field values first, then registry identities + the specific field values of this file
            for sp in ole.listdir(streams=True, storages=False):
                try:
                    st = ole.openstream(sp).read()
                except Exception:
                    continue
                if not st:
                    continue
                buf = bytearray(st)
                for off, nb, kind, txt in by_stream.get(tuple(sp), ()):
                    new, n = fids.apply_text(txt)
                    if n:
                        buf[off:off + nb] = fids.fit(new, nb, kind == "w")
                        ctx.t("ole-field", n)
                spans = []
                if sp[-1][:1] != "\x05":
                    # zlib blocks: inflate, replace, deflate again into exactly the same span (olez.py)
                    try:
                        zb, zst, spans = olez.rewrite_blocks(bytes(buf), ctx.m)
                    except Exception:
                        zb, zst, spans = bytes(buf), {}, []
                        ctx.t("ole-zblock-exception")
                    if len(zb) == len(buf):
                        buf = bytearray(zb)
                    for k, lab in (("rewritten", "ole-zblock-rewritten"), ("nofit", "ole-zblock-nofit"), ("failed", "ole-zblock-failed"),
                                   ("padded", "ole-zblock-padded")):
                        ctx.t(lab, zst.get(k, 0))
                if spans:
                    nst, n = olez.apply_patches_outside(ctx.m, bytes(buf), spans)     # never patch inside compressed bytes
                else:
                    nst, n = ctx.m.replace_bytes(bytes(buf))
                if fids and sp[-1].startswith("ISolidWorksInformation"):
                    nst, n3 = olez.ascii_tail_pass(fids.map, nst)
                    n += n3
                ctx.t("ole-stream:" + sp[-1][:28], n)
                if nst != st and len(nst) == len(st):
                    ole.write_stream(sp, nst)
                    changed += 1
        finally:
            ole.close()
        with open(tmp.name, "rb") as f:
            out = f.read()
    finally:
        ctx.m = saved_m
        os.unlink(tmp.name)
    # whatever is left in the container outside streams (directory entry names, slack, mini-stream gaps)
    out2, n2 = (ctx.m if ctx.m is saved_m else saved_m).replace_bytes(out)
    if n2:
        out = out2
        changed += n2
        ctx.t("ole-outside-streams", n2)
    if file_m is not None:       # the per-file field values in free sectors / slack / directory bytes (never inside stream data)
        try:
            out3, n3 = olez.patch_unowned(file_m, out)
        except Exception:
            out3, n3 = out, 0
        if n3 and len(out3) == len(out):
            out = out3
            changed += n3
            ctx.t("ole-outside-streams-file", n3)
    return out if changed else None


# ---------------------------------------------------------------------------------------------------- PDF
_LIT = re.compile(rb"\(((?:\\.|[^\\()])*)\)", re.S)


def _stream_may_hit(ctx: Ctx, raw: bytes) -> bool:
    """Cheap prefilter: all string literals of the content stream joined (TJ pieces concatenate), searched for identities."""
    if b"Tj" not in raw and b"TJ" not in raw and b"'" not in raw:
        return False
    joined = b"".join(_LIT.findall(raw)).decode("latin-1")
    return bool(joined) and ctx.m.replace_str(joined)[1] > 0


def _page_bytes(page) -> bytes:
    c = page.get("/Contents")
    if c is None:
        return b""
    try:
        if isinstance(c, __import__("pikepdf").Array):
            return b"\n".join(x.read_bytes() for x in c)
        return c.read_bytes()
    except Exception:
        return b""


def _fix_text_ops(ctx: Ctx, ops):
    import pikepdf
    changed = 0
    for operands, op in ops:
        o = str(op)
        if o == "Tj" and operands and isinstance(operands[0], pikepdf.String):
            s = bytes(operands[0]).decode("latin-1")
            ns, n = ctx.m.replace_str(s)
            if n:
                operands[0] = pikepdf.String(ns.encode("latin-1")); changed += n
        elif o == "TJ" and operands:
            arr = operands[0]
            idx = [i for i, e in enumerate(arr) if isinstance(e, pikepdf.String)]
            if not idx:
                continue
            parts = [bytes(arr[i]).decode("latin-1") for i in idx]
            joined = "".join(parts)
            nj, n = ctx.m.replace_str(joined)
            if n and len(nj) == len(joined):
                pos = 0
                for i, p in zip(idx, parts):
                    arr[i] = pikepdf.String(nj[pos:pos + len(p)].encode("latin-1")); pos += len(p)
                changed += n
        elif o in ("'", '"') and operands and isinstance(operands[-1], pikepdf.String):
            s = bytes(operands[-1]).decode("latin-1")
            ns, n = ctx.m.replace_str(s)
            if n:
                operands[-1] = pikepdf.String(ns.encode("latin-1")); changed += n
    return changed


def _walk_strings(ctx: Ctx, obj, depth=0) -> int:
    import pikepdf
    n = 0
    if depth > 12:
        return 0
    if isinstance(obj, pikepdf.Dictionary) or (isinstance(obj, pikepdf.Stream)):
        keys = list(obj.keys())
        for k in keys:
            try:
                v = obj[k]
            except Exception:
                continue
            if isinstance(v, pikepdf.String):
                s = str(v)
                ns, c = ctx.m.replace_str(s)
                if c:
                    obj[k] = pikepdf.String(ns); n += c
            elif isinstance(v, (pikepdf.Dictionary, pikepdf.Array)) and not v.is_indirect:
                n += _walk_strings(ctx, v, depth + 1)
            elif isinstance(v, pikepdf.Name) and k in ("/Title", "/Author"):
                pass
    elif isinstance(obj, pikepdf.Array):
        for i in range(len(obj)):
            v = obj[i]
            if isinstance(v, pikepdf.String):
                ns, c = ctx.m.replace_str(str(v))
                if c:
                    obj[i] = pikepdf.String(ns); n += c
            elif isinstance(v, (pikepdf.Dictionary, pikepdf.Array)) and not v.is_indirect:
                n += _walk_strings(ctx, v, depth + 1)
    return n


def do_pdf(ctx: Ctx, name: str, data: bytes, depth: int):
    """Wrapper: identity FIELD values of this PDF (author, owner, annotation authors ...) first, then the content passes."""
    import pikepdf
    from . import fields, perfile
    from .matcher import Chain
    fids = None
    if ctx.reg is not None:
        try:
            with pikepdf.open(io.BytesIO(data)) as p0:
                fids = perfile.FileIds(ctx.reg, fields.pdf_field_values(p0))
            txt = _pdf_text(data)
            if txt:
                fids.add_content(perfile.text_identities(ctx.reg, txt))
        except Exception as e:
            ctx.notes.append(f"pdf-ids-failed:{type(e).__name__}")
            fids = None
    saved = ctx.m
    try:
        base = Chain(ctx.pdfm, saved) if ctx.pdfm is not None else saved
        ctx.m = base
        if fids and fids.m is not None:
            ctx.m = Chain(fids.m, base)
        return _do_pdf(ctx, name, data, depth, fids)
    finally:
        ctx.m = saved


def _pdf_text(data: bytes, max_pages: int = 80) -> str:
    """Visible text, link targets and annotation texts of the first pages (for finding e-mail addresses, domains, names)."""
    try:
        import pymupdf as fitz
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    parts = []
    try:
        for i, pg in enumerate(doc):
            if i >= max_pages:
                break
            parts.append(pg.get_text())
            for lk in pg.get_links():
                if lk.get("uri"):
                    parts.append(lk["uri"])
            for an in pg.annots() or []:
                c = (an.info or {}).get("content")
                if c:
                    parts.append(c)
    except Exception:
        pass
    finally:
        doc.close()
    return "\n".join(parts)


def _fix_fields(ctx: Ctx, pdf, fids) -> int:
    """Field-level replacement (any length / wording): Info author-style keys, XMP creator-style elements, annotation authors."""
    import pikepdf
    from . import fields
    n = 0
    for k in fields.INFO_KEYS:
        try:
            v = pdf.docinfo.get(k)
            if v is not None:
                nv, c = fids.apply_text(str(v))
                if c:
                    pdf.docinfo[k] = pikepdf.String(nv); n += c
        except Exception:
            continue
    try:
        md = pdf.Root.get("/Metadata")
        if md is not None:
            x = md.read_bytes().decode("utf-8", "surrogateescape")
            cnt = [0]
            def piece(t):
                nt, c = fids.apply_text(t.group(1))
                cnt[0] += c
                return ">" + nt + "<"

            def elem(m):
                inner = fields._TXT.sub(piece, ">" + m.group(2) + "<")[1:-1]
                return m.group(0)[: m.start(2) - m.start(0)] + inner + m.group(0)[m.end(2) - m.start(0):]
            x2 = fields._XMP_RE.sub(elem, x)
            if cnt[0]:
                md.write(x2.encode("utf-8", "surrogateescape")); n += cnt[0]
                ctx.t("pdf-xmp-field", cnt[0])
    except Exception:
        pass
    try:
        for pg in pdf.pages:
            for a in pg.get("/Annots", []) or []:
                try:
                    if a.get("/Subtype") != "/Widget" and a.get("/T") is not None:
                        nv, c = fids.apply_text(str(a.get("/T")))
                        if c:
                            a["/T"] = pikepdf.String(nv); n += c
                except Exception:
                    continue
    except Exception:
        pass
    ctx.t("pdf-field", n)
    return n


def _do_pdf(ctx: Ctx, name: str, data: bytes, depth: int, fids=None):
    import pikepdf
    pdf = pikepdf.open(io.BytesIO(data))
    changed = 0
    try:
        if fids:
            changed += _fix_fields(ctx, pdf, fids)
        # 1. info dictionary + every dictionary string (outlines, annotations, form fields, names)
        for obj in pdf.objects:
            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
                c = _walk_strings(ctx, obj)
                ctx.t("pdf-dict-strings", c)
                changed += c
        # info dict is the trailer's /Info
        try:
            changed += _walk_strings(ctx, pdf.docinfo)
        except Exception:
            pass
        # 2. XMP, embedded files, page / form content streams
        for obj in pdf.objects:
            if not isinstance(obj, pikepdf.Stream):
                continue
            t = obj.get("/Type")
            st = obj.get("/Subtype")
            try:
                if t == "/Metadata":
                    raw = obj.read_bytes()
                    nb, n = ctx.m.replace_bytes(raw)
                    if n:
                        obj.write(nb); changed += n
                        ctx.t("pdf-xmp", n)
                elif t == "/EmbeddedFile":
                    raw = obj.read_bytes()
                    nb = process_blob(ctx, "attachment", raw, depth + 1)
                    if nb is not None:
                        obj.write(nb); changed += 1
                        ctx.t("pdf-attachment-content")
                elif st == "/Form" and _stream_may_hit(ctx, obj.read_bytes()):
                    ops = pikepdf.parse_content_stream(obj)
                    c = _fix_text_ops(ctx, ops)
                    if c:
                        obj.write(pikepdf.unparse_content_stream(ops)); changed += c
                        ctx.t("pdf-content-text", c)
            except Exception:
                continue
        # attachments listed in the name tree (names + descriptions)
        try:
            for fname, spec in list(pdf.attachments.items()):
                nn = ctx.name(fname)
                if nn != fname:
                    att = pdf.attachments[fname]
                    pdf.attachments[nn] = att
                    del pdf.attachments[fname]
                    changed += 1
        except Exception:
            pass
        # page content streams (pages whose /Contents is array / single stream not caught above)
        for page in pdf.pages:
            try:
                if not _stream_may_hit(ctx, _page_bytes(page)):
                    continue
                ops = pikepdf.parse_content_stream(page)
                c = _fix_text_ops(ctx, ops)
                if c:
                    page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(ops)); changed += c
                    ctx.t("pdf-content-text", c)
            except Exception:
                continue
        out = io.BytesIO()
        if changed:
            pdf.save(out, deterministic_id=True)
    finally:
        pdf.close()
    result = out.getvalue() if changed else None
    # 3. visible text that is still present (subset fonts, glyph-split text): overlay replacement text
    result = _pdf_visible_fixup(ctx, result if result is not None else data, name, orig_changed=result is not None)
    return result


def _pdf_visible_fixup(ctx: Ctx, data: bytes, name: str, orig_changed: bool):
    try:
        import pymupdf as fitz
    except Exception:
        return data if orig_changed else None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return data if orig_changed else None
    fixed = 0
    try:
        for pno, page in enumerate(doc):
            if pno >= 80:           # bound the cost on very long documents (listed as a limitation)
                ctx.notes.append("pdf-visible-scan-capped")
                break
            txt = page.get_text()
            hits = ctx.m.find_str(txt) + [(k, ctx.m.str_map[k]) for k in ctx.m._nonascii_keys if k in txt]   # non-ASCII originals (accented names) are not in the byte automaton
            if not hits:
                continue
            seen = set()
            for orig, rep in hits:
                if orig in seen:
                    continue
                seen.add(orig)
                for r in page.search_for(orig):
                    size = max(4.0, min(14.0, r.height * 0.8))
                    page.add_redact_annot(r, text=rep, fontname="helv", fontsize=size, fill=False)
                    fixed += 1
            if fixed:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        if not fixed:
            return data if orig_changed else None
        ctx.notes.append("pdf-visible-overlay")
        ctx.t("pdf-visible-overlay", fixed)
        out = doc.tobytes(garbage=0, deflate=True)
        try:
            import pikepdf
            with pikepdf.open(io.BytesIO(data)) as pa, pikepdf.open(io.BytesIO(out)) as pb:
                ok = len(pa.pages) == len(pb.pages)
        except Exception:
            ok = False
        if not ok:      # never trade pages for a pseudonym: keep the version without overlay
            ctx.notes.append("pdf-overlay-dropped-pages")
            return data if orig_changed else None
        return out
    except Exception as e:
        ctx.notes.append(f"pdf-overlay-failed:{type(e).__name__}")
        return data if orig_changed else None
    finally:
        doc.close()
