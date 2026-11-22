#!/usr/bin/env python3
"""Split the input manifest into shards for CI runners.   python3 plan_shards.py [--manifest FILE] [--out shards.json] [--max-gb 2.9] [--ledger LEDGER]
A shard is a contiguous range of the path-sorted manifest (so every path is in exactly one shard); shards.json stores numbers only
(no file names) plus the manifest's sha256, which run_shard.sh checks. With --ledger (the private run ledger, read only) the cost
of each file is the seconds the local run took, and a shard is also closed when its estimated cost passes --max-cost, so slow
formats (PDF, zip) do not make a few shards much slower than the rest. Prints totals so coverage can be checked."""
import argparse, json, os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shardlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="manifest.tsv (default: download it from the mirror)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "shards.json"))
    ap.add_argument("--max-gb", type=float, default=2.9, help="input bytes per shard (decimal GB)")
    ap.add_argument("--max-files", type=int, default=6000)
    ap.add_argument("--ledger", help="ledger.sqlite of the local run, for per-file cost (optional)")
    ap.add_argument("--max-cost", type=float, default=900.0, help="estimated local core-seconds per shard (needs --ledger)")
    ap.add_argument("--disk-gb", type=float, default=11.0, help="free disk to assume on a runner (input + output + tools)")
    a = ap.parse_args()
    man = a.manifest
    if not man:
        man = os.path.join(tempfile.mkdtemp(), "manifest.tsv")
        shardlib.fetch_manifest(man)
    rows = shardlib.load_manifest(man)
    cost = {}
    if a.ledger:
        con = sqlite3.connect(f"file:{os.path.abspath(a.ledger)}?immutable=1", uri=True)
        cost = {r: s for r, s in con.execute("SELECT rel, secs FROM files")}
    cap = int(a.max_gb * 1e9)
    shards, start, nb, nc, nf = [], 0, 0, 0.0, 0
    for i, (rel, size, _, _) in enumerate(rows):
        c = cost.get(rel, size / 25e6)          # without a ledger: about 25 MB per core-second
        if nf and (nb + size > cap or nf >= a.max_files or (a.ledger and nc + c > a.max_cost)):
            shards.append((start, i, nf, nb, nc)); start, nb, nc, nf = i, 0, 0.0, 0
        nb += size; nc += c; nf += 1
    if nf:
        shards.append((start, len(rows), nf, nb, nc))
    out = {"manifest_sha256": shardlib.sha256_file(man), "manifest_rows": len(rows), "max_bytes": cap,
           "shards": [{"id": k, "start": s, "end": e, "files": n, "bytes": b, "est_core_s": round(c)} for k, (s, e, n, b, c) in enumerate(shards)]}
    # coverage: ranges are contiguous and cover [0, rows)
    assert shards[0][0] == 0 and shards[-1][1] == len(rows) and all(x[1] == y[0] for x, y in zip(shards, shards[1:]))
    big = max(rows, key=lambda r: r[1])[1]
    biggest = max(shards, key=lambda x: x[3])
    need = 2 * biggest[3] / 1e9
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"manifest rows {len(rows)}  bytes {sum(r[1] for r in rows)}")
    print(f"shards {len(shards)}  files {sum(x[2] for x in shards)}  bytes {sum(x[3] for x in shards)}  (must equal the manifest totals)")
    print(f"largest shard: id {shards.index(biggest)}  {biggest[2]} files  {biggest[3] / 1e9:.2f} GB  (input+output {need:.1f} GB of {a.disk_gb} GB)")
    print(f"largest single file {big / 1e9:.2f} GB; most files in a shard {max(x[2] for x in shards)}; est. core-seconds max {max(x[4] for x in shards):.0f} mean {sum(x[4] for x in shards) / len(shards):.0f}")
    print("wrote", a.out)
    if need > a.disk_gb:
        raise SystemExit("a shard would not fit the runner disk: lower --max-gb")


if __name__ == "__main__":
    main()
