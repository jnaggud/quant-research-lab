#!/usr/bin/env python3
"""reconstruct_mbp1.py — reconstruct tick-level L1 (mbp-1) from the L2 book (mbp-10).

mbp-10 records carry the full top-10 book; levels[0] is the best bid/offer, so every
L1 (best bid/ask) change is present. We stream each mbp-10 daily file, take levels[0],
dedupe per instrument (emit only when the BBO actually changes = mbp-1 semantics), and
write a compact Parquet. Parallel across ALL cores; streaming + batched writes so the
20 GB files never blow memory.

SCOPE: mbp-10 (L2) is a 1-month entitlement, so this covers ~1 month. Historical L1 for
the other 11 months comes from bbo-1s (1s BBO) + tbbo (BBO at trades), already on disk.

Usage: python3 scripts/reconstruct_mbp1.py            # all mbp-10 files, all cores
       python3 scripts/reconstruct_mbp1.py 8           # cap workers at 8
Output: data/databento/mbp-1-reconstructed/<date>.parquet
"""
import glob
import multiprocessing as mp
import os
import sys

import databento as db
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.getenv("DATABENTO_ROOT", "data/databento")
OUTDIR = os.path.join(ROOT, "mbp-1-reconstructed")
SENTINEL = 9223372036854775807          # DBN undefined price (INT64_MAX)
SCALE = 1e-9                            # DBN fixed-point price -> dollars
BATCH = 1_000_000                        # rows per Parquet write

SCHEMA = pa.schema([
    ("ts_event", pa.int64()), ("instrument_id", pa.int64()),
    ("bid_px", pa.float64()), ("bid_sz", pa.int64()),
    ("ask_px", pa.float64()), ("ask_sz", pa.int64()),
    ("mid", pa.float64()), ("spread", pa.float64()),
])


def _px(v):
    return float("nan") if abs(v) >= SENTINEL else v * SCALE


def reconstruct(src):
    date = src.split("glbx-mdp3-")[1][:8]
    out = os.path.join(OUTDIR, f"{date}.parquet")
    if os.path.exists(out):
        return (date, "exists", 0)
    tmp = out + ".tmp"
    last = {}                            # instrument_id -> (bpx,bsz,apx,asz)
    cols = {k: [] for k in ("ts", "iid", "bpx", "bsz", "apx", "asz", "mid", "spr")}
    writer = None
    n = 0

    def flush():
        nonlocal writer
        if not cols["ts"]:
            return
        tbl = pa.table({
            "ts_event": cols["ts"], "instrument_id": cols["iid"],
            "bid_px": cols["bpx"], "bid_sz": cols["bsz"],
            "ask_px": cols["apx"], "ask_sz": cols["asz"],
            "mid": cols["mid"], "spread": cols["spr"]}, schema=SCHEMA)
        if writer is None:
            writer = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
        writer.write_table(tbl)
        for v in cols.values():
            v.clear()

    try:
        store = db.DBNStore.from_file(src)
        for rec in store:
            levels = getattr(rec, "levels", None)
            if not levels:
                continue
            lv = levels[0]
            iid = rec.instrument_id
            key = (lv.bid_px, lv.bid_sz, lv.ask_px, lv.ask_sz)
            if last.get(iid) == key:        # L1 unchanged -> skip (mbp-1 semantics)
                continue
            last[iid] = key
            bpx, apx = _px(lv.bid_px), _px(lv.ask_px)
            cols["ts"].append(rec.ts_event); cols["iid"].append(iid)
            cols["bpx"].append(bpx); cols["bsz"].append(lv.bid_sz)
            cols["apx"].append(apx); cols["asz"].append(lv.ask_sz)
            cols["mid"].append((bpx + apx) / 2.0); cols["spr"].append(apx - bpx)
            n += 1
            if len(cols["ts"]) >= BATCH:
                flush()
        flush()
        if writer is not None:
            writer.close()
            os.replace(tmp, out)
        else:
            open(out, "a").close()          # empty day -> touch so it's not retried
        return (date, "ok", n)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return (date, f"ERR {repr(e)[:80]}", n)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(ROOT, "mbp-10", "*", "glbx-mdp3-*.mbp-10.dbn.zst")))
    nproc = int(sys.argv[1]) if len(sys.argv) > 1 else (mp.cpu_count() or 8)
    print(f"reconstructing L1 from {len(files)} mbp-10 files using {nproc} cores -> {OUTDIR}", flush=True)
    done = 0
    with mp.Pool(nproc) as pool:
        for date, status, nrows in pool.imap_unordered(reconstruct, files):
            done += 1
            print(f"  [{done}/{len(files)}] {date}: {status}  {nrows:,} L1 rows", flush=True)
    print("done.")


if __name__ == "__main__":
    main()
