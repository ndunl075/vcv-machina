#!/usr/bin/env python3
"""EXPERIMENTAL / UNTESTED: server-side copy of unchanged objects from an earlier attempt folder into a new one, so a later
attempt only uploads files that changed. Uses the same bearer token and the GCS XML API as kit/upload.py.

  1. python3 copy_unchanged.py --probe --token T --src gs://B/teams/ID/attempt-1/ --dst gs://B/teams/ID/attempt-2/
     copies ONE small object and reports whether the token is allowed to (needs read on src and write on dst);
  2. without --probe: for every file listed in the ledger as unchanged (nrep=0), when the source folder holds the same key with the
     same size and MD5 (the manifest md5 is the input md5, and unchanged outputs are bit-identical clones), copy it server-side.
  3. then run kit/upload.py as usual: it skips what is already there (same size + MD5) and uploads the rest.
"""
import argparse, http.client, os, sqlite3, sys, urllib.parse, xml.etree.ElementTree as ET
HOST = "storage.googleapis.com"


def enc(k):
    return "/".join(urllib.parse.quote(p, safe="") for p in k.split("/"))


def split(u):
    b, p = u[5:].split("/", 1)
    return b, p if p.endswith("/") else p + "/"


def listing(conn, tok, bucket, prefix):
    out, cont = {}, None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000", "encoding-type": "url"}
        if cont:
            q["continuation-token"] = cont
        conn.request("GET", f"/{bucket}/?{urllib.parse.urlencode(q)}", headers={"Authorization": f"Bearer {tok}"})
        r = conn.getresponse(); body = r.read()
        if r.status != 200:
            raise SystemExit(f"list failed {r.status}: {body[:200]!r}")
        root = ET.fromstring(body); ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
        for c in root.findall(ns + "Contents"):
            out[urllib.parse.unquote_plus(c.findtext(ns + "Key"))] = (int(c.findtext(ns + "Size")), (c.findtext(ns + "ETag") or "").strip('"').lower())
        if root.findtext(ns + "IsTruncated") != "true":
            return out
        cont = root.findtext(ns + "NextContinuationToken")


def copy(conn, tok, bucket, src_key, dst_key):
    conn.request("PUT", f"/{bucket}/{enc(dst_key)}", headers={"Authorization": f"Bearer {tok}", "x-goog-copy-source": f"/{bucket}/{enc(src_key)}", "Content-Length": "0"})
    r = conn.getresponse(); body = r.read()
    return r.status, body[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("MACHINA_UPLOAD_TOKEN", ""))
    ap.add_argument("--src", required=True); ap.add_argument("--dst", required=True)
    ap.add_argument("--ledger", default=os.path.join(os.environ.get("DEID_WORK", "."), "ledger.sqlite"))
    ap.add_argument("--manifest", default="manifest.tsv")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    (b1, p1), (b2, p2) = split(a.src), split(a.dst)
    assert b1 == b2, "server-side copy stays inside one bucket"
    conn = http.client.HTTPSConnection(HOST, timeout=120)
    have = listing(conn, a.token, b1, p1 + "corpus/")
    print(f"{len(have)} objects in the source attempt")
    if a.probe:
        key, (size, _) = min(have.items(), key=lambda kv: kv[1][0])
        st, body = copy(conn, a.token, b1, key, p2 + key[len(p1):])
        print("probe copy of", size, "bytes ->", st, body)
        return
    md5 = {}
    for line in open(a.manifest):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 3 and f[2]:
            md5[f[0]] = f[2]
    con = sqlite3.connect(a.ledger)
    done = skipped = 0
    for rel, orel, size in con.execute("SELECT rel, out_rel, size FROM files WHERE nrep=0 AND status='ok'"):
        key = p1 + "corpus/" + orel
        h = have.get(key)
        if not h or h[0] != size or (md5.get(rel) and h[1] != md5[rel]):
            skipped += 1; continue
        st, body = copy(conn, a.token, b1, key, p2 + "corpus/" + orel)
        if st >= 300:
            raise SystemExit(f"copy failed {st}: {body!r}")
        done += 1
        if done % 2000 == 0:
            print(done, "copied")
    print(f"copied {done}, left for upload.py {skipped}")


if __name__ == "__main__":
    main()
