#!/usr/bin/env python3
"""Byte-compare a shard's output with the same files of an earlier full run.   compare_out.py <shard-corpus-dir> <reference-corpus-dir> [report-file]
Prints counts only; the list of differing files (with size and number of differing bytes) goes to report-file (private: it has names)."""
import filecmp, os, sys, collections
a, b = sys.argv[1], sys.argv[2]
rep = open(sys.argv[3], "w") if len(sys.argv) > 3 else None
same = diff = missing = 0
by_ext = collections.Counter()
for d, _, fs in os.walk(a):
    for f in fs:
        pa = os.path.join(d, f)
        rel = os.path.relpath(pa, a)
        pb = os.path.join(b, rel)
        if not os.path.exists(pb):
            missing += 1
            if rep: rep.write(f"MISSING-IN-REFERENCE\t{rel}\n")
            continue
        if os.path.getsize(pa) == os.path.getsize(pb) and filecmp.cmp(pa, pb, shallow=False):
            same += 1
        else:
            diff += 1
            ext = os.path.splitext(f)[1].lower()
            by_ext[ext] += 1
            if rep:
                da, db = open(pa, "rb").read(), open(pb, "rb").read()
                nd = sum(x != y for x, y in zip(da, db)) + abs(len(da) - len(db))
                rep.write(f"DIFF\t{rel}\t{len(da)}\t{len(db)}\t{nd}\n")
print(f"files {same + diff + missing}: identical {same}, different {diff}, not in reference {missing}")
if by_ext:
    print("different by extension:", dict(by_ext))
