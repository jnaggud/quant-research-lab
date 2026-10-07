"""dbn_data.py — Databento DBN data-access layer for the ES quant pipeline.

Reads `.dbn.zst` files (via the databento SDK), returns **Polars** DataFrames,
and provides Polygon-compatible accessors plus ES-style continuous front-month
stitching. Pure read layer: no network, no lookahead, no mutation of source data.

Layout assumed:  <ROOT>/<schema>/<job_id>/glbx-mdp3-YYYYMMDD.<schema>.dbn.zst

Symbol conventions (GLBX.MDP3 raw_symbol):
  outright future : ESU6, ESZ6, 6EU6        (root + month-code + year digit)
  option          : "ESU6 C7800", "ESU6 P6900"   (space-separated, C/P + strike)
  spread          : ESU6-ESZ6                     (dash)

Design notes
------------
* Front-month roll is **volume-based**: for each day, the outright contract of a
  root with the highest traded volume is "front". This is causal (uses only that
  day's volume) and is the standard liquid-contract continuous definition.
* All timestamps stay tz-aware UTC nanosecond (Polars Datetime). We never round
  through Python `datetime` (which is microsecond-only).
"""
from __future__ import annotations

import glob
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import databento as db
import polars as pl

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

ROOT = Path(os.getenv("DATABENTO_ROOT", "data/databento"))

TIMESPAN_SCHEMA = {
    "second": "ohlcv-1s",
    "minute": "ohlcv-1m",
    "hour": "ohlcv-1h",
    "day": "ohlcv-1d",
}

MONTH_CODES = "FGHJKMNQUVXZ"          # Jan..Dec
QUARTERLY = "HMUZ"                     # Mar, Jun, Sep, Dec (ES/NQ/etc. cycle)

_FILE_RE = re.compile(r"glbx-mdp3-(\d{8})\.")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _as_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def _outright_regex(root: str) -> str:
    """Regex matching an OUTRIGHT future for `root` (no option, no spread)."""
    return rf"^{re.escape(root)}[{MONTH_CODES}]\d+$"


def _files_for(schema: str, start=None, end=None) -> list[tuple[date, str]]:
    """Sorted [(date, path)] of daily files for a schema, within [start, end].

    Re-submitted jobs can produce duplicate per-date files across job dirs; we
    dedupe by date, keeping the LARGEST file per date (most complete extract).
    """
    s = _as_date(start) if start is not None else None
    e = _as_date(end) if end is not None else None
    best: dict[date, tuple[int, str]] = {}
    for p in glob.glob(str(ROOT / schema / "*" / f"*.{schema}.dbn.zst")):
        m = _FILE_RE.search(os.path.basename(p))
        if not m:
            continue
        d = datetime.strptime(m.group(1), "%Y%m%d").date()
        if (s and d < s) or (e and d > e):
            continue
        try:
            sz = os.path.getsize(p)
        except OSError:
            sz = 0
        if d not in best or sz > best[d][0]:
            best[d] = (sz, p)
    return sorted((d, sz_p[1]) for d, sz_p in best.items())


def _id_symbol_map(store) -> dict:
    """instrument_id -> raw_symbol from the DBN symbology (cheap)."""
    out: dict[int, str] = {}
    try:
        mappings = store.symbology.get("mappings", {})
    except Exception:
        return out
    for raw, entries in mappings.items():
        for e in entries:
            iid = e.get("symbol")
            if iid is None:
                continue
            try:
                out[int(iid)] = raw
            except (TypeError, ValueError):
                pass
    return out


def _read_dbn(path: str) -> pl.DataFrame:
    """Read one .dbn.zst file -> Polars DataFrame WITHOUT symbol mapping (fast,
    ~0.07s). `instrument_id` is present; symbol mapping is done separately (and
    only for the root of interest) via the cached id-map below."""
    store = db.DBNStore.from_file(path)
    pdf = store.to_df(map_symbols=False)
    pdf = pdf.reset_index()
    return pl.from_pandas(pdf)


# instrument_id -> outright-future symbol, cached per root. Built by sampling the
# symbology of a handful of files across the range (the full per-file symbology
# carries the entire 1.38M-symbol universe and costs ~1s to access — far too slow
# to do per file, so we sample and reuse; ES contract ids are stable over a life).
_ROOT_IDMAP_CACHE: dict[str, dict[int, str]] = {}


def _build_root_idmap(root: str, files: list[tuple[date, str]]) -> dict[int, str]:
    """{instrument_id: outright_symbol} for `root`, built by sampling symbology
    across the file range. instrument_id is stable per contract, so we ignore the
    one-day mapping windows and keep a flat id->symbol map (valid within a staging
    window of a few years; ids can recycle only over much longer spans)."""
    rx = re.compile(_outright_regex(root))
    span = max(1, len(files) // 24)
    sample = list({p for _d, p in files[::span]} | {files[-1][1]} | {files[0][1]})
    idmap: dict[int, str] = {}
    for p in sample:
        try:
            mappings = db.DBNStore.from_file(p).symbology.get("mappings", {})
        except Exception:
            continue
        for raw, entries in mappings.items():
            if not rx.match(raw):
                continue
            for e in entries:
                try:
                    idmap[int(e["symbol"])] = raw
                except (TypeError, ValueError):
                    pass
    return idmap


def _root_idmap(root: str, files: list[tuple[date, str]]) -> dict[int, str]:
    if root not in _ROOT_IDMAP_CACHE:
        _ROOT_IDMAP_CACHE[root] = _build_root_idmap(root, files)
    return _ROOT_IDMAP_CACHE[root]


def _ts_col(df: pl.DataFrame) -> str:
    for c in ("ts_event", "ts_recv", "ts"):
        if c in df.columns:
            return c
    return df.columns[0]


# --------------------------------------------------------------------------------------
# Coverage / discovery
# --------------------------------------------------------------------------------------

def schemas_on_disk() -> list[str]:
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir())


def coverage(schema: str) -> dict | None:
    """Return {schema, files, start, end} for what's downloaded, or None."""
    fs = _files_for(schema)
    if not fs:
        return None
    return {"schema": schema, "files": len(fs), "start": fs[0][0].isoformat(), "end": fs[-1][0].isoformat()}


# --------------------------------------------------------------------------------------
# Core loader
# --------------------------------------------------------------------------------------

def load(
    schema: str,
    start=None,
    end=None,
    symbols: Iterable[str] | None = None,
    root: str | None = None,
    outright_only: bool = False,
) -> pl.DataFrame:
    """Load a schema across a date range as one Polars DataFrame.

    symbols       : keep only these exact raw symbols.
    root          : keep only symbols beginning with this product root.
    outright_only : keep only outright futures for `root` (drops options & spreads);
                    requires `root`.
    """
    if outright_only and not root:
        raise ValueError("outright_only=True requires root=")
    sym_list = list(symbols) if symbols is not None else None
    files = _files_for(schema, start, end)
    verbose = bool(os.environ.get("DBN_VERBOSE"))

    # Infer a root from requested outright symbols so single-symbol queries also
    # use the fast id path.
    eff_root = root
    if eff_root is None and sym_list:
        roots = {m.group(1) for s in sym_list
                 if (m := re.match(rf"^([A-Z0-9]+?)[{MONTH_CODES}]\d+$", s))}
        if len(roots) == 1:
            eff_root = next(iter(roots))

    # FAST PATH: filter by instrument_id via the cached root id-map (no per-file
    # symbology). Falls back to the slow per-file mapping only if no root resolves.
    idmap = _root_idmap(eff_root, files) if eff_root else None
    id_keys = list(idmap.keys()) if idmap else None

    frames: list[pl.DataFrame] = []
    for idx, (_d, p) in enumerate(files, 1):
        if verbose and (idx % 100 == 0 or idx == len(files)):
            print(f"  [load {schema}] {idx}/{len(files)} files...", flush=True)
        f = _read_dbn(p)  # has instrument_id, no symbol
        if idmap is not None and "instrument_id" in f.columns:
            f = f.filter(pl.col("instrument_id").is_in(id_keys))
            if f.height == 0:
                continue
            f = f.with_columns(
                pl.col("instrument_id").replace_strict(idmap, default=None).alias("symbol")
            )
            if sym_list is not None:
                f = f.filter(pl.col("symbol").is_in(sym_list))
        elif sym_list is not None or root is not None:
            # slow fallback: map all symbols (rare — only when no single root resolves)
            store = db.DBNStore.from_file(p)
            id2sym = _id_symbol_map(store)
            if id2sym and "instrument_id" in f.columns:
                f = f.with_columns(
                    pl.col("instrument_id").replace_strict(id2sym, default=None).alias("symbol")
                )
                if sym_list is not None:
                    f = f.filter(pl.col("symbol").is_in(sym_list))
                if root is not None:
                    f = f.filter(pl.col("symbol").str.starts_with(root))
        if f.height:
            frames.append(f)
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal_relaxed").sort(_ts_col(frames[0]))


# --------------------------------------------------------------------------------------
# Polygon-compatible price accessor
# --------------------------------------------------------------------------------------

_OHLCV_OUT = ["ts", "open", "high", "low", "close", "volume", "symbol"]


def get_price_data(symbol: str, timespan: str = "minute", start=None, end=None) -> pl.DataFrame:
    """Mirror of PolygonManager.get_price_data: OHLCV for one symbol.

    timespan in {second, minute, hour, day}. Returns columns
    [ts, open, high, low, close, volume, symbol] sorted by ts (tz-aware UTC).
    """
    schema = TIMESPAN_SCHEMA[timespan]
    df = load(schema, start, end, symbols=[symbol])
    if df.is_empty():
        return df
    ts = _ts_col(df)
    return df.select(
        pl.col(ts).alias("ts"), "open", "high", "low", "close", "volume", "symbol"
    ).sort("ts")


def list_contracts(root: str, timespan: str = "day", start=None, end=None) -> pl.DataFrame:
    """All outright-future contracts for a root with total volume in range,
    most-traded first. Useful to inspect the roll schedule."""
    schema = TIMESPAN_SCHEMA[timespan]
    df = load(schema, start, end, root=root, outright_only=True)
    if df.is_empty():
        return df
    return (
        df.group_by("symbol")
        .agg(pl.col("volume").sum().alias("total_volume"), pl.len().alias("bars"))
        .sort("total_volume", descending=True)
    )


# --------------------------------------------------------------------------------------
# Continuous front-month
# --------------------------------------------------------------------------------------

def continuous(
    root: str,
    timespan: str = "day",
    start=None,
    end=None,
    adjust: bool = False,
) -> pl.DataFrame:
    """Build a continuous front-month series for `root` by **volume roll**.

    For each calendar day, the outright contract with the highest *daily* volume
    is the front contract; its bars are kept. Rolls happen automatically when
    volume migrates to the next contract.

    adjust=True back-adjusts price levels so the series is continuous across rolls
    (subtracts the close gap at each roll from all prior bars — panama-canal style),
    preserving returns. Raw (unadjusted) keeps true traded prices with roll gaps.

    Returns [ts, open, high, low, close, volume, symbol] (+ 'adj_*' if adjust).
    """
    schema = TIMESPAN_SCHEMA[timespan]
    bars = load(schema, start, end, root=root, outright_only=True)
    if bars.is_empty():
        return bars
    ts = _ts_col(bars)
    bars = bars.with_columns(pl.col(ts).dt.date().alias("d"))

    # front contract per day = max daily volume
    front = (
        bars.group_by(["d", "symbol"])
        .agg(pl.col("volume").sum().alias("dv"))
        .sort(["d", "dv"])
        .group_by("d", maintain_order=True)
        .last()
        .select(["d", pl.col("symbol").alias("front")])
    )
    out = (
        bars.join(front, on="d")
        .filter(pl.col("symbol") == pl.col("front"))
        .select(pl.col(ts).alias("ts"), "open", "high", "low", "close", "volume", "symbol")
        .sort("ts")
    )

    if adjust and out.height:
        # roll points: where symbol changes vs previous bar
        out = out.with_columns(
            (pl.col("symbol") != pl.col("symbol").shift(1)).fill_null(False).alias("_roll")
        )
        # gap at each roll = new contract's open-bar close - prior contract's last close.
        # Cumulative adjustment applied to *historical* bars so the latest is true price.
        prev_close = out.select("close").to_series().shift(1)
        cur_close = out.select("close").to_series()
        roll_mask = out.select("_roll").to_series()
        gaps = (cur_close - prev_close)  # only meaningful on roll rows
        # back-adjust: at each roll, all earlier bars shift by the gap so prices line up
        import numpy as np
        g = gaps.to_numpy()
        rm = roll_mask.to_numpy()
        adj = np.zeros(len(g))
        # walk backwards: cumulative sum of roll gaps that occur AFTER each bar
        run = 0.0
        for i in range(len(g) - 1, -1, -1):
            adj[i] = run
            if rm[i]:
                run += g[i] if not np.isnan(g[i]) else 0.0
        out = out.with_columns(pl.Series("_adj", adj)).with_columns(
            (pl.col("open") - pl.col("_adj")).alias("adj_open"),
            (pl.col("high") - pl.col("_adj")).alias("adj_high"),
            (pl.col("low") - pl.col("_adj")).alias("adj_low"),
            (pl.col("close") - pl.col("_adj")).alias("adj_close"),
        ).drop(["_roll", "_adj"])
    return out


if __name__ == "__main__":
    import sys
    print("schemas on disk:", schemas_on_disk())
    for s in ("ohlcv-1d", "ohlcv-1m", "definition", "trades", "bbo-1m"):
        print(" ", coverage(s))
