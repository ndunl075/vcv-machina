#!/usr/bin/env python3.12
"""Assemble attempt-N/code and attempt-N/README.txt next to attempt-N/corpus.   python make_attempt.py [attempt-dir]
Nothing private is copied: no seed, registry, ledger rows with original paths or raw input."""
import collections, os, shutil, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from deid import core

dest = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(core.OUT)
code = os.path.join(dest, "code")
if os.path.exists(code):
    shutil.rmtree(code)
shutil.copytree(HERE, code, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite*", "seed.bin", "venv", "tests/fixtures"))
root = os.path.dirname(HERE)
for f in ("SURVEY.md", "LICENSE"):
    if os.path.exists(os.path.join(root, f)):
        shutil.copy(os.path.join(root, f), code)

con = sqlite3.connect(core.LEDGER)
rows = con.execute("SELECT out_rel, handler, status, nrep, size, note FROM files").fetchall()
n = len(rows)
changed = sum(1 for r in rows if r[3])
empty = [r[0] for r in rows if r[4] == 0]
failed = [(r[0], r[2], r[5]) for r in rows if r[2] != "ok"]
fallback = [(r[0], r[5]) for r in rows if r[5] and ("handler-failed" in r[5] or "too-big" in r[5])]
by_handler = collections.Counter(r[1] for r in rows)

L = []
w = L.append
w("""MACHINA CAD DE-ID - ATTEMPT README

1. What is in this folder
  corpus/      one output file per input file, same relative layout and extensions; the only path parts that changed are the ones
               that carried an identity (the <owner>__<repo> folder name under sources/github and sources/gitlab, and any file or
               folder name that contained a registered identity). Duplicates and invalid files are kept (see section 4).
  code/        the complete pipeline (Python 3.12), SURVEY.md (where identifiers live), requirements.lock
  README.txt   this file

2. How to run (exact)
  python3.12 -m venv venv && ./venv/bin/pip install -r code/requirements.lock
  export DEID_INPUT=/path/to/input   # the corpus, laid out as sources/... and archives/...
  export DEID_WORK=/path/to/work     # private: registry.sqlite (identity -> pseudonym), seed.bin (secret), ledger.sqlite
  export DEID_OUT=/path/to/attempt-1/corpus
  cd code && PYTHON=../venv/bin/python ./run_all.sh 6
  Stages (each is resumable; a rerun skips finished files):
    run.py harvest   pass 1: find identities in every file (folder owner/repo, STEP/IGES header fields, OLE summary properties, PDF info/XMP/text,
                     SVG/FreeCAD/3MF metadata, e-mail addresses, URLs/domains, user-home paths, copyright holders, phone numbers after tel/fax/mobile)
                     and register each one with a deterministic pseudonym (HMAC of a private seed).
    run.py apply     pass 2: write every file to DEID_OUT. Unchanged files are APFS clones (clonefile), changed files are rewritten.
    verify.py        leak scan (ASCII/UTF-8/UTF-16LE, inside zip/tar/gzip/OLE members and PDF objects), per-format usability checks, registry consistency, completeness.
  Without the original seed the mapping cannot be reproduced and is not part of this submission.

3. Method in one paragraph
  Every pseudonym has exactly the same number of characters as the identity it replaces (a person gets a plausible person name, a company a company
  name, an account or project a word-style handle, a domain a domain with the same TLD, a part number the same pattern of digits and letters, a phone
  number the same layout). Equal length makes in-place replacement safe in binary files (no length field to repair). The same identity gets the same
  pseudonym everywhere: file and folder names, zip/tar/gzip member names, text and binary content, OLE property streams, PDF info/XMP/annotations/outlines/
  attachments/content streams, so references from one file to another that names a renamed file stay valid in every format that stores the name in readable bytes.
  Geometry, numbers, units, materials and structure are never touched: only registered strings are replaced. Generic words (dictionary words, software
  and format names) are never treated as identities inside file content; they are only renamed when they form a whole owner/repo folder name.

4. Limitations, source defects and omissions
""")
w(f"  Files processed: {n:,}; files with at least one replacement: {changed:,}; unchanged files are bit-identical clones.")
w("  Handler mix: " + ", ".join(f"{k} {v:,}" for k, v in by_handler.most_common()) + ".")
w("""  Not handled in this version (the files are kept, readable and listed by type, never dropped):
    - New-format SolidWorks (.sldprt/.sldasm/.slddrw written by SolidWorks 2015+), Inventor streams that are compressed, JT, Parasolid (.x_t/.x_b),
      CATIA, Creo (.prt, .1), DWG, F3D internals, U3D, .7z and .z archives: only identifiers that are stored uncompressed (file names, OLE summary
      properties, plain strings) are replaced; identifiers inside compressed chunks remain.
    - Logos and text that exist only as pixels (embedded previews, scanned drawings, PDF images) are not changed.
    - Free-text identifiers that are not registered (a name that never appears in a structured field, folder name, e-mail, URL, user path or
      copyright line) are not found.
    - Postal addresses are only replaced when they occur inside a registered string.
  Empty files in the input (kept as empty files, final paths):""")
for p in empty[:300]:
    w("    " + p)
if len(empty) > 300:
    w(f"    ... and {len(empty) - 300} more")
if not empty:
    w("    (none)")
w("  Files that could not be processed and were kept unchanged (final paths, reason):")
for p, st, note in failed[:300]:
    w(f"    {p}  [{st}: {note[:100]}]")
if not failed:
    w("    (none)")
w("  Files where the format handler failed and only raw equal-length byte replacement was applied (final paths):")
for p, note in fallback[:300]:
    w(f"    {p}  [{note[:100]}]")
if not fallback:
    w("    (none)")
w("""
5. No credentials, raw input, private mapping, seed or run log are included in this submission.
""")
open(os.path.join(dest, "README.txt"), "w").write("\n".join(L))
print("wrote", os.path.join(dest, "README.txt"), "and", code)
