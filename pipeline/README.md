# Machina CAD De-ID pipeline (v1)

`run.py harvest` finds identities (pass 1), `run.py apply` rewrites every file (pass 2), `verify.py` checks the output,
`survey_report.py` writes `../SURVEY.md`, `make_attempt.py` assembles `attempt-N/code` and `attempt-N/README.txt`.
`tests/run_fixture.sh` runs the whole chain on a synthetic corpus. `tools/copy_unchanged.py` is an untested helper for
server-side copies between attempt folders. See `../SURVEY.md` for where identifiers live and `deid/` for the handlers:

* `registry.py` identity -> pseudonym (same length, deterministic from a private seed, collision-free)
* `matcher.py` Aho-Corasick replacement in ASCII/UTF-8/UTF-16LE with token-boundary rules
* `harvest.py`, `ident.py`, `detect.py` structured-field and conservative pattern detection with generic-word guards
* `rewrite.py` zip/tar/gzip/OLE/PDF/raw handlers, `core.py` path renaming, APFS clones, ledger
