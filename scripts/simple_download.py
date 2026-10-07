#!/usr/bin/env python3
"""simple_download.py — dead-simple one-shot puller for jobs already DONE on Databento.

No submitter, no continuous scheduler, no polling loop, no verify — just:
  1. list which of our manifest jobs are 'done' on Databento right now,
  2. download each (resumable) with a small worker pool,
  3. update the manifest, exit.

Written because the full `run` continuous scheduler keeps stalling under HDD
contention. This has nothing to stall ON. Re-run it to pick up jobs that finish
later. Usage:  DATABENTO_API_KEY=... python scripts/simple_download.py [--workers 8]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import databento_massive_download as D  # reuse the proven helpers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    client = D._client()
    manifest = D.Manifest(D.DEFAULT_ROOT / D.MANIFEST_NAME)
    manifest.load()

    print("listing live job states from Databento...", flush=True)
    job_map = D._build_job_map(client)            # {job_id: info}
    print(f"  {len(job_map)} jobs known to Databento", flush=True)

    pending = [e for e in manifest.entries.values()
               if e.job_id and e.state != "downloaded"]
    done = [e for e in pending
            if (job_map.get(e.job_id) or {}).get("state") == "done"]

    # PRIORITY: pull the small, high-value book schemas first (options-feature data),
    # then everything else smallest-first. Defers the giant bbo-1s ALL_SYMBOLS files
    # (~400 GB each) so they don't block the data we need now.
    PRI = {"mbo": 0, "mbp-10": 0, "mbp-1": 0, "tbbo": 1, "trades": 1,
           "definition": 1, "statistics": 1, "status": 1, "ohlcv-1s": 1,
           "bbo-1m": 2, "bbo-1s": 3}

    def _sz(e):
        return int((job_map.get(e.job_id) or {}).get("actual_size") or 0)

    done.sort(key=lambda e: (PRI.get(e.schema, 2), _sz(e)))
    from collections import Counter
    print(f"{len(pending)} not-downloaded jobs; {len(done)} DONE and pullable now",
          flush=True)
    print(f"  priority order by schema: {dict(Counter(e.schema for e in done))}", flush=True)
    if not done:
        print("nothing ready to pull.")
        return 0

    lock = threading.Lock()
    counter = {"ok": 0, "err": 0, "n": len(done)}
    t0 = time.time()

    def pull(e):
        try:
            job_dir = D.DEFAULT_ROOT / e.schema / e.job_id
            files = D._download_job_resumable(client, e.job_id, job_dir, False)  # verify=False
            with lock:
                e.files = files
                e.state = "downloaded"
                e.last_state = "done"
                manifest.save()
                counter["ok"] += 1
                done_n = counter["ok"] + counter["err"]
            print(f"  [{done_n}/{counter['n']}] OK {e.schema} {e.start} "
                  f"({len(files)} files, {time.time()-t0:.0f}s elapsed)", flush=True)
        except Exception as ex:
            with lock:
                e.error = str(ex)
                manifest.save()
                counter["err"] += 1
                done_n = counter["ok"] + counter["err"]
            print(f"  [{done_n}/{counter['n']}] ERR {e.schema} {e.start}: {ex}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(pull, done))

    print(f"\nDONE: {counter['ok']} downloaded, {counter['err']} errors, "
          f"{time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
