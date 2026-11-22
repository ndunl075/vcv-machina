#!/usr/bin/env python3.12
"""Verifier. python verify.py [--procs 6] [--sample 0.05] [--full]
(a) leak scan of every changed output file (+ a sample of unchanged ones) and every output path, ASCII/UTF-8/UTF-16LE,
    inside zip/tar/gzip/OLE members and PDF objects/streams;  (b) per-format usability against the input;
(c) registry consistency;  (d) completeness of the output tree.   Prints one table by file type and failure kind."""
import argparse, collections, hashlib, io, json, multiprocessing as mp, os, random, re, sys, time, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deid import core, rewrite
from deid.registry import Registry

_E = None


def _init():
    global _E
    os.nice(10)
    _E = core.Engine()


def ext_of(p):
    return os.path.splitext(p)[1].lower().lstrip(".") or "(none)"


def check_step(a, b):
    ra = re.compile(rb"^#\d+\s*=", re.M)
    if len(ra.findall(a)) != len(ra.findall(b)):
        return "entity-count"
    for tok in (b"ISO-10303-21;", b"HEADER;", b"ENDSEC;", b"DATA;", b"END-ISO-10303-21;"):
        if a.count(tok) != b.count(tok):
            return "structure"
    return None


def check_iges(a, b):
    la, lb = a.split(b"\n"), b.split(b"\n")
    if len(la) != len(lb):
        return "line-count"
    for x, y in zip(la, lb):
        if len(x) != len(y) or x[72:73] != y[72:73] or x[73:] != y[73:]:
            return "column-structure"
    return None


def check_stl(a, b):
    if len(a) != len(b):
        return "size"
    if a[:5].lower() == b"solid" and b"facet" in a[:1000]:
        return None if a.count(b"facet normal") == b.count(b"facet normal") else "facet-count"
    return None if a[80:84] == b[80:84] else "facet-count"


def check_obj(a, b):
    for tok in (b"\nv ", b"\nf ", b"\nvn ", b"\nvt "):
        if a.count(tok) != b.count(tok):
            return "mesh-count"
    return None


def check_zip(a, b):
    za, zb = zipfile.ZipFile(io.BytesIO(a)), zipfile.ZipFile(io.BytesIO(b))
    if zb.testzip() is not None:
        return "zip-corrupt"
    ia, ib = za.infolist(), zb.infolist()
    if len(ia) != len(ib):
        return "member-count"
    for x, y in zip(ia, ib):
        if x.file_size != y.file_size:
            # rewritten PDFs / nested containers legitimately change size; plain members must keep it
            if rewrite.sniff(x.filename, za.read(x)[:8]) == "raw":
                return "member-size"
        if y.filename.lower().endswith((".xml", ".model", ".rels")):
            try:
                from lxml import etree
                etree.fromstring(zb.read(y))
            except Exception:
                return "xml-malformed"
    return None


def check_ole(a, b):
    import olefile
    oa, ob = olefile.OleFileIO(io.BytesIO(a)), olefile.OleFileIO(io.BytesIO(b))
    la = [(tuple(p), oa.get_size(p)) for p in oa.listdir()]
    lb = [(tuple(p), ob.get_size(p)) for p in ob.listdir()]
    if [s for _, s in la] != [s for _, s in lb] or len(la) != len(lb):
        return "stream-structure"
    return None


def check_pdf(a, b):
    import pikepdf
    pa, pb = pikepdf.open(io.BytesIO(a)), pikepdf.open(io.BytesIO(b))
    if len(pa.pages) != len(pb.pages):
        return "page-count"
    try:
        if len(pa.attachments) != len(pb.attachments):
            return "attachment-count"
    except Exception:
        pass
    return None


def check_img(a, b):
    from PIL import Image
    ia, ib = Image.open(io.BytesIO(a)), Image.open(io.BytesIO(b))
    ib.load()
    return None if ia.size == ib.size else "image-size"


def check_svg(a, b):
    from lxml import etree
    etree.fromstring(b, parser=etree.XMLParser(recover=False, huge_tree=True))
    return None


def verify_one(item):
    rel, orel, handler, nrep, size, do_leak = item
    ext = ext_of(rel)
    src, dst = os.path.join(core.INPUT, rel), os.path.join(core.OUT, orel)
    fails = []
    if not os.path.isfile(dst):
        return rel, ext, ["missing-output"]
    if ext_of(orel) != ext:
        fails.append("extension-changed")
    if _E.pm.replace_str(orel)[1]:
        fails.append("leak-in-path")
    rp, op = rel.split("/"), orel.split("/")
    if len(rp) > 3 and rp[0] == "sources" and rp[1] in ("github", "gitlab") and rp[2] == op[2]:
        fails.append("root-folder-not-renamed")
    dsz = os.path.getsize(dst)
    if size == 0:
        return rel, ext, fails
    if size > rewrite.BIG:
        if dsz != size:
            fails.append("size-changed")
        if do_leak:
            if core._scan_patches(dst, dsz, _E.cm):
                fails.append("leak-in-content")
        return rel, ext, fails
    try:
        b = open(dst, "rb").read()
        if do_leak or nrep:
            ctx = rewrite.Ctx(_E.cm, _E.pm, [])
            if rewrite.process_blob(ctx, orel, b) is not None:
                fails.append("leak-in-content")
        if nrep or do_leak:
            a = open(src, "rb").read()
            kind = rewrite.sniff(rel, a[:8])
            err = None
            try:
                if ext in ("step", "stp", "p21"):
                    err = check_step(a, b)
                elif ext in ("iges", "igs"):
                    err = check_iges(a, b)
                elif ext == "stl":
                    err = check_stl(a, b)
                elif ext == "obj":
                    err = check_obj(a, b)
                elif kind == "zip":
                    err = check_zip(a, b)
                elif kind == "ole":
                    err = check_ole(a, b)
                elif kind == "pdf":
                    err = check_pdf(a, b)
                elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"):
                    err = check_img(a, b)
                elif ext == "svg":
                    err = check_svg(a, b)
                elif ext not in ("zip",) and kind in ("raw",) and len(a) != len(b):
                    err = "size-changed"
            except Exception as e:
                err = "parse-error:" + type(e).__name__
            if err:
                fails.append(err)
    except Exception as e:
        fails.append("verify-error:" + type(e).__name__)
    return rel, ext, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=2, help="worker processes (default 2; raise for the full run)")
    ap.add_argument("--sample", type=float, default=0.05, help="fraction of unchanged files also leak-scanned")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--json", default=os.path.join(core.WORK, "verify.json"))
    a = ap.parse_args()
    con = core.ledger()
    rows = con.execute("SELECT rel,out_rel,handler,status,nrep,size,note FROM files").fetchall()
    reg = Registry(core.REGDB, core.get_seed(), readonly=True)
    summary = collections.defaultdict(lambda: collections.Counter())
    # (c) registry consistency ---------------------------------------------------------------------------------------
    cons = collections.Counter()
    seen = {}
    lower_orig = {o.lower() for o in reg.map}
    for o, (k, p) in reg.map.items():
        if len(o) != len(p):
            cons["pseudonym-length-differs"] += 1
        if p.lower() in seen and seen[p.lower()] != o:
            cons["two-identities-one-pseudonym"] += 1
        seen[p.lower()] = o
        if p.lower() in lower_orig and p.lower() != o.lower():
            cons["pseudonym-equals-other-original"] += 1
        if p == o:
            cons["pseudonym-equals-original"] += 1
    # (d) completeness -----------------------------------------------------------------------------------------------
    comp = collections.Counter()
    input_files = {r for r in core.walk_inputs()}
    ledger_rels = {r[0] for r in rows}
    comp["input-without-ledger-row"] = len(input_files - ledger_rels)
    comp["ledger-status-not-ok"] = sum(1 for r in rows if r[3] != "ok")
    outs = collections.Counter(r[1] for r in rows)
    comp["output-path-collisions"] = sum(1 for v in outs.values() if v > 1)
    total_out = 0
    extra = 0
    expect = set(outs)
    for d, _dn, fn in os.walk(core.OUT):
        for f in fn:
            total_out += 1
            if os.path.relpath(os.path.join(d, f), core.OUT) not in expect:
                extra += 1
    comp["output-files"] = total_out
    comp["output-files-not-in-ledger"] = extra
    comp["over-400k-objects"] = int(total_out > 400000)
    comp["over-2GB"] = sum(1 for r in rows if r[5] > (2 << 30))
    # (a)+(b) per file ----------------------------------------------------------------------------------------------
    random.seed(1)
    items = []
    for rel, orel, handler, status, nrep, size, note in rows:
        do_leak = a.full or nrep == 0 and random.random() < a.sample
        items.append((rel, orel, handler, nrep, size, do_leak))
    t0 = time.time()
    by_ext = collections.defaultdict(collections.Counter)
    kinds = collections.Counter()
    failed_files = []
    with mp.Pool(a.procs, initializer=_init) as pool:
        for i, (rel, ext, fails) in enumerate(pool.imap_unordered(verify_one, items, chunksize=8)):
            by_ext[ext]["files"] += 1
            if fails:
                by_ext[ext]["failed"] += 1
                failed_files.append((rel, fails))
                for f in fails:
                    by_ext[ext][f] += 1
                    kinds[f] += 1
            if i and i % 5000 == 0:
                print(f"  verified {i}/{len(items)}", file=sys.stderr, flush=True)
    cloned = collections.Counter()
    notes = collections.Counter()
    for rel, orel, handler, status, nrep, size, note in rows:
        if nrep == 0:
            cloned[ext_of(rel)] += 1
        if status != "ok":
            notes[status + ":" + ext_of(rel)] += 1
        for n in (note or "").split(";"):
            if n:
                notes[re.sub(r":.*", "", n)] += 1
    # print ----------------------------------------------------------------------------------------------------------
    print(f"\nVERIFY  {len(rows)} ledger rows, {time.time() - t0:.0f}s\n")
    print("(c) registry:", dict(cons) or "OK", f"({len(reg.map)} identities)")
    print("(d) completeness:", dict(comp))
    print("\n(a)(b) by type          files  failed  leak-path leak-content  other-usability")
    for ext, c in sorted(by_ext.items(), key=lambda kv: -kv[1]["files"])[:40]:
        other = sum(v for k, v in c.items() if k not in ("files", "failed", "leak-in-path", "leak-in-content"))
        print(f"  {ext:<18}{c['files']:>7}{c['failed']:>8}{c['leak-in-path']:>10}{c['leak-in-content']:>13}{other:>16}")
    print("\nfailure kinds:", dict(kinds.most_common()))
    print("\nfiles left unchanged (no identifier found / nothing to do) by type:", dict(cloned.most_common(12)))
    print("handler notes / non-ok statuses:", dict(notes.most_common(20)))
    json.dump({"consistency": cons, "completeness": comp, "by_ext": {k: dict(v) for k, v in by_ext.items()}, "kinds": kinds,
               "failed": failed_files[:2000]}, open(a.json, "w"))


if __name__ == "__main__":
    main()
