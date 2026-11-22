# att4 recall round: orgs.py + holders, registry 4,831 -> 6,850; an2 org ALL-left 44->19, copyright ALL-left 22->16 (fix1 -> att4)
# att4 round 2: text-only discoveries use scope "pdf" (PDF-only matcher in Engine.ctx.pdfm), strict_ok guards in ident.py (person/company/phone/domain; project+address dropped),
# registry re-harvested from the ORIGINAL registry: 4,831 -> 6,044 identities. Sample: PDF fields all changed 180/186, OLE 139/142 (was 183/142 before this round).
# att4 round 3: registry re-harvested again (4,831 -> 6,329); sample fields all changed PDF 183/186, OLE 142/142; leaks 8 PDF content, 1 path.
# STATE att4 (branch att4, from fix1 cdf4466 + pdftext merged)
- Pseudonyms: registered identities come from the registry; unregistered ones are a pure function of (seed, kind, normalised original) probing only against
  the (read-only, identical on every slice) registry: Registry._pure, Overlay (per-file text identities), case-insensitive twins share one pseudonym.
- Chain matcher scans the original once (per-file matches win), path matcher keeps NEVER_IN_CONTENT words, OLE m_all uses content_safe, _sub cannot KeyError.
- harvest-meta registers the same text candidates apply finds (perfile.text_candidates) plus pdftext title-block identities. Full run: 4,831 -> 6,886 identities (224 s, 4 procs).
- cloud/registry.enc repacked from that registry.

# STATE (worker mac-fix, branch fix1) - updated after the harvest-meta timing test

## Diagnosis so far (rates measured on a 300-PDF / 150-OLE sample over many source folders; full-corpus metadata scan of 10,253 PDF + 10,965 OLE where noted)
- Scorer row names cannot be read directly; measured proxies only.
- PDF Info/XMP identity fields (author-style) in the first run: unchanged in 18.5% of 6,561 PDFs with an author (full corpus). Cause: content guards
  (min length 4-5, "dictionary word" guard that also covers given names, mixed-case guard) dropped short names, accounts, generic accounts.
- OLE last-saved-by unchanged in 44% of 3,879 files (full corpus); Inventor property sets (author, design-tracking, control) only about 1/3 replaced;
  the same account also stays in other streams (sample: 60 of 142 OLE files with a field identity kept it in other streams = "cross-stream residue").
- Visible PDF text: non-public domains still present in 51 of 86 sampled PDFs with one (bare host names without http/www and mixed-case spellings
  were never detected); e-mail 3 of 24 left; person names in text were never detected (about 6 percent of PDFs contain a "First Last" name).
- PDF Title left unchanged in 92% (it mirrors the file name in 55%, deliberately left).
- Registry is small (4,832 identities) and has a few ordinary words from folder names (plural words) that get replaced inside drawings.
- Collisions: pseudonyms in the first run are collision free for registry entries; same pseudonym never given to 2 identities (0 colliding in the field scan).
  Cause for "non-collision triplets 0/100" NOT found; best hypothesis: the identities in those checks are mostly among the ones we left untouched.
- 6 PDFs lost pages through the overlay pass (verify: page-count) - fixed by reverting to the non-overlay version.
- Not touched: logos as images, part/drawing numbers, Title/Subject, non-ASCII names inside OLE non-property streams, STEP headers (33 of 42 with a real
  author/org already clean).

## Fixes done (commits on fix1)
1. 3472e29 field-level identities for PDF + OLE (deid/fields.py, perfile.py, registry.meta_pseudonym, Chain matcher, OLE read-once/write-once).
   Target: OLE saved-account, OLE cross-stream residue, PDF scoped removal, cross-PDF consistency.
   Sample before -> after: OLE files with all identity fields replaced 63 -> 142 of 142; OLE files with the account still in other streams 60 -> 3;
   PDF files with all author-style fields replaced 143 -> 183 of 186; PDF residue of field values elsewhere 28 -> 4. verify.py usability: 0 failures on 450 files.
2. 28b253b per-file text identities in PDFs: e-mail, domain (also bare / mixed case), phone, copyright holder, person names (name lists in
   data/first_names.txt.gz, last_names.txt.gz, public lists); harvest-meta stage in run.py; overlay keeps page count; public domains list extended;
   generic folder-name words (core.NEVER_IN_CONTENT) no longer replaced inside content.
   Sample: PDFs with non-public domain left 51 -> 9 of 80; words missing from visible text 1988 -> 1777 of 357,830.
- Uncommitted/in progress: nothing except this file.

## Milestone status
- M1 (no re-harvest): the current head works with the existing registry + seed (read-only registry returns the deterministic first candidate for new
  identities). Expect about 1% of new field pseudonyms to collide with each other (10 of 1,015 in a metadata scan). Safe on sample (usability checks pass);
  NOT yet run on the whole corpus; PDF apply is slower (about 2x, extra text pass).
- M2 (collision-free, same pseudonym in raw files too): `run.py harvest-meta` (new, resumable, PDF/OLE and those inside zip/gz only).
  Tested on 439 files with 4 procs: 12 s (registry 4,832 -> 5,063). Estimated full run 15-40 min on this Mac (21k top-level files + zip members).

## Exact commands (private paths, run on the Mac)
  M1 only: pack registry unchanged (cloud/registry.enc is already current), run cloud apply as in cloud/README.md (new code ref = fix1 head).
  M2:
    cd /Users/nico/Developer/vcv-wt/mac-fix/pipeline
    /Volumes/vcvmachina/work/venv/bin/python -W ignore run.py harvest-meta --procs 6     # writes /Volumes/vcvmachina/work/registry.sqlite (back it up first with sqlite3 .backup)
    bash ../cloud/pack_registry.sh <passphrase file> ../cloud/registry.enc; commit + push; cloud apply (about 10 min)
  Do not use ledger/registry of the live run for tests; work copies are under /Volumes/vcvmachina/work/fixtest/.

## Next, in priority order
1. DONE: both samples re-run with head, verify clean (0 failures on 450 files); M2 registry copy (fixtest/m2work, harvest-meta on the sample only) also applies cleanly (out_m2/).
2. Run harvest-meta on the whole corpus when the architect decides (M2).
3. Non-ASCII field values in OLE non-property streams; label-based names in title blocks; pdf overlay cap of 80 pages; Title/Subject policy; logos.
4. Pseudonym quality (digit tails like "Bo Fo8" for colliding person names; very long first names for composite accounts).

## Where things are (all private, under /Volumes/vcvmachina/work/fixtest/)
  diag/sample.json (sample list), diag/sample scripts: runsample_mp.py (apply sample), evalpdf.py, evalole.py, runverify.py, scanmeta.py (full metadata scan -> meta_all.pkl),
  out/ (sample outputs, delete when done), registry.sqlite + ledger.sqlite (copies), m2work/ (copy with harvest-meta applied to the sample only), pipx/ (faker, only used to build name lists once).
  New outputs for the sample: diag/new_pdf.json / new_ole.json. Old output for comparison: /Volumes/vcvmachina/out/attempt-1/corpus.
Notes: pip was used once (faker into a throwaway --target dir) only to build the name lists; no new runtime dependency.
