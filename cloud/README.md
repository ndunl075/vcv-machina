# Cloud shards (apply stage on free Linux runners)

Each job takes one slice of the input manifest (`shards.json`: contiguous ranges of the path-sorted manifest, numbers only), downloads
those files from the public mirror, runs `pipeline/run.py apply` with the existing registry and seed, self-checks, uploads with
`kit/upload.py`, deletes everything and writes a small JSON result. Logs carry counts and timings only.

Files: `plan_shards.py`, `shards.json`, `run_shard.sh`, `shard_tool.py`, `shardlib.py`, `pack_registry.sh`, `registry.enc` (AES-256, passphrase
kept outside the repo), `job2.yml` (the workflow), `count_bucket.py`, `local_proof.sh` + `compare_out.py` (container test, no upload).

Decision for the 3 input files whose names macOS could not store: the cloud run writes them under the SAME legal names as attempt-1
(`DEID_LEGALIZE=1`: U+FFC9 and U+FFD0 become `_`), so the attempt README section 4 stays true and object names are plain valid UTF-8.

Names used below: public runner repo `PUB=ndunl075/scratch-notes-7`, private repo `ndunl075/vcv-machina`, branch `cloud`.

Note: attempt-1/corpus holds 188,719 files; the 3 unrepresentable files were never written there, so the cloud run is the first to produce them
(attempt-2 has 188,722 objects under `corpus/`). Rewritten PDFs differ from the Mac run only in the trailer `/ID` (qpdf makes a new random id on
every run); every other file is byte-identical.

## (a) Secrets and deploy key (already done; for reference)
```
gh repo deploy-key add KEY.pub -R ndunl075/vcv-machina -t runner-ro          # read-only (no --allow-write)
gh secret set MAC_SRC_KEY -R $PUB < KEY                                       # private half
gh secret set MAC_SRC_URL -R $PUB -b 'git@github.com:ndunl075/vcv-machina.git'
gh secret set MAC_REG_PASS -R $PUB < /Users/nico/Developer/vcv-data/machina-ci-keys/pass   # a trailing newline is ignored
gh secret set MACHINA_DEST -R $PUB -b 'gs://<bucket>/teams/<id>/attempt-2/'
gh secret set MACHINA_UPLOAD_TOKEN -R $PUB -b "$TOKEN"                        # last thing before launching: it lives 1 hour
```
`registry.enc` is committed on branch `cloud`; rebuild it (e.g. after a registry change) with
`bash cloud/pack_registry.sh /Users/nico/Developer/vcv-data/machina-ci-keys/pass cloud/registry.enc`, commit, push.

## (b) Put the workflow on the public repo (only this one file)
```
git clone git@github.com:ndunl075/scratch-notes-7.git /tmp/pub && cd /tmp/pub && mkdir -p .github/workflows
cp /Users/nico/Developer/vcv-wt/mac-cloud/cloud/job2.yml .github/workflows/job2.yml
git add .github/workflows/job2.yml && git commit -m "add batch workflow" && git push origin main
```

## (c) Run
Smoke test without upload (2 shards, ~10 min), then everything. `ref` may be a branch or a full commit id of the private repo.
```
gh workflow run job2.yml -R $PUB --ref main -f shards=0-1 -f upload=false -f ref=cloud
gh workflow run job2.yml -R $PUB --ref main -f shards=all -f upload=true  -f ref=cloud     # 59 shards, 20 at a time
```
Set `MACHINA_UPLOAD_TOKEN` right before the full run. If it expires mid-run, shards report `upload token expired`: set a new token and run
`-f shards=<those ids>`; a rerun is safe (the uploader skips files already there).

## (d) Collect and verify
```
RUN=$(gh run list -R $PUB -w job2.yml -L1 --json databaseId -q '.[0].databaseId'); gh run watch $RUN -R $PUB
gh run download $RUN -R $PUB -D /tmp/res                  # res-<id>/shard-<id>.json, counts only
python3 - <<'PY'
import glob, json
rs = [json.load(open(f)) for f in glob.glob("/tmp/res/*/*.json")]
print(len(rs), "shards; in", sum(r["files_in"] for r in rs), "out", sum(r["files_out"] for r in rs), "not clean:", [r["shard"] for r in rs if r["exit_code"] or r["failures"]])
PY
MACHINA_UPLOAD_TOKEN=$TOKEN python3 cloud/count_bucket.py gs://<bucket>/teams/<id>/attempt-2/      # expects 188722
```
The workflow's last job also prints the totals in the run log.

## (e) Code and README for attempt-2 (on the Mac, after the corpus is complete)
```
cd /Users/nico/Developer/vcv-wt/mac-cloud/pipeline
DEID_WORK=/Volumes/vcvmachina/work DEID_OUT=/Volumes/vcvmachina/out/attempt-2/corpus python3.12 make_attempt.py /Volumes/vcvmachina/out/attempt-2
MACHINA_UPLOAD_TOKEN=$TOKEN python3 ../kit/upload.py --dest gs://<bucket>/teams/<id>/attempt-2/ --code /Volumes/vcvmachina/out/attempt-2/code --readme /Volumes/vcvmachina/out/attempt-2/README.txt
```
(`make_attempt.py` reads the local ledger from the Mac run: the corpus is the same bytes, apart from the differences listed in the report of the byte comparison.)

## Local proof (no upload)
`bash cloud/local_proof.sh <shard-id> linux/arm64 <workdir> [plan.json]` runs `run_shard.sh` in `python:3.12-slim`, copies the output out and
compares it byte for byte with attempt-1.
