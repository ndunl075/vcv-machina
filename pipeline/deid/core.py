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

_libc = None
if sys.platform == "darwin":          # APFS copy-on-write clone; every other platform uses a plain copy
    try:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        _libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    except (OSError, AttributeError):
        _libc = None


def get_seed() -> bytes:
    if not os.path.exists(SEEDFILE):
        if os.environ.get("DEID_REQUIRE_SEED") == "1":     # a worker must never invent a seed: its pseudonyms would not match the registry
            raise SystemExit("seed.bin is missing and DEID_REQUIRE_SEED=1")
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
    if _libc is not None and _libc.clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
        return
    import shutil
    shutil.copyfile(src, dst)
    shutil.copystat(src, dst)


FILELIST = os.environ.get("DEID_FILELIST") or os.path.join(WORK, "filelist.txt")
MANIFEST = os.environ.get("DEID_MANIFEST", "/Users/nico/Developer/vcv-kits/machina/manifest.tsv")


def freeze_list(root: str = INPUT) -> int:
    """Write the list of fully downloaded files (size equals the manifest size) so a run works on a fixed snapshot."""
    want = {}
    with open(MANIFEST, encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2:
                want[p[0]] = int(p[1])
    n = 0
    with open(FILELIST, "w", encoding="utf-8") as out:
        for rel in sorted(want):
            try:
                if os.path.getsize(os.path.join(root, rel)) == want[rel]:
                    out.write(rel + "\n"); n += 1
            except OSError:
                pass
    return n


def walk_inputs(root: str = INPUT):
    if os.environ.get("DEID_USE_LIST") == "1" and os.path.exists(FILELIST):
        with open(FILELIST, encoding="utf-8") as f:
            for line in f:
                yield line.rstrip("\n")
        return
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            yield os.path.relpath(p, root)


# Output names for the three input files whose names the macOS build machine could not store (APFS rejects U+FFC9 and U+FFD0 in a name).
# attempt-1 stores them with each such character replaced by "_" (see README section 4); DEID_LEGALIZE=1 makes other machines (which can store
# the true name) produce exactly the same output path, so the README stays true for every run.
_APFS_REJECTED = "\uffc9\uffd0"


def legalize(orel: str) -> str:
    if os.environ.get("DEID_LEGALIZE") != "1":
        return orel
    return "".join("_" if ch in _APFS_REJECTED else ch for ch in orel)


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


def gitlab_parts(component: str):
    """'gitlab.com__group__sub__repo[__hash12]' -> (host, [names...], hash|None)."""
    parts = component.split("__")
    h = None
    if len(parts) >= 3 and HEX12.match(parts[-1]):
        h = parts[-1]; parts = parts[:-1]
    if len(parts) >= 3 and "." in parts[0]:
        return parts[0], parts[1:], h
    return None


PUBLIC_WEB = set("""arxiv.org github.com gitlab.com wikipedia.org wikimedia.org youtube.com researchgate.net academia.edu semanticscholar.org
doi.org ieee.org springer.com sciencedirect.com nasa.gov nist.gov iso.org ansi.org autodesk.com solidworks.com 3ds.com ptc.com siemens.com
grabcad.com thingiverse.com printables.com cults3d.com sketchfab.com google.com""".split())


def seed_paths(reg: Registry, rels):
    """Register the structured identities that every path starts from: GitHub owner/repo, GitLab group/repo, web host,
    catalog dataset title. Generic-looking single words stay 'path' scope (renamed only as a whole root folder)."""
    seen = set()
    for rel in rels:
        p = rel.split("/")
        if len(p) < 3 or p[0] != "sources" or (p[1], p[2]) in seen:
            continue
        seen.add((p[1], p[2]))
        if p[1] == "github":
            rp = repo_parts(p[2])
            if rp:
                o, r, _ = rp
                for v, kind in ((o, "account"), (r, "project")):
                    reg.pseudonym(v, kind, "path-root", scope="path" if ident.is_generic_phrase(v) else "all")
        elif p[1] == "gitlab":
            gp = gitlab_parts(p[2])
            if gp:
                named = [x for x in gp[1] if x]
                for i, v in enumerate(named):
                    reg.pseudonym(v, "project" if i == len(named) - 1 else "account", "path-root", scope="path" if ident.is_generic_phrase(v) else "all")
        elif p[1] == "web":
            from .registry import split_domain
            sub, rd = split_domain(p[2])
            if rd and rd not in PUBLIC_WEB and rd not in ident.PUBLIC_DOMAINS and len(rd) >= 6:
                reg.pseudonym(rd, "domain", "path-root")
        elif p[1] == "catalog":
            if len(p[2]) >= 8:
                reg.pseudonym(p[2], "project", "path-root", scope="path" if ident.is_generic_phrase(p[2]) else "all")
    reg.commit()


def reg_fingerprint(reg: Registry) -> str:
    h = hashlib.sha1()
    for o in sorted(reg.map):
        h.update(o.encode("utf-8", "surrogatepass")); h.update(reg.map[o][1].encode("utf-8", "surrogatepass"))
    return h.hexdigest()[:12]


# Registered from folder names but ordinary engineering words: replacing them inside drawings and models would destroy non-identifying text
NEVER_IN_CONTENT = {"parts", "part", "resources", "holders", "users", "models", "files", "drawings", "assemblies", "components", "docs",
                    "documents", "projects", "tools", "designs", "sources", "library", "libraries", "master", "main", "test", "tests", "data"}


class Engine:
    """Loaded read-only registry + matchers; one per worker process."""
    def __init__(self):
        self.reg = Registry(REGDB, get_seed(), readonly=True)
        # content identities (scope "all") are replaced everywhere, in paths too; "path"-scope identities (generic-looking owner/repo
        # names such as a repo called "models") are only replaced as the whole <owner>__<repo> root folder, never inside other paths
        allid = [(o, self.reg.map[o][1]) for o in self.reg.map if self.reg.scope.get(o) == "all"]
        extra = []
        for o in list(self.reg.map):     # 'Last, First' / 'Last First' orderings of two-token person names
            k, p = self.reg.map[o]
            a, b = o.split(" "), p.split(" ")
            if k == "person" and self.reg.scope.get(o) == "all" and len(a) == 2 and len(b) == 2 and all(a) and all(b):
                extra.append((f"{a[1]}, {a[0]}", f"{b[1]}, {b[0]}"))
                extra.append((f"{a[1]} {a[0]}", f"{b[1]} {b[0]}"))
        # path matcher: every identity (a folder called like a registered ordinary word is still renamed); content matcher: without the
        # ordinary engineering words that came from folder names
        self.pm = Matcher(allid + extra, min_len=4)
        self.cm = Matcher([x for x in allid if x[0].lower() not in NEVER_IN_CONTENT] + extra, min_len=4)
        self.ctx_notes: list = []
        # identities found only in the visible text of PDFs (scope "pdf"): replaced inside PDFs only, never in paths or other formats
        pdfid = [(o, self.reg.map[o][1]) for o in self.reg.map if self.reg.scope.get(o) == "pdf"]
        pextra = []
        for o, p_ in pdfid:
            a, b = o.split(" "), p_.split(" ")
            if self.reg.map[o][0] == "person" and len(a) == 2 and len(b) == 2 and all(a) and all(b):
                pextra += [(f"{a[1]}, {a[0]}", f"{b[1]}, {b[0]}"), (f"{a[1]} {a[0]}", f"{b[1]} {b[0]}")]
        self.ctx = rewrite.Ctx(self.cm, self.pm, self.ctx_notes, reg=self.reg)
        self.ctx.pdfm = Matcher(pdfid + pextra, min_len=4) if pdfid else None

    def out_rel(self, rel: str) -> str:
        comps = rel.split("/")
        res = []
        for i, c in enumerate(comps):
            if i == 2 and comps[0] == "sources" and comps[1] == "gitlab":
                gp = gitlab_parts(c)
                if gp:
                    host, names, h = gp
                    res.append("__".join([host] + [self.reg.pseudonym(n, "project") if n else "" for n in names]) + ("__" + h if h else ""))
                    continue
            if i == 2 and comps[0] == "sources" and comps[1] == "github":
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


def apply_one(eng: Engine, rel: str, src: str | None = None, orel_override: str | None = None):
    """Returns (out_rel, handler, status, nrep, note, trace). src / orel_override serve files that cannot live under their own name."""
    src = src or os.path.join(INPUT, rel)
    orel = orel_override or legalize(eng.out_rel(rel))
    dst = os.path.join(OUT, orel)
    eng.ctx_notes.clear()
    eng.ctx.trace.clear()
    st = os.stat(src)
    size = st.st_size
    if size == 0:
        clone(src, dst)
        return orel, "empty", "ok", 0, "empty-input", {}
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
                return orel, kind, "ok", 0, ";".join(eng.ctx_notes), dict(eng.ctx.trace)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(new)
            os.utime(dst, (st.st_atime, st.st_mtime))
            return orel, kind, "ok", 1, ";".join(eng.ctx_notes), dict(eng.ctx.trace)
        patches = _scan_patches(src, size, eng.cm)
        clone(src, dst)
        if patches:
            with open(dst, "r+b") as f:
                for off, rep in patches:
                    f.seek(off); f.write(rep)
        return orel, "raw" if kind == "raw" else kind + "-big", "ok", len(patches), ";".join(eng.ctx_notes), ({"raw-bytes": len(patches)} if patches else {})
    except Exception as e:
        # never drop a file: keep it unchanged and report
        try:
            clone(src, dst)
        except Exception:
            pass
        return orel, kind, "cloned-after-error", 0, f"{type(e).__name__}:{e}"[:200], {}


# ---------------------------------------------------------------------------------------------- ledger
def ledger():
    con = sqlite3.connect(LEDGER, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS files(rel TEXT PRIMARY KEY, out_rel TEXT, handler TEXT, status TEXT, nrep INTEGER, size INTEGER,
                   secs REAL, regver TEXT, note TEXT, trace TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS harvest(rel TEXT PRIMARY KEY, status TEXT, ncand INTEGER, kinds TEXT)""")
    for tbl, col in (("files", "trace"), ("harvest", "kinds")):
        if col not in [r[1] for r in con.execute(f"PRAGMA table_info({tbl})")]:
            con.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS survey(rel TEXT PRIMARY KEY, ext TEXT, kind TEXT, size INTEGER, where_hits TEXT, cands TEXT, note TEXT)""")
    return con
