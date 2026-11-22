#!/usr/bin/env python3.12
"""Remove files in DEID_OUT that the ledger does not know (left over from an earlier run with an older registry)."""
import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from deid import core
keep = {r[0] for r in sqlite3.connect(core.LEDGER).execute("SELECT out_rel FROM files")}
unrep = os.path.join(core.WORK, "unrepresentable.tsv")
if os.path.exists(unrep):
    for l in open(unrep, encoding="utf-8"):
        f = l.rstrip("\n").split("\t")
        if len(f) >= 2 and f[1]:
            keep.add(f[1])
n = 0
for d, dirs, files in os.walk(core.OUT, topdown=False):
    for f in files:
        if os.path.relpath(os.path.join(d, f), core.OUT) not in keep:
            os.unlink(os.path.join(d, f)); n += 1
    if d != core.OUT and not os.listdir(d):
        os.rmdir(d)
print("removed", n, "stale files")
