#!/usr/bin/env python3
"""Count what is in the destination folder and compare with the manifest.   MACHINA_UPLOAD_TOKEN=... python3 cloud/count_bucket.py gs://B/teams/ID/attempt-2/ [expected=188722]
Prints counts only. Run it by hand after the shards finished (it uses the token, which the CI jobs never print)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kit"))
import upload
dest = sys.argv[1]
expected = int(sys.argv[2]) if len(sys.argv) > 2 else 188722
bucket, prefix = upload.parse_dest(dest)
have = upload.list_existing(bucket, prefix + "corpus/", upload.Tokens(os.environ["MACHINA_UPLOAD_TOKEN"].strip(), None))
n, size = len(have), sum(s for s, _ in have.values())
print(f"objects under corpus/: {n} ({size / 1e9:.2f} GB); expected files: {expected}; {'COMPLETE' if n == expected else 'MISSING ' + str(expected - n) if n < expected else 'EXTRA ' + str(n - expected)}")
sys.exit(0 if n == expected else 1)
