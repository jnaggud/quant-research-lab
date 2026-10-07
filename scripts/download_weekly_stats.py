#!/usr/bin/env python3
"""download_weekly_stats.py — statistics (open interest) for the ES WEEKLY option roots.

The main statistics download was scoped to the 43 major roots by parent symbology,
and ES.OPT = the quarterly root only — so weekly-root OI (E1A-E5D, EW, EW1-4) is
missing from disk (see reports/es_options_v2_research_20260707.md §0). This pulls
just those parents: tiny data, one batch job per year.

Cost-guarded: aborts before submitting if the summed estimate exceeds $1.
Self-contained manifest (does NOT touch the main manifest.json).

Usage: python3 scripts/download_weekly_stats.py            # submit+poll+download
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import databento as db

DATASET = "GLBX.MDP3"
ROOT = Path(os.getenv("DATABENTO_ROOT", "data/databento"))
OUTDIR = ROOT / "statistics-weekly"
MAN = OUTDIR / "manifest_weekly_stats.json"

WEEKLY_ROOTS = ([f"E{i}{c}" for i in range(1, 6) for c in "ABCD"] +
                ["EW", "EW1", "EW2", "EW3", "EW4"])
SYMS = [r + ".OPT" for r in WEEKLY_ROOTS]
YEARS = [("2021-01-01", "2022-01-01"), ("2022-01-01", "2023-01-01"),
         ("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01"),
         ("2025-01-01", "2026-01-01"), ("2026-01-01", "2026-06-29")]
COST_ABORT_USD = 1.0


def _client() -> db.Historical:
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        kf = Path.home() / ".databento" / "key"
        if kf.exists():
            key = kf.read_text().strip()
    if not key:
        raise SystemExit("no DATABENTO_API_KEY / ~/.databento/key")
    return db.Historical(key)


def _load():
    if MAN.exists():
        return json.loads(MAN.read_text())
    return {"jobs": {}}


def _save(m):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    MAN.write_text(json.dumps(m, indent=2))


def main():
    client = _client()
    m = _load()

    # 1. cost check (skip if already submitted)
    pending = [(s, e) for s, e in YEARS if f"{s}|{e}" not in m["jobs"]]
    if pending:
        total = 0.0
        for s, e in pending:
            try:
                c = client.metadata.get_cost(dataset=DATASET, symbols=SYMS,
                                             schema="statistics", start=s, end=e,
                                             stype_in="parent")
                amt = float(c.get("cost", c) if isinstance(c, dict) else c)
            except Exception as ex:
                print(f"  cost check {s[:4]}: error ({ex}); assuming $0 (subscription)")
                amt = 0.0
            total += amt
            print(f"  {s[:4]}: ${amt:.4f}")
        print(f"total estimated: ${total:.4f}")
        if total > COST_ABORT_USD:
            raise SystemExit(f"ABORT: estimated ${total:.2f} > ${COST_ABORT_USD} guard")

        # 2. submit
        for s, e in pending:
            job = client.batch.submit_job(dataset=DATASET, symbols=SYMS,
                                          schema="statistics", start=s, end=e,
                                          stype_in="parent", encoding="dbn",
                                          compression="zstd", split_duration="day")
            jid = job["id"] if isinstance(job, dict) else job.id
            m["jobs"][f"{s}|{e}"] = {"job_id": jid, "state": "submitted"}
            print(f"submitted {s[:4]} -> {jid}", flush=True)
            _save(m)

    # 3. poll + download
    while True:
        todo = {k: j for k, j in m["jobs"].items() if j["state"] != "downloaded"}
        if not todo:
            break
        done_states = {}
        for jl in client.batch.list_jobs():
            done_states[jl["id"]] = jl["state"]
        for k, j in todo.items():
            st = done_states.get(j["job_id"], "unknown")
            if st == "done":
                dest = OUTDIR / j["job_id"]
                print(f"downloading {k} -> {dest}", flush=True)
                client.batch.download(job_id=j["job_id"], output_dir=OUTDIR)
                j["state"] = "downloaded"
                _save(m)
            elif st in ("expired", "error"):
                j["state"] = st
                _save(m)
                print(f"JOB {j['job_id']} state={st} — giving up on {k}", flush=True)
        todo = {k: j for k, j in m["jobs"].items()
                if j["state"] not in ("downloaded", "expired", "error")}
        if not todo:
            break
        print(f"waiting on {len(todo)} jobs ...", flush=True)
        time.sleep(60)

    states = [j["state"] for j in m["jobs"].values()]
    print("FINAL:", {s: states.count(s) for s in set(states)})


if __name__ == "__main__":
    main()
