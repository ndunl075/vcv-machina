#!/usr/bin/env python3.12
"""De-identification pipeline driver.   python run.py {seed|harvest|apply|survey|verify|all} [--limit N] [--procs 6] [--force]
Everything is resumable: per-file results live in WORK/ledger.sqlite and WORK/registry.sqlite."""
import argparse, json, multiprocessing as mp, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deid import core, harvest, ident, rewrite
from deid.pool import run_pool
from deid.registry import Registry

_eng = None


def _init():
    os.nice(10)


def _harvest_one(rel):
    path = os.path.join(core.INPUT, rel)
    out = []
    try:
        size = os.path.getsize(path)
        if size == 0:
            return rel, "empty", []
        data = open(path, "rb").read() if size <= (96 << 20) else _bigwin(path, size)
        _harvest_blob(rel, data, out, 0)
        return rel, "ok", out
    except Exception as e:
        return rel, "error:" + type(e).__name__, out


def _bigwin(path, size):
    with open(path, "rb") as f:
        h = f.read(harvest.HEAD)
        f.seek(max(0, size - harvest.TAIL))
        return h + f.read()


def _harvest_blob(name, data, out, depth):
    kind = rewrite.sniff(name, data)
    if depth < 4 and kind == "zip":
        import io, zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            for info in z.infolist():
                if info.is_dir() or info.file_size > (96 << 20):
                    continue
                low = info.filename.lower()
                # only open members that can carry identifiers; skip bulk geometry/image members
                if low.endswith((".brep", ".bin", ".png", ".jpg", ".jpeg", ".gif", ".bmp")) and not low.endswith("thumbnail.png"):
                    continue
                _harvest_blob(info.filename, z.read(info), out, depth + 1)
            return
        except Exception:
            pass
    if kind == "pdf":
        if harvest.pdf_candidates(data, out):
            return
    if kind == "ole":
        if harvest.ole_candidates(__import__("io").BytesIO(data), out):
            harvest.raw_candidates(name, data[:1 << 16], out)
            return
    if depth < 4 and kind == "gzip":
        import gzip
        try:
            _harvest_blob(name[:-3] if name.lower().endswith(".gz") else name, gzip.decompress(data), out, depth + 1)
            return
        except Exception:
            pass
    harvest.raw_candidates(name, data, out)


def cmd_harvest(a):
    con = core.ledger()
    reg = Registry(core.REGDB, core.get_seed())
    rels = list(core.walk_inputs())
    if a.limit:
        rels = rels[: a.limit]
    core.seed_paths(reg, rels)
    fixed = reg.repair()
    if fixed:
        print(f"repaired {fixed} registry entries", flush=True)
    done = {r for (r,) in con.execute("SELECT rel FROM harvest")} if not a.force else set()
    todo = [r for r in rels if r not in done]
    print(f"harvest: {len(rels)} files, {len(todo)} to do", flush=True)
    t0 = time.time(); n = 0; nb = 0
    cnt = [0]

    def on_res(res):
        rel, status, cands = res
        cands = [c for c in cands if c[0] != "__attachment__"]
        ident.register_candidates(reg, cands, source=os.path.splitext(rel)[1].lower())
        kc: dict = {}
        for c in cands:
            kc[c[0]] = kc.get(c[0], 0) + 1
        con.execute("INSERT OR REPLACE INTO harvest(rel,status,ncand,kinds) VALUES(?,?,?,?)", (rel, status, len(cands), json.dumps(kc)))
        cnt[0] += 1
        if cnt[0] % 500 == 0:
            reg.commit(); con.commit()
            print(f"  {cnt[0]}/{len(todo)}  registry={len(reg.map)}  {cnt[0] / (time.time() - t0):.1f} files/s", flush=True)

    def on_crash(rel):
        con.execute("INSERT OR REPLACE INTO harvest(rel,status,ncand) VALUES(?,?,?)", (rel, "crashed", 0)); con.commit()
    run_pool(_harvest_one, todo, a.procs, _init, on_res, on_crash, chunksize=8)
    reg.commit(); con.commit()
    print(f"harvest done: registry has {len(reg.map)} identities in {time.time() - t0:.0f}s")


_E = None


def _apply_init():
    global _E
    os.nice(10)
    _E = core.Engine()


def _apply_one(rel):
    t = time.time()
    try:
        orel, handler, status, nrep, note, trace = core.apply_one(_E, rel)
    except Exception as e:
        return rel, "", "error", "error", 0, 0, time.time() - t, f"{type(e).__name__}:{e}"[:200], "{}"
    return rel, orel, handler, status, nrep, os.path.getsize(os.path.join(core.INPUT, rel)), time.time() - t, note, json.dumps(trace)


def cmd_apply(a):
    con = core.ledger()
    reg = Registry(core.REGDB, core.get_seed(), readonly=True)
    ver = core.reg_fingerprint(reg)
    rels = list(core.walk_inputs())
    if a.limit:
        rels = rels[: a.limit]
    done = {r for (r,) in con.execute("SELECT rel FROM files WHERE regver=? AND status IN ('ok')", (ver,))} if not a.force else set()
    todo = [r for r in rels if r not in done]
    print(f"apply: {len(rels)} files, {len(todo)} to do, registry {len(reg.map)} identities, version {ver}", flush=True)
    t0 = time.time(); n = 0; nbytes = 0
    stats = [0, 0]

    def on_res(res):
        rel, orel, handler, status, nrep, size, secs, note, trace = res
        con.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?,?,?)", (rel, orel, handler, status, nrep, size, secs, ver, note, trace))
        stats[0] += 1; stats[1] += size
        if stats[0] % 500 == 0:
            con.commit()
            el = time.time() - t0
            print(f"  {stats[0]}/{len(todo)} {stats[0] / el:.1f} files/s {stats[1] / el * 60 / 1e9:.2f} GB/min", flush=True)

    def on_crash(rel):   # a file that kills workers is cloned unchanged and listed
        try:
            eng = core.Engine()
            orel = eng.out_rel(rel)
            core.clone(os.path.join(core.INPUT, rel), os.path.join(core.OUT, orel))
            con.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?,?,?)", (rel, orel, "crash", "cloned-after-crash", 0, os.path.getsize(os.path.join(core.INPUT, rel)), 0, ver, "worker-crash", "{}"))
            con.commit()
        except Exception as e:
            print("crash handler failed", rel, e, file=sys.stderr)
    run_pool(_apply_one, todo, a.procs, _apply_init, on_res, on_crash, chunksize=4)
    n, nbytes = stats
    con.commit()
    el = max(time.time() - t0, 1e-6)
    print(f"apply done: {n} files, {nbytes / 1e9:.2f} GB in {el:.0f}s = {n / el * 60:.0f} files/min, {nbytes / 1e9 / el * 60:.2f} GB/min")


def cmd_survey(a):
    import subprocess
    subprocess.check_call([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "survey_report.py")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "harvest", "apply", "survey", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--procs", type=int, default=2, help="worker processes (default 2; raise for the full run)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "freeze":
        print("frozen file list:", core.freeze_list(), "complete files ->", core.FILELIST)
    if a.cmd in ("harvest", "all"):
        cmd_harvest(a)
    if a.cmd in ("apply", "all"):
        cmd_apply(a)
    if a.cmd == "survey":
        cmd_survey(a)


if __name__ == "__main__":
    main()
