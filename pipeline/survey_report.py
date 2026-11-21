#!/usr/bin/env python3.12
"""Aggregate the survey table (WORK/ledger.sqlite) into SURVEY.md. Counts only - no identifier values are written."""
import collections, json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deid import core

con = sqlite3.connect(core.LEDGER)
rows = con.execute("SELECT rel, ext, kind, size, where_hits, cands, note FROM survey").fetchall()
total = len(rows)
by = collections.defaultdict(lambda: {"n": 0, "bytes": 0, "hit": 0, "loc": collections.Counter(), "cand": collections.Counter(), "candfiles": collections.Counter(), "kinds": collections.Counter(), "err": 0})
src = collections.defaultdict(lambda: {"n": 0, "bytes": 0, "hit": 0, "exts": collections.Counter()})
for rel, ext, kind, size, wh, cands, note in rows:
    e = ext or "(none)"
    d = by[e]
    d["n"] += 1; d["bytes"] += size; d["kinds"][kind] += 1
    wh = json.loads(wh or "{}"); cands = json.loads(cands or "{}")
    if kind in ("error", "crashed"):
        d["err"] += 1
    if wh:
        d["hit"] += 1
        for k in wh:
            d["loc"][k.split(":")[0] if k.startswith("ole-stream") else k] += 1
            if k.startswith("ole-stream"):
                d["loc"][k] += 0
    for k, v in cands.items():
        d["cand"][k] += v; d["candfiles"][k] += 1
    p = rel.split("/")
    s = "/".join(p[:2]) if p[0] == "sources" else p[0]
    src[s]["n"] += 1; src[s]["bytes"] += size; src[s]["hit"] += 1 if wh else 0; src[s]["exts"][e] += 1
reg = sqlite3.connect(core.REGDB)
regs = reg.execute("SELECT kind, source, count(*) FROM identity GROUP BY 1, 2").fetchall()
kinds = collections.Counter(); sources = collections.Counter()
for k, s, n in regs:
    kinds[k] += n; sources[(s if s != "path-root" else "folder-name")] += n

out = []
w = out.append
w("# SURVEY - where identifiers live in the corpus\n")
w(f"Scope: {total:,} files downloaded at survey time (the rest of the 188,722 follows the same layout). "
  "Counts only; no original value appears in this file. \"Seed hits\" = files in which at least one registry identity "
  "(GitHub/GitLab owner and repository from the folder name, plus identities harvested from structured fields) occurs "
  "after decoding: raw bytes in ASCII/UTF-8/UTF-16LE, zip/tar/gzip members (names and content), OLE streams, PDF objects, XMP, "
  "attachments and content streams.\n")
w("## Registry (pass 1 result)\n")
w("Identities by kind: " + ", ".join(f"{k} {n:,}" for k, n in kinds.most_common()) + ".\n")
w("Identities by where first found: " + ", ".join(f"{k} {n:,}" for k, n in sources.most_common(12)) + ".\n")
w("## Per file type\n")
w("| type | files | GB | files with seed hits | where hits occur (files) | harvested candidates (files) |")
w("|---|---:|---:|---:|---|---|")
for ext, d in sorted(by.items(), key=lambda kv: -kv[1]["n"])[:34]:
    loc = ", ".join(f"{k} {n}" for k, n in d["loc"].most_common(5) if n)
    cand = ", ".join(f"{k} {d['candfiles'][k]}" for k, _ in d["cand"].most_common(4))
    w(f"| .{ext} | {d['n']:,} | {d['bytes'] / 1e9:.2f} | {d['hit']:,} ({100 * d['hit'] / max(d['n'], 1):.0f}%) | {loc or '-'} | {cand or '-'} |")
w("\n## Sources other than GitHub\n")
w("| source | files | GB | files with seed hits | most common types |")
w("|---|---:|---:|---:|---|")
for s, d in sorted(src.items(), key=lambda kv: -kv[1]["n"]):
    w(f"| {s} | {d['n']:,} | {d['bytes'] / 1e9:.2f} | {d['hit']:,} | " + ", ".join(f".{k} {n}" for k, n in d["exts"].most_common(5)) + " |")
w("""
## How a naive replacement breaks each format

* **STEP (.step/.stp)**: strings are `'...'` with `''` escapes, and the header is `FILE_NAME(name, time, (authors), (orgs), preprocessor, system, authorisation)`;
  replacing a name with one that contains a quote, a different length that crosses a line-wrap, or a non-ASCII character that needs `\\X2\\` escaping breaks the
  parse. Product names also appear in `PRODUCT`/`NEXT_ASSEMBLY_USAGE_OCCURRENCE`, so a rename must be applied everywhere or links between parts are lost.
* **IGES**: fixed 80-column records with a section letter and sequence number in columns 73-80, and Hollerith strings (`12Hsome text`) whose length prefix must match.
  Any length change corrupts every following record.
* **DXF / SAT / OBJ / SVG / WRL / STL-ASCII**: text with structure (group-code pairs, ACIS length-prefixed strings, XML). Equal-length replacement keeps all of them valid.
* **Zip-based (.zip, .fcstd, .3mf, .f3z/.f3d)**: member names and content hold identifiers; the CRC, sizes and the central directory must be rebuilt, and nested archives need recursion. Renaming a member without updating the references to it (3MF relationships, FreeCAD links) breaks the model.
* **OLE (.ipt/.iam/.idw, old .sldprt/.sldasm/.slddrw, .doc)**: summary / document-summary property streams carry author, last-saved-by, company, title; strings are length-prefixed and padded to 4 bytes, and sectors chain streams, so only equal-length in-place edits per stream are safe.
* **Newer SolidWorks files**: a custom container of raw-deflate chunks; names and properties inside compressed chunks cannot be reached without re-deflating to the same compressed size (not attempted in v1; such files are cloned and listed).
* **PDF**: info dictionary, XMP packet, embedded files, annotations and outlines hold identifiers; visible text lives in content streams with font-specific encodings (subset fonts, split `TJ` arrays), so a text search on the raw file misses it, and a naive byte edit breaks the xref table.
* **Images / meshes**: EXIF/XMP/PNG text chunks carry author/software/GPS; visible logos and title blocks are pixels. Binary STL/3MF mesh data must not be touched (vertex/facet counts).
* **Paths**: every GitHub file sits under `sources/github/<owner>__<repo>[__<12 hex>]/`; the owner is an account and the repo a project name. Renaming only the folder keeps relative links inside a repo intact; renaming file basenames needs the same replacement inside every file that references them.
""")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SURVEY.md"), "w").write("\n".join(out))
print("wrote SURVEY.md")
