import os, random, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from deid import core
ext = sys.argv[1].lower(); n = int(sys.argv[2])
eng = core.Engine()
fs = [r for r in core.walk_inputs() if r.lower().endswith(ext)]
random.seed(3); random.shuffle(fs)
c = collections.Counter()
for rel in fs[:n]:
    data = open(os.path.join(core.INPUT, rel), "rb").read()
    for off, rep in eng.cm.patches(data):
        c[data[off:off + len(rep)]] += 1
for k, v in c.most_common(15):
    print(v, k[:60])
