# Machina CAD De-ID pipeline (v1)

`run.py harvest` finds identities (pass 1), `run.py apply` rewrites every file (pass 2), `verify.py` checks the output,
`survey_report.py` writes `../SURVEY.md`, `make_attempt.py` assembles `attempt-N/code` and `attempt-N/README.txt`.
`tests/run_fixture.sh` runs the whole chain on a synthetic corpus. `tools/copy_unchanged.py` is an untested helper for
server-side copies between attempt folders. See `../SURVEY.md` for where identifiers live and `deid/` for the handlers:

* `registry.py` identity -> pseudonym (same length, deterministic from a private seed, collision-free)
* `matcher.py` Aho-Corasick replacement in ASCII/UTF-8/UTF-16LE with token-boundary rules
* `harvest.py`, `ident.py`, `detect.py` structured-field and conservative pattern detection with generic-word guards
* `rewrite.py` zip/tar/gzip/OLE/PDF/raw handlers, `core.py` path renaming, APFS clones, ledger

## Identity fields and per-file identities (fix1)

* `deid/fields.py` finds identity FIELD values: OLE property sets (SummaryInformation, DocumentSummaryInformation, Inventor's own sets;
  parsed so a value of any length can be patched in place) and PDF Info / XMP creator-style elements / annotation authors.
* `deid/perfile.py` turns them (plus e-mail addresses, domains, phone numbers, copyright holders and person names found in a PDF's own text,
  `deid/names.py`) into per-file pseudonyms. Fields are replaced whatever they look like; the rest of the file only when the value is specific
  (`fields.content_safe`). Pseudonyms come from `Registry.meta_pseudonym` (scope `meta`): one per case-insensitive value, same in every
  file and format; the read-only registry of a cloud shard returns the deterministic first candidate.
* `run.py harvest-meta` registers all of these for the whole corpus (PDF / OLE and the ones inside zip, gz) so the pseudonyms are collision free;
  it is optional for `apply` (without it the deterministic candidates are used) and cheap compared with `harvest`.
