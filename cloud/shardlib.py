"""Shared by plan_shards.py and shard_tool.py: the manifest in a fixed order, and the slice a shard id stands for.
A shard is a contiguous range [start, end) of the manifest sorted by path (raw UTF-8 bytes), so shards.json holds only numbers."""
import hashlib, os, urllib.request

DEFAULT_BASE = "https://machina-input.joinbuilders.org"


def fetch_manifest(dest: str, base: str = "") -> None:
    base = (base or os.environ.get("MACHINA_INPUT_BASE") or DEFAULT_BASE).rstrip("/")
    req = urllib.request.Request(base + "/manifest.tsv", headers={"Accept-Encoding": "gzip"})
    last = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
            with open(dest, "wb") as f:
                f.write(data)
            return
        except Exception as e:      # noqa: BLE001
            last = e
    raise SystemExit(f"manifest download failed: {type(last).__name__}")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: str):
    """[(rel, size, md5, urlpath)] sorted by rel bytes; '#' lines skipped; duplicate paths are an error."""
    rows = []
    with open(path, "rb") as f:
        for line in f:
            if line.startswith(b"#") or not line.strip():
                continue
            p = line.rstrip(b"\n").split(b"\t")
            if len(p) < 4:
                raise SystemExit("bad manifest row")
            rows.append((p[0], int(p[1]), p[2].decode(), p[3].decode("ascii")))
    rows.sort(key=lambda r: r[0])
    for a, b in zip(rows, rows[1:]):
        if a[0] == b[0]:
            raise SystemExit("duplicate path in manifest")
    return [(r[0].decode("utf-8"), r[1], r[2], r[3]) for r in rows]
