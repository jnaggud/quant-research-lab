"""scope_bbo1s_to_majors.py — replace the 13 pending bbo-1s ALL_SYMBOLS jobs
(~5 TB, ~5 days) with bbo-1s scoped to the MAJOR FUTURES roots (.FUT, parent
symbology) — small, fast, the only bbo-1s we'd actually use.

For each pending bbo-1s manifest entry we submit a new scoped batch job and point
the entry at the new job_id (state -> submitted). The old ALL_SYMBOLS done jobs are
simply abandoned (they expire on Databento in ~7 days; we never download them).

Run with the keep-alive STOPPED so there's no manifest write race.
"""
import os
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from databento_massive_download import (DATASET, JOB_DEFAULTS, MAJOR_ROOTS,
                                        _api_call, _client)

MAN = os.path.join(os.getenv("DATABENTO_ROOT", "data/databento"), 'manifest.json')
SYMS = [r + ".FUT" for r in MAJOR_ROOTS]   # futures only — options quotes come from mbp-1


def main():
    client = _client()
    m = json.load(open(MAN))
    pending = {k: j for k, j in m["jobs"].items()
               if j.get("schema") == "bbo-1s" and j.get("state") != "downloaded"}
    print(f"{len(pending)} pending bbo-1s jobs to re-scope to {len(SYMS)} major .FUT roots")

    # one cost check to confirm $0 (within subscription)
    sample = next(iter(pending.values()))
    try:
        cost = _api_call(client.metadata.get_cost, dataset=DATASET, symbols=SYMS,
                         schema="bbo-1s", start=sample["start"][:10], end=sample["end"][:10],
                         stype_in="parent")
        camt = cost.get("cost") if isinstance(cost, dict) else cost
        print(f"  per-month scoped bbo-1s cost estimate: ${float(camt):.4f}")
    except Exception as e:
        print(f"  (cost check skipped: {e})")

    done = 0
    for k, j in sorted(pending.items(), key=lambda x: str(x[1]["start"])):
        resp = _api_call(client.batch.submit_job, dataset=DATASET, symbols=SYMS,
                         schema="bbo-1s", start=j["start"][:10], end=j["end"][:10],
                         stype_in="parent", **JOB_DEFAULTS)
        jid = resp["id"] if isinstance(resp, dict) else getattr(resp, "id", None)
        j["job_id"] = jid
        j["state"] = "submitted"
        j["symbols"] = SYMS
        j["files"] = []
        j["error"] = None
        done += 1
        print(f"  re-scoped {j['start'][:10]}..{j['end'][:10]} -> {jid}")

    json.dump(m, open(MAN, "w"), indent=2, default=str)
    print(f"done: re-scoped {done} bbo-1s jobs to majors; manifest saved.")
    print("new scoped jobs will process server-side (minutes-hours), then the keep-alive pulls them.")


if __name__ == "__main__":
    main()
