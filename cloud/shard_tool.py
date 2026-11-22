#!/usr/bin/env python3
"""Helper for run_shard.sh. Prints only counts. Subcommands:
  prepare <id>   download the manifest, check it against shards.json, write the shard's file list, fetch its input files (size + md5 checked)
  check <id>     self-check the apply output against the ledger and the input sizes, write the result JSON
Environment: SHARD_TMP (work area), DEID_WORK (private work dir with registry/seed/ledger), DEID_INPUT, DEID_OUT, MACHINA_INPUT_BASE."""
import concurrent.futures as cf, hashlib, http.client, json, os, sqlite3, sys, threading, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shardlib

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.environ["SHARD_TMP"]
INPUT = os.environ["DEID_INPUT"]
OUT = os.environ["DEID_OUT"]
WORK = os.environ["DEID_WORK"]


def say(msg):
    print(msg, flush=True)


def shard_rows(sid):
    plan = json.load(open(os.path.join(HERE, "shards.json")))
    man = os.path.join(TMP, "manifest.tsv")
    if not os.path.exists(man):
        shardlib.fetch_manifest(man)
    if shardlib.sha256_file(man) != plan["manifest_sha256"]:
        raise SystemExit("manifest on the mirror differs from the one shards.json was planned from: run plan_shards.py again")
    rows = shardlib.load_manifest(man)
    if len(rows) != plan["manifest_rows"]:
        raise SystemExit("manifest row count differs from shards.json")
    sh = plan["shards"][sid]
    part = rows[sh["start"]:sh["end"]]
    if len(part) != sh["files"] or sum(r[1] for r in part) != sh["bytes"]:
        raise SystemExit("shard slice differs from shards.json")
    return sh, part


_tl = threading.local()


def _conn(host):
    c = getattr(_tl, "c", None)
    if c is None:
        c = _tl.c = http.client.HTTPSConnection(host, timeout=120)
    return c


def _drop():
    c = getattr(_tl, "c", None)
    if c is not None:
        try:
            c.close()
        except Exception:      # noqa: BLE001
            pass
    _tl.c = None


def fetch_one(host, root, rel, size, md5, upath):
    """returns '' on success or a short error word (never the name)."""
    dst = os.path.join(INPUT, rel)
    if os.path.isabs(rel) or ".." in rel.split("/"):
        return "badpath"
    if os.path.exists(dst) and os.path.getsize(dst) == size and not (md5 and _md5(dst) != md5):
        return ""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if size == 0:
        open(dst, "wb").close()
        return ""
    tmp = dst + ".part"
    err = "fetch"
    for attempt in range(6):
        try:
            c = _conn(host)
            c.request("GET", root + "/" + upath, headers={"Accept-Encoding": "identity"})
            r = c.getresponse()
            if r.status != 200:
                r.read(); _drop(); err = f"http{r.status}"
                if r.status == 404:
                    return err
                time.sleep(1 + attempt * 2); continue
            h = hashlib.md5(); n = 0
            with open(tmp, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b); h.update(b); n += len(b)
            if n != size:
                err = "size"; _drop(); time.sleep(1 + attempt); continue
            if md5 and h.hexdigest() != md5:
                err = "md5"; time.sleep(1 + attempt); continue
            os.replace(tmp, dst)
            return ""
        except Exception as e:      # noqa: BLE001
            err = type(e).__name__; _drop(); time.sleep(1 + attempt * 2)
    try:
        os.unlink(tmp)
    except OSError:
        pass
    return err


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cmd_prepare(sid):
    t0 = time.time()
    sh, rows = shard_rows(sid)
    with open(os.environ["DEID_FILELIST"], "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r[0] + "\n")
    base = (os.environ.get("MACHINA_INPUT_BASE") or shardlib.DEFAULT_BASE).rstrip("/")
    u = urllib.parse.urlsplit(base)
    jobs = int(os.environ.get("FETCH_JOBS", "32"))
    errs = {}
    with cf.ThreadPoolExecutor(jobs) as ex:
        futs = [ex.submit(fetch_one, u.netloc, u.path, r[0], r[1], r[2], r[3]) for r in rows]
        for fu in futs:
            e = fu.result()
            if e:
                errs[e] = errs.get(e, 0) + 1
    have = sum(1 for r in rows if os.path.exists(os.path.join(INPUT, r[0])) and os.path.getsize(os.path.join(INPUT, r[0])) == r[1])
    say(f"fetch: {have}/{len(rows)} files, {sum(r[1] for r in rows) / 1e9:.2f} GB, {time.time() - t0:.0f}s, errors {errs or 'none'}")
    if have != len(rows) or errs:
        raise SystemExit(2)


def cmd_check(sid):
    sh, rows = shard_rows(sid)
    size = {r[0]: r[1] for r in rows}
    con = sqlite3.connect(os.path.join(WORK, "ledger.sqlite"))
    led = {r: (o, st) for r, o, st in con.execute("SELECT rel, out_rel, status FROM files")}
    miss_led = sum(1 for r in size if r not in led)
    bad_status = sum(1 for r in size if r in led and led[r][1] != "ok")
    miss_out = empty_out = 0
    nbytes = 0
    for r, sz in size.items():
        if r not in led:
            continue
        p = os.path.join(OUT, led[r][0])
        try:
            osz = os.path.getsize(p)
        except OSError:
            miss_out += 1; continue
        nbytes += osz
        if sz > 0 and osz == 0:
            empty_out += 1
    files_out = sum(len(fs) for _, _, fs in os.walk(OUT))
    uniq_out = len({led[r][0] for r in size if r in led})
    stray = files_out - uniq_out
    collisions = len(size) - uniq_out
    fails = miss_led + bad_status + miss_out + empty_out + abs(stray) + collisions
    res = {"shard": sid, "files_in": len(rows), "files_out": files_out, "bytes_in": sum(size.values()), "bytes_out": nbytes,
           "failures": fails, "not_in_ledger": miss_led, "bad_status": bad_status, "missing_output": miss_out,
           "empty_output": empty_out, "stray_output": stray, "colliding_names": collisions}
    json.dump(res, open(os.path.join(TMP, "result.json"), "w"))
    say(f"check: in {res['files_in']} out {res['files_out']} failures {fails} (not-in-ledger {miss_led}, bad-status {bad_status}, missing {miss_out}, empty {empty_out}, stray {stray}, collisions {collisions})")
    if fails or files_out != len(rows):
        raise SystemExit(3)


if __name__ == "__main__":
    {"prepare": cmd_prepare, "check": cmd_check}[sys.argv[1]](int(sys.argv[2]))
