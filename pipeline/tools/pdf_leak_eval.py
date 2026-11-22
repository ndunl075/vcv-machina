#!/usr/bin/env python3
"""Leak evaluator for the PDF path: harvest + apply on a fixed-seed sample, then re-open every OUTPUT and count.

  python pipeline/tools/pdf_leak_eval.py --work DIR --out DIR [--sample FILE | --make-sample FILE] [--mode before|after] [--procs 4]

  --work   directory that holds registry.sqlite + seed.bin (a COPY: new identities are added to it)
  --out    directory the sample outputs are written to
  --mode   'before' runs the harvest without the title-block discovery (DEID_PDFTEXT=0), 'after' with it
Prints counts only (never file names or identifiers): PDFs with a discovered identity, PDFs where every discovered original is gone from
output text + Info + XMP, PDFs whose output text contains a pseudonym, page / vector-drawing changes, handler failures.
"""
import argparse, json, multiprocessing as mp, os, random, re, shutil, sqlite3, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

_E = None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def surfaces(path: str, pages: int = 8):
    """(text, vector drawing count, page count) of a PDF: visible text of the first pages + Info + XMP."""
    import pymupdf
    doc = pymupdf.open(path)
    try:
        n = len(doc)
        parts = [pg.get_text() for i, pg in enumerate(doc) if i < pages]
        for v in (doc.metadata or {}).values():
            if v:
                parts.append(str(v))
        try:
            parts.append(doc.get_xml_metadata() or "")
        except Exception:
            pass
        nd = 0
        for i, pg in enumerate(doc):
            if i >= 20:
                break
            try:
                nd += len(pg.get_cdrawings())
            except Exception:
                pass
        return _norm(" ".join(parts)), nd, n
    finally:
        doc.close()


def _harvest(rel):
    from deid import core, harvest
    out = []
    try:
        data = open(os.path.join(core.INPUT, rel), "rb").read()
        harvest.pdf_candidates(data, out)
    except Exception:
        pass
    return rel, [c for c in out if c[0] != "__attachment__"]


def _init():
    global _E
    os.nice(10)
    from deid import core
    _E = core.Engine()


def _one(args):
    rel, discovered, pseudo = args
    from deid import core
    t = time.time()
    res = {"rel": rel}
    try:
        orel, handler, status, nrep, note, trace = core.apply_one(_E, rel)
        res.update(handler=handler, status=status, note=note)
        src, dst = os.path.join(core.INPUT, rel), os.path.join(core.OUT, orel)
        tin, din, pin = surfaces(src)
        tout, dout, pout = surfaces(dst)
        present = [o for o in discovered if _norm(o) in tin]
        res["n_present"] = len(present)
        res["leaked"] = [o for o in present if _norm(o) in tout]
        res["pseudo_seen"] = any(_norm(pseudo[o]) in tout for o in present if o in pseudo and _norm(pseudo[o]) != _norm(o))
        res["pages_changed"] = pin != pout
        res["draw_changed"] = din != dout
        res["fail"] = status != "ok" or "failed" in note or "error" in note
    except Exception as e:
        res.update(fail=True, note=f"{type(e).__name__}", n_present=0, leaked=[], pseudo_seen=False, pages_changed=False, draw_changed=False)
    res["secs"] = time.time() - t
    return res


def make_sample(ledger: str, dest: str, per_source: int = 60, seed: int = 20261122):
    import collections
    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    by = collections.defaultdict(list)
    for r, s in con.execute("select rel,size from files where lower(rel) like '%.pdf' and handler='pdf'"):
        if s < (25 << 20):
            by[r.split("/")[1]].append(r)
    rnd = random.Random(seed)
    out = []
    for k in sorted(by):
        v = sorted(by[k]); rnd.shuffle(v); out += v[:per_source]
    open(dest, "w").write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample")
    ap.add_argument("--make-sample")
    ap.add_argument("--ledger", default="/Volumes/vcvmachina/work/ledger.sqlite")
    ap.add_argument("--input", default="/Volumes/vcvmachina/input")
    ap.add_argument("--mode", choices=["before", "after"], default="after")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.make_sample:
        make_sample(a.ledger, a.make_sample); return
    procs = min(a.procs, 4)
    os.environ.update(DEID_WORK=os.path.abspath(a.work), DEID_OUT=os.path.abspath(a.out), DEID_INPUT=a.input)
    os.environ["DEID_PDFTEXT"] = "1"
    shutil.rmtree(a.out, ignore_errors=True)
    os.makedirs(a.out, exist_ok=True)
    from deid import core, ident
    from deid.registry import Registry
    rels = [l.strip() for l in open(a.sample) if l.strip()]
    # ground truth = what the (new) discovery finds, guarded exactly like the pipeline; 'before' registers it into a throw-away copy only,
    # so both modes judge the same identities while 'before' applies the unchanged registry.
    truth_dir = os.path.join(os.path.abspath(a.out) + ".truth")
    shutil.rmtree(truth_dir, ignore_errors=True)
    os.makedirs(truth_dir)
    if a.mode == "before":
        shutil.copy(core.REGDB, truth_dir); shutil.copy(core.SEEDFILE, truth_dir)
        reg = Registry(os.path.join(truth_dir, "registry.sqlite"), core.get_seed())
    else:
        reg = Registry(core.REGDB, core.get_seed())
    n0 = len(reg.map)
    t0 = time.time()
    cands = {}
    with mp.Pool(procs, initializer=os.nice, initargs=(10,)) as pool:
        for rel, c in pool.imap_unordered(_harvest, rels, chunksize=4):
            cands[rel] = c
    disc = {}
    for rel in rels:
        c = cands.get(rel, [])
        ident.register_candidates(reg, c, source=".pdf")
        vals = set()
        for kind, v in c:
            v = v.strip().strip("'\"").strip()
            if reg.get(v) and reg.scope.get(re.sub(r"\s+", " ", v)) == "all":
                vals.add(v)
        disc[rel] = sorted(vals)
    reg.commit()
    new_ids = len(reg.map) - n0
    pseudo = {o: reg.map[o][1] for v in disc.values() for o in v if o in reg.map}
    reg.con.close()
    shutil.rmtree(truth_dir, ignore_errors=True)
    with mp.Pool(procs, initializer=_init) as pool:
        results = list(pool.imap_unordered(_one, [(r, disc[r], {o: pseudo[o] for o in disc[r] if o in pseudo}) for r in rels], chunksize=2))
    with_id = [r for r in results if r["n_present"] > 0]
    summary = {
        "mode": a.mode, "sample": len(rels), "new_registry_rows": new_ids,
        "pdfs_with_discovered_identity": len(with_id),
        "pdfs_all_discovered_absent_in_output": sum(1 for r in with_id if not r["leaked"]),
        "pdfs_with_any_leak": sum(1 for r in with_id if r["leaked"]),
        "pdfs_pseudonym_in_output_text": sum(1 for r in with_id if r["pseudo_seen"]),
        "discovered_identities_total": sum(len(v) for v in disc.values()),
        "pdfs_page_count_changed": sum(1 for r in results if r["pages_changed"]),
        "pdfs_vector_drawing_count_changed": sum(1 for r in results if r["draw_changed"]),
        "handler_failures": sum(1 for r in results if r["fail"]),
        "seconds": round(time.time() - t0),
    }
    print(json.dumps(summary, indent=1))
    if a.json:
        json.dump({"summary": summary, "per_pdf": [{k: v for k, v in r.items()} for r in results]}, open(a.json, "w"))


if __name__ == "__main__":
    main()
