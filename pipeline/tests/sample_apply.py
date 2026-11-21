"""Apply the rewriter in-process to a random sample of real files (dry: nothing written) to catch crashes and slow handlers."""
import os, random, sys, time, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from deid import core, rewrite
ext = sys.argv[1].lower(); n = int(sys.argv[2])
eng = core.Engine()
fs = [r for r in core.walk_inputs() if r.lower().endswith(ext)]
random.seed(3); random.shuffle(fs)
stat = collections.Counter(); tot = 0
for rel in fs[:n]:
    data = open(os.path.join(core.INPUT, rel), "rb").read()
    t = time.time(); eng.ctx_notes.clear()
    try:
        new = rewrite.process_blob(eng.ctx, rel, data)
        stat["changed" if new is not None else "same"] += 1
        if new is not None and len(new) != len(data) and rewrite.sniff(rel, data) in ("raw", "ole"):
            stat["LEN-DIFF"] += 1
    except Exception as e:
        stat["EXC:" + type(e).__name__] += 1
    dt = time.time() - t; tot += dt
    if dt > 5: print("slow", round(dt, 1), len(data))
    for x in eng.ctx_notes: stat["note:" + x.split(":")[0]] += 1
print(ext, dict(stat), f"{tot:.1f}s total")
