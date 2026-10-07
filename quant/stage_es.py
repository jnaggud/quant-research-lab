"""stage_es.py — stage a continuous front-month series to local SSD Parquet.

Reads the (ALL_SYMBOLS) ohlcv DBN files off the archive HDD, filters to the
root's outright futures, builds the volume-roll continuous series, and writes a
small Parquet to ./cache on the fast local disk. Run this with the bulk download
PAUSED (the HDD can't serve big reads while the downloader saturates it).

Usage:
  DBN_VERBOSE=1 python -m quant.stage_es --root ES --timespan day --start 2021-01-01 --end 2026-06-28
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from quant import dbn_data as d

CACHE = Path(__file__).parent / "cache"


def stage(root: str, timespan: str, start: str, end: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    t0 = time.time()
    cont = d.continuous(root, timespan, start, end, adjust=True)
    out = CACHE / f"{root}_continuous_{timespan}_{start}_{end}.parquet"
    if cont.is_empty():
        raise SystemExit(f"no data staged for {root} {timespan} {start}..{end}")
    cont.write_parquet(out)
    n = cont.height
    print(f"staged {n} bars ({cont['ts'].min()} .. {cont['ts'].max()}) -> {out}  "
          f"in {time.time()-t0:.0f}s", flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="ES")
    ap.add_argument("--timespan", default="day")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-06-28")
    a = ap.parse_args()
    stage(a.root, a.timespan, a.start, a.end)
