"""Run configuration, seed handling, path renaming, per-file apply, ledger."""
from __future__ import annotations
import ctypes, ctypes.util, hashlib, mmap, os, re, secrets, sqlite3, sys, time
from . import rewrite, harvest, ident
from .matcher import Matcher
from .registry import Registry

INPUT = os.environ.get("DEID_INPUT", "/Volumes/vcvmachina/input")
WORK = os.environ.get("DEID_WORK", "/Volumes/vcvmachina/work")
OUT = os.environ.get("DEID_OUT", "/Volumes/vcvmachina/out/attempt-1/corpus")
REGDB = os.path.join(WORK, "registry.sqlite")
LEDGER = os.path.join(WORK, "ledger.sqlite")
SEEDFILE = os.path.join(WORK, "seed.bin")
HEX12 = re.compile(r"^[0-9a-f]{12}$")

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]


def get_seed() -> bytes:
    if not os.path.exists(SEEDFILE):
        os.makedirs(WORK, exist_ok=True)
        with open(SEEDFILE, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(SEEDFILE, 0o600)
    return open(SEEDFILE, "rb").read()


def clone(src: str, dst: str):
    """APFS clone (copy-on-write); falls back to a real copy only if cloning is impossible."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.unlink(dst)
    if _libc.clonefile(os.fsencode(src), os.fsencode(dst), 0) != 0:
        err = ctypes.get_errno()
        import shutil
        shutil.copyfile(src, dst)
        shutil.copystat(src, dst)


def walk_inputs(root: str = INPUT):
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            yield os.path.relpath(p, root)


def repo_parts(component: str):
    """'owner__repo[__hash12]' -> (owner, repo, hash|None) or None."""
    parts = component.split("__")
    h = None
    if len(parts) >= 3 and HEX12.match(parts[-1]):
        h = parts[-1]; parts = parts[:-1]
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1], h
    if len(parts) > 2:
        return parts[0], "__".join(parts[1:]), h
    return None


def seed_paths(reg: Registry, rels):
    """Register owner / repo of github + gitlab roots (structured identities; every path starts from these)."""
    seen = set()
    for rel in rels:
        p = rel.split("/")
        if len(p) >= 3 and p[0] == "sources" and p[1] in ("github", "gitlab") and p[2] not in seen:
            seen.add(p[2])
            rp = repo_parts(p[2])
            if rp:
                o, r, _ = rp
                for v, kind in ((o, "account"), (r, "project")):
                    reg.pseudonym(v, kind, "path-root", scope="path" if ident.is_generic_phrase(v) else "all")
    reg.commit()


def reg_fingerprint(reg: Registry) -> str:
    h = hashlib.sha1()
    for o in sorted(reg.map):
        h.update(o.encode("utf-8", "surrogatepass")); h.update(reg.map[o][1].encode("utf-8", "surrogatepass"))
    return h.hexdigest()[:12]


class Engine:
    """Loaded read-only registry + matchers; one per worker process."""
    def __init__(self):
        self.reg = Registry(REGDB, get_seed(), readonly=True)
        allp = [(o, p) for o, _k, p in self.reg.items("path")]
        content = [(o, self.reg.map[o][1]) for o in self.reg.map if self.reg.scope.get(o) == "all"]
        self.pm = Matcher(allp, min_len=3, boundary_len=7)
        self.cm = Matcher(content, min_len=4, boundary_len=7)
        self.ctx_notes: list = []
        self.ctx = rewrite.Ctx(self.cm, self.pm, self.ctx_notes)

    def out_rel(self, rel: str) -> str:
        comps = rel.split("/")
        res = []
        for i, c in enumerate(comps):
            if i == 2 and comps[0] == "sources" and comps[1] in ("github", "gitlab"):
                rp = repo_parts(c)
                if rp:
                    o, r, h = rp
                    po, pr = self.reg.pseudonym(o, "account"), self.reg.pseudonym(r, "project")
                    res.append(po + "__" + pr + ("__" + h if h else ""))
                    continue
            res.append(self.pm.replace_str(c)[0])
        return "/".join(res)


def _scan_patches(path: str, size: int, m: Matcher):
    """Chunked scan of a (possibly huge) file for in-place patches."""
    CH, OV = 64 << 20, max(m.max_pat * 2 + 8, 4096)
    patches = []
    with open(path, "rb") as f:
        pos = 0
        while pos < size:
            f.seek(max(0, pos - 8))
            lead = min(pos, 8)
            buf = f.read(CH + OV + lead)
            for off, rep in m.patches(buf):
                a = pos - lead + off
                if pos <= a < pos + CH or (pos + CH >= size and a >= pos):
                    patches.append((a, rep))
            pos += CH
    return sorted(set(patches))


def apply_one(eng: Engine, rel: str):
    """Returns (out_rel, handler, status, nrep, note)."""
    src = os.path.join(INPUT, rel)
    orel = eng.out_rel(rel)
    dst = os.path.join(OUT, orel)
    eng.ctx_notes.clear()
    st = os.stat(src)
    size = st.st_size
    if size == 0:
        clone(src, dst)
        return orel, "empty", "ok", 0, "empty-input"
    with open(src, "rb") as f:
        head = f.read(8)
        f.seek(257); tarmagic = f.read(5)
    kind = "tar" if tarmagic == b"ustar" and size > 512 else rewrite.sniff(rel, head)
    try:
        if kind in ("zip", "pdf", "ole", "gzip", "tar") and size <= rewrite.BIG:
            data = open(src, "rb").read()
            new = rewrite.process_blob(eng.ctx, rel, data)
            if new is None:
                clone(src, dst)
                return orel, kind, "ok", 0, ";".join(eng.ctx_notes)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(new)
            os.utime(dst, (st.st_atime, st.st_mtime))
            return orel, kind, "ok", 1, ";".join(eng.ctx_notes)
        patches = _scan_patches(src, size, eng.cm)
        clone(src, dst)
        if patches:
            with open(dst, "r+b") as f:
                for off, rep in patches:
                    f.seek(off); f.write(rep)
        return orel, "raw" if kind == "raw" else kind + "-big", "ok", len(patches), ";".join(eng.ctx_notes)
    except Exception as e:
        # never drop a file: keep it unchanged and report
        try:
            clone(src, dst)
        except Exception:
            pass
        return orel, kind, "cloned-after-error", 0, f"{type(e).__name__}:{e}"[:200]


# ---------------------------------------------------------------------------------------------- ledger
def ledger():
    con = sqlite3.connect(LEDGER, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS files(rel TEXT PRIMARY KEY, out_rel TEXT, handler TEXT, status TEXT, nrep INTEGER, size INTEGER,
                   secs REAL, regver TEXT, note TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS harvest(rel TEXT PRIMARY KEY, status TEXT, ncand INTEGER)""")
    con.execute("""CREATE TABLE IF NOT EXISTS survey(rel TEXT PRIMARY KEY, ext TEXT, kind TEXT, size INTEGER, where_hits TEXT, cands TEXT, note TEXT)""")
    return con
