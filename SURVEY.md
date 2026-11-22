# SURVEY - where identifiers live in the corpus

Scope: 188,719 files downloaded at survey time (the rest of the 188,722 follows the same layout). Counts only; no original value appears in this file. "Seed hits" = files in which at least one registry identity (GitHub/GitLab owner and repository from the folder name, plus identities harvested from structured fields) occurs after decoding: raw bytes in ASCII/UTF-8/UTF-16LE, zip/tar/gzip members (names and content), OLE streams, PDF objects, XMP, attachments and content streams.

## Registry (pass 1 result)

Identities by kind: account 1,682, domain 1,466, person 971, project 461, email 435, company 299, phone 85.

Identities by where first found: .pdf 2,012, .zip 1,444, folder-name 884, .step 176, .fcstd 151, .svg 126, .tar 115, .sldprt 104, repair 81, .stp 67, .1 41, .eps 26.

## Per file type

| type | files | GB | files with seed hits | where hits occur (files) | harvested candidates (files) |
|---|---:|---:|---:|---|---|
| .step | 57,701 | 45.83 | 54,982 (95%) | raw-bytes 54982 | domain 31577, person 27238, org 25659, userpath 2885 |
| .sat | 26,379 | 4.49 | 2,045 (8%) | raw-bytes 2045 | - |
| .sldprt | 18,792 | 8.66 | 2,673 (14%) | ole-stream 15329, ole-outside-streams 566, raw-bytes 83 | userpath 797, domain 347, person 1245, email 40 |
| .1 | 14,313 | 10.89 | 14,313 (100%) | raw-bytes 14313 | company 9362, domain 1334, person 4587, userpath 1172 |
| .stl | 12,768 | 14.94 | 1,697 (13%) | raw-bytes 1697 | domain 35, email 12, person 9 |
| .pdf | 10,342 | 6.06 | 7,995 (77%) | pdf-dict-strings 6014, pdf-xmp 4514, pdf-visible-overlay 4287, pdf-content-text 2062, raw-bytes 6 | domain 738, person 3984, account 1745, org 1804 |
| .svg | 7,863 | 1.54 | 5,390 (69%) | raw-bytes 5390 | domain 7737, person 305, userpath 143, email 53 |
| .ipt | 5,611 | 2.06 | 5,561 (99%) | ole-stream 14435, ole-outside-streams 192 | domain 61, userpath 57, person 8, company 1 |
| .fcstd | 4,717 | 3.10 | 4,716 (100%) | raw-bytes 4716, zip-member-content 4716 | person 4588, domain 4600, userpath 1694, company 331 |
| .stp | 4,525 | 7.89 | 4,445 (98%) | raw-bytes 4445 | person 3341, domain 2415, org 3308, userpath 53 |
| .wrl | 3,551 | 1.11 | 3,473 (98%) | raw-bytes 3473 | domain 2244, person 464 |
| .sldasm | 2,543 | 5.92 | 344 (14%) | ole-stream 2180, ole-outside-streams 157, raw-bytes 19 | userpath 109, person 142, domain 7, company 1 |
| .zip | 1,645 | 5.89 | 1,454 (88%) | zip-member-content 1435, raw-bytes 1250, ole-stream 609, zip-member-name 130, pdf-dict-strings 119 | domain 667, person 230, userpath 66, email 78 |
| .dxf | 1,625 | 0.56 | 273 (17%) | raw-bytes 273 | person 136, domain 36, email 11, userpath 2 |
| .slddrw | 1,593 | 1.00 | 484 (30%) | ole-stream 1341, ole-outside-streams 59, raw-bytes 1 | userpath 88, person 177, company 3, email 5 |
| .jt | 1,465 | 0.02 | 0 (0%) | - | - |
| .iam | 1,053 | 0.56 | 744 (71%) | ole-stream 2288, ole-outside-streams 33 | userpath 159, domain 14, person 1 |
| .prt | 921 | 0.34 | 910 (99%) | raw-bytes 853, ole-stream 61 | domain 95, userpath 70, person 23 |
| .gz | 826 | 0.19 | 339 (41%) | raw-bytes 338, pdf-content-text 1, pdf-visible-overlay 1 | person 15, email 4, domain 4, userpath 7 |
| .asm | 813 | 0.11 | 477 (59%) | ole-stream 502, raw-bytes 393, ole-outside-streams 30 | userpath 66, domain 212, person 67 |
| .dwg | 758 | 0.27 | 633 (84%) | raw-bytes 633 | userpath 57, domain 4, email 2, person 2 |
| .3mf | 723 | 2.99 | 723 (100%) | raw-bytes 723, zip-member-content 723, zip-member-name 2 | domain 603, userpath 97, person 92 |
| .f3d | 719 | 1.48 | 645 (90%) | raw-bytes 645, zip-member-content 639, zip-member-name 154 | domain 553, userpath 7, person 2 |
| .z | 719 | 0.38 | 5 (1%) | raw-bytes 5 | - |
| .png | 711 | 0.13 | 10 (1%) | raw-bytes 10 | domain 46, person 23, email 1 |
| .igs | 597 | 0.81 | 519 (87%) | raw-bytes 519 | person 528, org 528, userpath 120 |
| .jpg | 592 | 0.23 | 46 (8%) | raw-bytes 46 | domain 61, company 21, email 1 |
| .2 | 591 | 0.13 | 591 (100%) | raw-bytes 591 | person 4, company 1 |
| .obj | 461 | 4.11 | 91 (20%) | raw-bytes 91 | domain 329 |
| .par | 384 | 0.25 | 378 (98%) | ole-stream 1934, ole-outside-streams 65 | person 282 |
| .ps | 358 | 0.01 | 81 (23%) | raw-bytes 81 | company 11, person 9, email 3, domain 2 |
| .iges | 340 | 3.64 | 1 (0%) | raw-bytes 1 | person 337, org 337 |
| .x_b | 293 | 0.53 | 293 (100%) | raw-bytes 293 | - |
| .unv | 289 | 0.21 | 3 (1%) | raw-bytes 3 | - |

## Sources other than GitHub

| source | files | GB | files with seed hits | most common types |
|---|---:|---:|---:|---|
| sources/github | 178,453 | 125.75 | 110,710 | .step 56786, .sat 26371, .sldprt 17600, .1 14200, .stl 12513 |
| sources/existing | 4,444 | 9.15 | 3,288 | .pdf 2454, .step 566, .sldprt 452, .stp 378, .par 96 |
| sources/catalog | 3,535 | 2.67 | 2,057 | .sldprt 702, .pdf 561, .ipt 399, .jpg 351, .slddrw 299 |
| sources/web | 1,489 | 1.23 | 1,248 | .pdf 1084, .ipt 140, .step 66, .idw 51, .sldprt 38 |
| sources/gitlab | 794 | 0.74 | 388 | .fcstd 211, .stl 132, .pdf 113, .png 88, .jpg 63 |
| archives | 4 | 0.16 | 4 | .zip 4 |

## How a naive replacement breaks each format

* **STEP (.step/.stp)**: strings are `'...'` with `''` escapes, and the header is `FILE_NAME(name, time, (authors), (orgs), preprocessor, system, authorisation)`;
  replacing a name with one that contains a quote, a different length that crosses a line-wrap, or a non-ASCII character that needs `\X2\` escaping breaks the
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
