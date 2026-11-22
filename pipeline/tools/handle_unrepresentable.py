#!/usr/bin/env python3.12
"""Files whose names the local filesystem (APFS) refuses: fetch the bytes from the contest input server to a safe temporary name,
verify the manifest md5, run the normal pipeline on them and write the output under the closest legal name.
Usage: handle_unrepresentable.py <problems.tsv> <manifest.tsv>      (needs the finished registry; run after `run.py apply`)
Writes the list of what could not be stored under its expected path to WORK/unrepresentable.tsv (used by make_attempt.py)."""
import hashlib, os, subprocess, sys, tempfile, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from deid import core

BASE = "https://machina-input.joinbuilders.org/"


def legal_component(c: str, probe_dir: str) -> str:
    out = []
    for ch in c:
        try:
            fd = os.open(os.path.join(probe_dir, "p" + ch), os.O_CREAT | os.O_WRONLY)
            os.close(fd); os.unlink(os.path.join(probe_dir, "p" + ch))
            out.append(ch)
        except OSError:
            out.append("_")
    return "".join(out)


def main():
    probs = [l.split(b"\t")[1] for l in open(sys.argv[1], "rb").read().split(b"\n") if l.startswith(b"missing\t")]
    man = {}
    for l in open(sys.argv[2], "rb"):
        f = l.rstrip(b"\n").split(b"\t")
        man[f[0]] = f
    eng = core.Engine()
    tmp = tempfile.mkdtemp(dir=core.WORK)
    rows = []
    for p in probs:
        f = man.get(p)
        rel = p.decode("utf-8", "surrogateescape")
        if not f:
            rows.append((rel, "", "no-manifest-row")); continue
        url = BASE + f[3].decode()
        local = os.path.join(tmp, hashlib.md5(p).hexdigest())
        rc = subprocess.call(["curl", "-fsS", "--retry", "5", "-o", local, url])
        if rc or os.path.getsize(local) != int(f[1]) or (f[2] and hashlib.md5(open(local, "rb").read()).hexdigest().encode() != f[2]):
            rows.append((rel, "", "fetch-or-checksum-failed")); continue
        orel = eng.out_rel(rel)
        legal = "/".join(legal_component(c, tmp) for c in orel.split("/"))
        res = core.apply_one(eng, rel, src=local, orel_override=legal)
        rows.append((rel, legal, "stored-under-legal-name" if legal != orel else "ok"))
        os.unlink(local)
    with open(os.path.join(core.WORK, "unrepresentable.tsv"), "w") as o:
        for r in rows:
            o.write("\t".join(r) + "\n")
    print(rows if len(rows) < 5 else len(rows), "processed")


if __name__ == "__main__":
    main()
