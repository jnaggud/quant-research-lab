#!/usr/bin/env python3
"""
Databento massive downloader for the CME Globex MDP 3.0 (GLBX.MDP3) dataset.

Downloads every schema available to a Standard subscription, scoped to the
included date windows (no metered/pay-as-you-go usage):

  - L0 (16+ years):  definition, statistics, status, ohlcv-1s/1m/1h/1d
  - L1 (12 months):  mbp-1, tbbo, bbo-1s, bbo-1m, trades
  - L2 (1 month):    mbp-10
  - L3 (1 month):    mbo

Architecture
------------
* Submits Databento Batch API jobs (one per (schema, date-chunk)).
* Persists a manifest at <root>/manifest.json with each job's id, range, state,
  downloaded files, and SHA-256 verification status.
* Resume-safe: re-running the same subcommand picks up where it left off.

Subcommands
-----------
  preflight  Estimate cost for every planned job (sanity check; should be ~$0
             for the included windows). Does not submit.
  submit     Submit any not-yet-submitted jobs and record job_id in manifest.
  download   Poll Databento for finished jobs and download their files,
             verifying SHA-256 checksums. Idempotent / resumable.
  status     Print a summary of the manifest.
  run        submit then download in a loop until all jobs complete.

Usage
-----
  export DATABENTO_API_KEY=$(cat ~/.databento/key)
  python databento_massive_download.py preflight
  python databento_massive_download.py run
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field

import requests
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import databento as db


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

DATASET = "GLBX.MDP3"
DEFAULT_ROOT = Path(os.getenv("DATABENTO_ROOT", "data/databento"))
MANIFEST_NAME = "manifest.json"
LOG_NAME = "downloader.log"

# Entitlement windows for the Standard tier on GLBX.MDP3 (per Databento docs):
#   L0 schemas:     full available history (~16y)
#   L1 schemas:     trailing 12 months
#   L2 (mbp-10):    trailing 1 month
#   L3 (mbo):       trailing 1 month
#
# Buffer the trailing windows by 1 day to stay comfortably inside entitlement.
DAYS_L1 = 365 - 1
DAYS_L2 = 30 - 1
DAYS_L3 = 30 - 1

# Chunking strategy per schema. Smaller chunks = more robustness/parallelism
# but more job overhead. Tuned for ALL_SYMBOLS jobs on GLBX.MDP3.
CHUNK_YEAR = "year"
CHUNK_MONTH = "month"
CHUNK_DAY = "day"

# (schema, window_kind, chunk_kind)
SCHEMA_PLAN = [
    # ---- L0 schemas: full ~16y history --------------------------------------
    ("definition",  "full", CHUNK_YEAR),
    ("status",      "full", CHUNK_YEAR),
    ("statistics",  "full", CHUNK_YEAR),
    ("ohlcv-1d",    "full", CHUNK_YEAR),
    ("ohlcv-1h",    "full", CHUNK_YEAR),
    ("ohlcv-1m",    "full", CHUNK_YEAR),
    ("ohlcv-1s",    "full", CHUNK_MONTH),
    # ---- L1 schemas: trailing 12 months -------------------------------------
    ("mbp-1",       "l1",   CHUNK_MONTH),
    ("tbbo",        "l1",   CHUNK_MONTH),
    ("bbo-1s",      "l1",   CHUNK_MONTH),
    ("bbo-1m",      "l1",   CHUNK_MONTH),
    ("trades",      "l1",   CHUNK_MONTH),
    # ---- L2 / L3: trailing 1 month ------------------------------------------
    ("mbp-10",      "l2",   CHUNK_DAY),
    ("mbo",         "l3",   CHUNK_DAY),
]

# Batch job defaults. dbn + zstd = smallest on-disk footprint.
JOB_DEFAULTS = dict(
    encoding="dbn",
    compression="zstd",
    split_duration="day",   # one .dbn.zst file per UTC day per job (mirror's choice)
)

# --------------------------------------------------------------------------------------
# Symbol scope
# --------------------------------------------------------------------------------------
# "Maximal" plan: keep ALL_SYMBOLS for the cheap/wide schemas, but for the heavy
# book schemas (which are dominated by options quote traffic) restrict to the
# major futures roots PLUS their options, via parent symbology. This turns a
# ~78 TB ALL_SYMBOLS pull into ~14 TB while keeping full book depth on the
# instruments that matter.
MAJOR_ROOTS = [
    # equity index
    "ES", "NQ", "YM", "RTY",
    # rates / bonds (Treasury + short-rate futures)
    "ZT", "ZF", "ZN", "TN", "ZB", "UB", "SR3", "ZQ",
    # fx
    "6E", "6J", "6B", "6A", "6C", "6S", "6M", "6N",
    # energy
    "CL", "NG", "RB", "HO", "BZ",
    # metals
    "GC", "SI", "HG", "PL", "PA",
    # grains / ags
    "ZC", "ZS", "ZW", "ZL", "ZM", "ZO", "ZR", "KE",
    # livestock
    "LE", "HE", "GF",
    # crypto
    "BTC", "ETH",
]

# Schemas restricted to MAJOR_ROOTS (.FUT + .OPT via parent symbology). Everything
# else uses ALL_SYMBOLS / raw_symbol.
SCOPED_SCHEMAS = {"mbp-1", "mbp-10", "mbo"}


def _symbols_for(schema: str) -> tuple[object, str]:
    """Return (symbols, stype_in) for a schema under the Maximal plan."""
    if schema in SCOPED_SCHEMAS:
        syms = [r + ".FUT" for r in MAJOR_ROOTS] + [r + ".OPT" for r in MAJOR_ROOTS]
        return syms, "parent"
    return "ALL_SYMBOLS", "raw_symbol"


# --------------------------------------------------------------------------------------
# Manifest model
# --------------------------------------------------------------------------------------

@dataclass
class JobEntry:
    key: str                  # stable id: f"{schema}|{start}|{end}"
    schema: str
    start: str                # ISO date (UTC midnight)
    end: str                  # ISO date (UTC midnight, exclusive)
    chunk_kind: str
    job_id: str | None = None
    state: str = "planned"    # planned | submitted | done | downloaded | error
    files: list[dict] = field(default_factory=list)
    cost_usd: float | None = None
    cost_currency: str | None = None
    submitted_at: str | None = None
    last_state: str | None = None
    last_state_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "JobEntry":
        return cls(**d)


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, JobEntry] = {}
        self._loaded_mtime: float | None = None

    def load(self) -> None:
        if not self.path.exists():
            self.entries = {}
            return
        with self.path.open("r") as f:
            data = json.load(f)
        self.entries = {k: JobEntry.from_dict(v) for k, v in data.get("jobs", {}).items()}
        self._loaded_mtime = self.path.stat().st_mtime

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(
                {
                    "dataset": DATASET,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "jobs": {k: v.to_dict() for k, v in self.entries.items()},
                },
                f,
                indent=2,
                sort_keys=True,
            )
        os.replace(tmp, self.path)

    def upsert(self, entry: JobEntry) -> None:
        existing = self.entries.get(entry.key)
        if existing:
            # Don't downgrade state; only fill in missing fields.
            for k, v in entry.to_dict().items():
                if getattr(existing, k) in (None, "", [], "planned"):
                    setattr(existing, k, v)
        else:
            self.entries[entry.key] = entry


# --------------------------------------------------------------------------------------
# Date chunking
# --------------------------------------------------------------------------------------

def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _window_bounds(rng: dict, schema: str, kind: str) -> tuple[date, date]:
    """Return [start, end) bounds for this schema, respecting plan entitlements.

    `rng` is the dict returned by get_dataset_range(dataset=...) — per-schema
    ranges live under rng['schema'][schema]; falls back to dataset-level keys.
    """
    schema_rng = rng.get("schema", {}).get(schema, rng)
    # Job boundaries are day-granular; take the YYYY-MM-DD prefix. This sidesteps
    # Python 3.10's fromisoformat() rejecting 9-digit (nanosecond) fractional
    # seconds. The downloaded DBN data keeps full int64-nanosecond precision —
    # this parsing only affects which calendar days each batch job covers.
    ds_start = date.fromisoformat(schema_rng["start"][:10])
    ds_end = date.fromisoformat(schema_rng["end"][:10])
    today = _utc_today()
    end = min(ds_end, today)
    if kind == "full":
        start = ds_start
    elif kind == "l1":
        start = today - timedelta(days=DAYS_L1)
    elif kind == "l2":
        start = today - timedelta(days=DAYS_L2)
    elif kind == "l3":
        start = today - timedelta(days=DAYS_L3)
    else:
        raise ValueError(f"unknown window kind: {kind}")
    start = max(start, ds_start)
    return start, end


def _chunk_dates(start: date, end: date, kind: str) -> Iterable[tuple[date, date]]:
    """Yield (chunk_start, chunk_end) where end is exclusive."""
    cur = start
    while cur < end:
        if kind == CHUNK_DAY:
            nxt = cur + timedelta(days=1)
        elif kind == CHUNK_MONTH:
            # first of next month
            if cur.month == 12:
                nxt = date(cur.year + 1, 1, 1)
            else:
                nxt = date(cur.year, cur.month + 1, 1)
            # align cur to first of month for cleaner chunking, except for first chunk
            if cur.day != 1 and cur == start:
                # leave cur as-is so we cover the partial month from the dataset start
                pass
        elif kind == CHUNK_YEAR:
            nxt = date(cur.year + 1, 1, 1)
            if cur.month != 1 or cur.day != 1:
                # partial first year
                pass
        else:
            raise ValueError(f"unknown chunk kind: {kind}")
        if nxt > end:
            nxt = end
        yield cur, nxt
        cur = nxt


def plan_jobs(client: db.Historical) -> list[JobEntry]:
    """Build the full list of planned jobs from SCHEMA_PLAN."""
    rng = _api_call(client.metadata.get_dataset_range, dataset=DATASET)
    jobs: list[JobEntry] = []
    for schema, window_kind, chunk_kind in SCHEMA_PLAN:
        try:
            start, end = _window_bounds(rng, schema, window_kind)
        except Exception as e:
            logging.warning("Skipping %s: cannot resolve window: %s", schema, e)
            continue
        for cs, ce in _chunk_dates(start, end, chunk_kind):
            key = f"{schema}|{cs.isoformat()}|{ce.isoformat()}"
            jobs.append(JobEntry(
                key=key,
                schema=schema,
                start=cs.isoformat(),
                end=ce.isoformat(),
                chunk_kind=chunk_kind,
            ))
    return jobs


# --------------------------------------------------------------------------------------
# Databento helpers
# --------------------------------------------------------------------------------------

# Resolved once in _client(); used by the resumable downloader for HTTP basic auth
# against batch file URLs (Databento uses the API key as the basic-auth username).
_API_KEY: str | None = None


def _client() -> db.Historical:
    global _API_KEY
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        key_file = Path.home() / ".databento" / "key"
        if key_file.exists():
            key = key_file.read_text().strip()
    if not key:
        raise SystemExit("DATABENTO_API_KEY not set and ~/.databento/key not found")
    _API_KEY = key
    return db.Historical(key)


def _estimate_cost(client: db.Historical, entry: JobEntry) -> tuple[float, str]:
    """Best-effort cost estimate. Returns (amount, currency)."""
    symbols, stype_in = _symbols_for(entry.schema)
    res = _api_call(
        client.metadata.get_cost,
        dataset=DATASET,
        symbols=symbols,
        schema=entry.schema,
        start=entry.start,
        end=entry.end,
        stype_in=stype_in,
    )
    # API may return a float or a dict depending on SDK version.
    if isinstance(res, dict):
        amount = float(res.get("cost") or res.get("amount") or 0.0)
        currency = res.get("currency", "USD")
    else:
        amount = float(res)
        currency = "USD"
    return amount, currency


def _submit_job(client: db.Historical, entry: JobEntry) -> dict:
    symbols, stype_in = _symbols_for(entry.schema)
    return client.batch.submit_job(
        dataset=DATASET,
        symbols=symbols,
        schema=entry.schema,
        start=entry.start,
        end=entry.end,
        stype_in=stype_in,
        **JOB_DEFAULTS,
    )


def _build_job_map(client: db.Historical) -> dict[str, dict]:
    """Return {job_id: job_info_dict} for all known batch jobs.

    Uses list_jobs (the correct method in databento 0.69.x; get_job does not
    exist). Iterates over each state string individually because some SDK
    versions only accept a single state value per call.
    """
    all_states = ("received", "queued", "processing", "done", "expired", "failed")
    job_map: dict[str, dict] = {}
    for state in all_states:
        try:
            jobs = _api_call(client.batch.list_jobs, states=state)
        except Exception:
            continue
        for job in (jobs or []):
            if isinstance(job, dict):
                jid = job.get("id")
                info = job
            else:
                jid = getattr(job, "id", None)
                info = vars(job) if hasattr(job, "__dict__") else {}
                info.setdefault("id", jid)
            if jid:
                job_map[jid] = info
    return job_map


# --------------------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------------------

def cmd_preflight(args: argparse.Namespace) -> int:
    client = _client()
    manifest = Manifest(args.root / MANIFEST_NAME)
    manifest.load()
    planned = plan_jobs(client)
    for entry in planned:
        manifest.upsert(entry)

    print(f"Planned {len(planned)} batch jobs.")
    by_schema: dict[str, int] = {}
    for e in planned:
        by_schema[e.schema] = by_schema.get(e.schema, 0) + 1
    for s, n in sorted(by_schema.items()):
        print(f"  {s:>12}: {n:>4} jobs")

    if args.no_cost:
        manifest.save()
        return 0

    print("\nEstimating costs (this can take a few minutes)...")
    total = 0.0
    nonzero: list[tuple[str, float]] = []
    for i, entry in enumerate(planned, 1):
        if entry.cost_usd is not None:
            cost = entry.cost_usd
        else:
            try:
                cost, currency = _estimate_cost(client, entry)
                entry.cost_usd = cost
                entry.cost_currency = currency
                manifest.upsert(entry)
            except Exception as e:
                logging.warning("Cost estimate failed for %s: %s", entry.key, e)
                continue
        total += cost
        if cost > 0:
            nonzero.append((entry.key, cost))
        if i % 25 == 0:
            print(f"  ...estimated {i}/{len(planned)} jobs; running total ${total:.4f}")
            manifest.save()

    manifest.save()
    print(f"\nTotal estimated cost: ${total:.4f} USD across {len(planned)} jobs.")
    if nonzero:
        print(f"WARNING: {len(nonzero)} jobs have non-zero cost. First 10:")
        for k, c in nonzero[:10]:
            print(f"  ${c:>10.4f}  {k}")
    else:
        print("All jobs estimated at $0 — within Standard subscription entitlement.")
    return 0


_RETRY_AFTER_RE = re.compile(r"retry in (\d+)\s*s", re.IGNORECASE)


def _retry_after_seconds(msg: str, default: int = 30) -> int:
    """Pull the server's 'Retry in Ns' hint out of a 429 message."""
    m = _RETRY_AFTER_RE.search(msg or "")
    return int(m.group(1)) if m else default


def _api_call(fn, *args, _retries: int = 8, **kwargs):
    """Central wrapper for EVERY Databento API request, so all calls respect
    rate limits uniformly.

    On HTTP 429 we sleep for the server-provided 'Retry in Ns' interval (capped,
    + buffer) and retry — this is the authoritative way to respect the limit,
    since the server tells us exactly how long to back off. Other transient
    errors get linear backoff. Re-raises the last error once retries run out.
    """
    last_err = None
    for attempt in range(_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt >= _retries - 1:
                break
            msg = str(e)
            if "429" in msg or "Too Many" in msg:
                time.sleep(min(90, _retry_after_seconds(msg, 30) + 2))
            else:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _submit_one(client, manifest, lock, entry) -> tuple[bool, str | None]:
    """Submit one job in a worker thread via the rate-limit-aware _api_call.

    The network call runs off-lock; only the manifest mutation is locked.
    `entry` is the live object in manifest.entries, so mutating it updates the
    manifest directly."""
    try:
        resp = _api_call(_submit_job, client, entry)
        with lock:
            entry.job_id = resp["id"]
            entry.state = "submitted"
            entry.submitted_at = datetime.now(timezone.utc).isoformat()
            entry.error = None
        return True, None
    except Exception as e:
        with lock:
            entry.error = str(e)
            entry.state = "error"
        return False, str(e)


def cmd_submit(args: argparse.Namespace) -> int:
    client = _client()
    manifest = Manifest(args.root / MANIFEST_NAME)
    manifest.load()
    planned = plan_jobs(client)
    for entry in planned:
        manifest.upsert(entry)

    # Requeue jobs that failed during submission (no job_id) — these are
    # transient 429s, not real failures. Errors WITH a job_id are download-side
    # and left alone.
    requeued = 0
    for e in manifest.entries.values():
        if e.state == "error" and not e.job_id:
            e.state = "planned"
            e.error = None
            requeued += 1
    if requeued:
        print(f"Requeued {requeued} previously failed submissions.")
    manifest.save()

    to_submit = [e for e in manifest.entries.values() if e.state == "planned"]
    if args.limit:
        to_submit = to_submit[:args.limit]
    # Submission is server-rate-limited; keep concurrency modest (distinct from
    # the download --workers). Workers honor the 429 Retry-After hint.
    workers = max(1, getattr(args, "submit_workers", 0) or 4)
    total = len(to_submit)
    print(f"{total} jobs to submit (submit-workers={workers}, {len(manifest.entries)} total in manifest).")

    lock = threading.Lock()
    done = 0
    rc = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_submit_one, client, manifest, lock, e): e
                   for e in to_submit}
        for fut in concurrent.futures.as_completed(futures):
            entry = futures[fut]
            ok, err = fut.result()
            done += 1
            if ok:
                print(f"  [{done}/{total}] submitted {entry.schema} {entry.start}..{entry.end} -> {entry.job_id}")
            else:
                print(f"  [{done}/{total}] ERROR submitting {entry.key}: {err}")
                if args.stop_on_error:
                    rc = 1
            # Persist periodically; the lock serializes the atomic save.
            if done % 20 == 0:
                with lock:
                    manifest.save()

    with lock:
        manifest.save()
    return rc


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_file_resumable(url: str, dest: Path, expected_size: int,
                             expected_hash: str | None = None,
                             verify: bool = False,
                             max_attempts: int = 12,
                             chunk: int = 8 * 1024 * 1024) -> dict:
    """Download one file with HTTP Range resume.

    The fragile part of large batch files is that a dropped connection makes the
    SDK restart from byte 0. Here, on any interruption we re-request with
    `Range: bytes=<have>-` and APPEND, so a 22 GB file that breaks at 18 GB
    resumes from 18 GB instead of starting over. Bounded attempts guarantee the
    call returns (success or raise) rather than looping forever — so it can
    never block the download pass the way the old whole-zip download did.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    success = False
    for attempt in range(max_attempts):
        have = dest.stat().st_size if dest.exists() else 0
        if expected_size and have == expected_size:
            success = True
            break
        if expected_size and have > expected_size:
            dest.unlink()  # overshoot => corrupt partial, restart clean
            have = 0
        headers = {}
        mode = "wb"
        if have > 0:
            headers["Range"] = f"bytes={have}-"
            mode = "ab"
        try:
            with requests.get(url, headers=headers, auth=(_API_KEY or "", ""),
                              stream=True, timeout=(30, 300)) as r:
                # If we asked to resume but the server sends 200 (full body), it
                # ignored Range — overwrite from scratch to avoid duplicate bytes.
                if have > 0 and r.status_code == 200:
                    mode = "wb"
                r.raise_for_status()
                with open(dest, mode) as f:
                    for block in r.iter_content(chunk_size=chunk):
                        if block:
                            f.write(block)
            if not expected_size or dest.stat().st_size == expected_size:
                success = True
                break
            last_err = f"size mismatch {dest.stat().st_size}/{expected_size}"
        except Exception as e:
            last_err = str(e)
        time.sleep(min(30, 2 * (attempt + 1)))

    if not success:
        have = dest.stat().st_size if dest.exists() else 0
        raise RuntimeError(f"download failed after {max_attempts} attempts "
                           f"({have}/{expected_size} bytes): {dest.name}: {last_err}")

    rec = {"path": str(dest), "size": dest.stat().st_size, "sha256": None}
    if verify:
        digest = _sha256(dest)
        rec["sha256"] = digest
        if expected_hash:
            exp = expected_hash.split(":", 1)[-1]
            if digest != exp:
                raise RuntimeError(f"sha256 mismatch for {dest.name}: {digest} != {exp}")
    return rec


def _download_job_resumable(client, job_id: str, job_dir: Path, verify: bool) -> list[dict]:
    """Download every file of a batch job individually, with resume. Files that
    are already complete on disk (matching size) are skipped, so re-runs and
    inner retries are cheap."""
    files = _api_call(client.batch.list_files, job_id)
    recs = []
    for finfo in files:
        fn = finfo.get("filename")
        url = (finfo.get("urls") or {}).get("https")
        if not fn or not url:
            continue
        size = int(finfo.get("size") or 0)
        rec = _download_file_resumable(
            url, job_dir / fn, size,
            expected_hash=finfo.get("hash"), verify=verify,
        )
        recs.append(rec)
    return recs


def _download_one(client, args, manifest, lock, entry, idx, total, job_map) -> str:
    """Process a single pending job: check state, and if done download + verify.

    Runs in a worker thread. The slow parts — network download and SHA-256
    hashing — happen OUTSIDE the lock so all workers proceed concurrently; the
    lock is held only for the (fast) manifest mutation + atomic save. `entry`
    is the live object inside manifest.entries, so mutating it updates the
    manifest directly. Raises only when --stop-on-error is set.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        info = job_map.get(entry.job_id, {})
        state = info.get("state") if isinstance(info, dict) else getattr(info, "state", None)

        if state is None:
            with lock:
                entry.last_state = "unknown"
                entry.last_state_at = now
            return f"[{idx}/{total}] {entry.job_id} {entry.schema} -> not found in job list (waiting)"

        if state in ("received", "queued", "processing"):
            with lock:
                entry.last_state = state
                entry.last_state_at = now
            return f"[{idx}/{total}] {entry.job_id} {entry.schema} -> {state} (waiting)"

        if state != "done":
            with lock:
                entry.last_state = state
                entry.last_state_at = now
                entry.error = f"unexpected state: {state}"
                entry.state = "error"
                manifest.save()
            return f"[{idx}/{total}] {entry.job_id} {entry.schema} -> {state} (error)"

        # state == "done": download each file with resume (network I/O) + verify
        # (CPU) without the lock. Files land in <root>/<schema>/<job_id>/.
        job_dir = args.root / entry.schema / entry.job_id
        files = _download_job_resumable(client, entry.job_id, job_dir, args.verify)
        with lock:
            entry.last_state = state
            entry.last_state_at = now
            entry.files = files
            entry.state = "downloaded"
            manifest.save()
        return f"[{idx}/{total}] downloaded {entry.job_id} {entry.schema} ({len(files)} files)"
    except Exception as e:
        # Keep job_id so a later pass / re-run resumes from the partial file
        # instead of restarting. State -> error ends this pass without blocking.
        with lock:
            entry.error = str(e)
            entry.state = "error"
            manifest.save()
        if args.stop_on_error:
            raise
        return f"[{idx}/{total}] ERROR for {entry.key}: {e}"


def cmd_download(args: argparse.Namespace) -> int:
    client = _client()
    manifest = Manifest(args.root / MANIFEST_NAME)
    manifest.load()

    pending = [e for e in manifest.entries.values()
               if e.job_id and e.state not in ("downloaded",)]
    workers = max(1, getattr(args, "workers", 0) or (os.cpu_count() or 8))
    total = len(pending)
    print(f"{total} jobs to check/download (workers={workers}).")

    # Bulk-fetch all job states once (list_jobs is the correct API in 0.69.x).
    job_map = _build_job_map(client)
    lock = threading.Lock()
    rc = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download_one, client, args, manifest, lock,
                        entry, i, total, job_map): entry
            for i, entry in enumerate(pending, 1)
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                print(f"  {fut.result()}")
            except Exception as e:
                # Only reached when --stop-on-error caused a worker to re-raise.
                print(f"  worker aborted: {e}")
                rc = 1

    with lock:
        manifest.save()
    return rc


def cmd_status(args: argparse.Namespace) -> int:
    manifest = Manifest(args.root / MANIFEST_NAME)
    manifest.load()
    by_state: dict[str, int] = {}
    by_schema_state: dict[tuple[str, str], int] = {}
    total_bytes = 0
    for e in manifest.entries.values():
        by_state[e.state] = by_state.get(e.state, 0) + 1
        by_schema_state[(e.schema, e.state)] = by_schema_state.get((e.schema, e.state), 0) + 1
        for f in e.files:
            total_bytes += int(f.get("size") or 0)
    print(f"Manifest: {manifest.path}")
    print(f"Total jobs: {len(manifest.entries)}")
    for s, n in sorted(by_state.items()):
        print(f"  {s:>12}: {n}")
    print(f"On-disk bytes: {total_bytes/1e9:,.2f} GB")
    print("\nBy schema:")
    schemas = sorted({s for s, _ in by_schema_state})
    for s in schemas:
        line = f"  {s:>12}: "
        for st in ("planned", "submitted", "done", "downloaded", "error"):
            n = by_schema_state.get((s, st), 0)
            if n:
                line += f"{st}={n} "
        print(line)
    return 0


_WAITING_STATES = (None, "unknown", "received", "queued", "processing")


def _submitter_thread(client, manifest, lock, submit_done, sub_workers, stop_on_error):
    """Background worker: submit every planned job (rate-limited), then signal.

    Shares `manifest` + `lock` with the downloader. _submit_one does its network
    call off-lock and mutates the manifest under the lock, so the two threads
    never corrupt each other's writes."""
    with lock:
        todo = [e for e in manifest.entries.values() if e.state == "planned"]
    print(f"[submitter] submitting {len(todo)} jobs (submit-workers={sub_workers})")
    n = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=sub_workers) as pool:
            futures = {pool.submit(_submit_one, client, manifest, lock, e): e for e in todo}
            for fut in concurrent.futures.as_completed(futures):
                entry = futures[fut]
                ok, err = fut.result()
                n += 1
                if not ok:
                    print(f"  [submit {n}/{len(todo)}] ERROR {entry.key}: {err}")
                    if stop_on_error:
                        break
                if n % 20 == 0:
                    with lock:
                        manifest.save()
                    print(f"[submitter] {n}/{len(todo)} submitted")
    finally:
        with lock:
            manifest.save()
        submit_done.set()
        print("[submitter] finished")


def cmd_run(args: argparse.Namespace) -> int:
    """Decoupled submit + download until everything is downloaded/errored.

    A background submitter thread queues all remaining jobs (rate-limited,
    --submit-workers) while the main thread continuously polls and downloads
    finished jobs (--workers). Neither blocks the other; they share one Manifest
    guarded by one lock (all mutations + saves happen under it, only the network
    I/O runs off-lock). This keeps submission progressing even while a long
    download/verify pass is in flight.
    """
    client = _client()
    manifest = Manifest(args.root / MANIFEST_NAME)
    manifest.load()
    planned = plan_jobs(client)
    for entry in planned:
        manifest.upsert(entry)
    # Requeue all errored jobs at the start of a run so each invocation retries:
    #   - submission failures (no job_id, e.g. 429s)     -> back to "planned"
    #   - download failures (have job_id)                -> back to "submitted",
    #     so the download pass retries them; the resumable downloader picks up
    #     from the partial file on disk rather than restarting.
    requeued_sub = requeued_dl = 0
    for e in manifest.entries.values():
        if e.state == "error":
            if e.job_id:
                e.state = "submitted"
                e.last_state = None
                requeued_dl += 1
            else:
                e.state = "planned"
                requeued_sub += 1
            e.error = None
    if requeued_sub or requeued_dl:
        print(f"Requeued {requeued_sub} failed submissions, {requeued_dl} failed downloads.")
    manifest.save()

    poll = args.poll_seconds
    sub_workers = max(1, getattr(args, "submit_workers", 0) or 4)
    dl_workers = max(1, getattr(args, "workers", 0) or (os.cpu_count() or 8))
    stop_on_error = getattr(args, "stop_on_error", False)
    lock = threading.Lock()
    submit_done = threading.Event()

    submitter = threading.Thread(
        target=_submitter_thread,
        args=(client, manifest, lock, submit_done, sub_workers, stop_on_error),
        daemon=True,
    )
    submitter.start()

    # Continuous downloader: a pool of persistent worker threads pulls jobs off a
    # shared queue, while the main thread polls Databento and enqueues each job
    # the moment it turns "done". Unlike a pass-based loop, a single huge file
    # (e.g. a 280 GB mbo day) NEVER leaves the other workers idle — they keep
    # draining the queue, and newly-ready jobs are picked up continuously.
    work_q: "queue.Queue" = queue.Queue()
    enqueued: set[str] = set()   # entry.key currently queued or downloading
    stop = threading.Event()

    def _download_worker():
        while not stop.is_set():
            try:
                entry = work_q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                job_dir = args.root / entry.schema / entry.job_id
                files = _download_job_resumable(client, entry.job_id, job_dir, args.verify)
                with lock:
                    entry.files = files
                    entry.state = "downloaded"
                    entry.last_state = "done"
                    entry.last_state_at = datetime.now(timezone.utc).isoformat()
                    manifest.save()
                print(f"  downloaded {entry.schema} {entry.start}..{entry.end} ({len(files)} files)")
            except Exception as ex:
                with lock:
                    entry.error = str(ex)
                    entry.state = "error"
                    manifest.save()
                print(f"  ERROR downloading {entry.key}: {ex}")
            finally:
                with lock:
                    enqueued.discard(entry.key)
                work_q.task_done()

    workers = [threading.Thread(target=_download_worker, daemon=True) for _ in range(dl_workers)]
    for w in workers:
        w.start()

    try:
        while True:
            job_map = _build_job_map(client)
            newly = 0
            with lock:
                for e in manifest.entries.values():
                    if e.state != "submitted" or not e.job_id or e.key in enqueued:
                        continue
                    st = job_map.get(e.job_id, {}).get("state")
                    e.last_state_at = datetime.now(timezone.utc).isoformat()
                    if st in ("expired", "purged"):
                        # Output is gone server-side; drop the job_id and mark
                        # error so the next run's requeue resubmits it fresh
                        # (and so this loop can still terminate).
                        e.state = "error"
                        e.job_id = None
                        e.last_state = st
                        e.error = f"batch job {st}; will resubmit on next run"
                        print(f"  {st.upper()} {e.schema} {e.start} — will resubmit next run")
                        continue
                    e.last_state = st or "unknown"
                    if st == "done":
                        enqueued.add(e.key)
                        work_q.put(e)
                        newly += 1
                planned_left = sum(1 for e in manifest.entries.values() if e.state == "planned")
                actionable = sum(1 for e in manifest.entries.values() if e.state == "submitted")
                manifest.save()

            if newly:
                print(f"[scheduler] enqueued {newly} ready jobs (queue depth ~{work_q.qsize()}, {actionable} not yet downloaded)")

            if submit_done.is_set() and planned_left == 0 and actionable == 0:
                print("All jobs accounted for.")
                break

            print(f"[scheduler] {planned_left} to submit, {actionable} awaiting download, {len(enqueued)} in flight; next poll {poll}s")
            time.sleep(poll)
    finally:
        work_q.join()
        stop.set()
        for w in workers:
            w.join(timeout=5)

    cmd_status(args)
    return 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                   help=f"Output root (default: {DEFAULT_ROOT})")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("preflight", help="Estimate cost of every planned job")
    sp.add_argument("--no-cost", action="store_true",
                    help="Skip the cost estimation; just plan jobs.")
    sp.set_defaults(func=cmd_preflight)

    cpu_default = os.cpu_count() or 8
    sp = sub.add_parser("submit", help="Submit planned jobs to the batch API")
    sp.add_argument("--limit", type=int, default=0,
                    help="Submit at most N new jobs this run (0 = unlimited)")
    sp.add_argument("--submit-workers", type=int, default=4,
                    help="Parallel submission threads (default: 4; kept low because "
                         "batch submission is rate-limited server-side)")
    sp.add_argument("--stop-on-error", action="store_true")
    sp.set_defaults(func=cmd_submit)
    sp = sub.add_parser("download", help="Poll & download finished jobs")
    sp.add_argument("--verify", action="store_true",
                    help="Compute SHA-256 of downloaded files (slow on multi-GB files)")
    sp.add_argument("--workers", type=int, default=cpu_default,
                    help=f"Parallel download/verify threads (default: {cpu_default} = all cores)")
    sp.add_argument("--stop-on-error", action="store_true")
    sp.set_defaults(func=cmd_download)

    sp = sub.add_parser("status", help="Print manifest summary")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("run", help="Interleaved submit + poll/download loop until done")
    sp.add_argument("--poll-seconds", type=int, default=120)
    sp.add_argument("--limit", type=int, default=0)
    sp.add_argument("--submit-batch", type=int, default=40,
                    help="Submit at most N new jobs per pass before each download pass (default: 40)")
    sp.add_argument("--submit-workers", type=int, default=4,
                    help="Parallel submission threads (default: 4; submission is rate-limited)")
    sp.add_argument("--verify", action="store_true")
    sp.add_argument("--workers", type=int, default=cpu_default,
                    help=f"Parallel download/verify threads (default: {cpu_default} = all cores)")
    sp.add_argument("--stop-on-error", action="store_true")
    sp.set_defaults(func=cmd_run)

    args = p.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(args.root / LOG_NAME),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
