"""Portfolio complementarity test: unchanged C11 plus standalone MR sleeve."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant import es_c11_robust as C11R
from quant.strategy_failed_breakout_mr import (
    MRParams, build_features, load_all_1m, run_backtest,
)


RESEARCH = Path("reports/es_failed_breakout_mr_research_20260714.json")
OUTPUT = Path("reports/es_failed_breakout_mr_portfolio_20260714.json")


def summarize(returns: pd.Series) -> dict:
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "mean_quarter": float(returns.mean()),
        "positive_quarters": float((returns > 0).mean()),
        "sharpe": float(returns.mean() / returns.std() * np.sqrt(4)) if returns.std() else 0.0,
        "max_drawdown": float(drawdown.min()),
    }


def main() -> None:
    research = json.loads(RESEARCH.read_text())
    # Selection is based only on train CV score, exactly as in the research run.
    finalist = max(research["finalists"], key=lambda row: row["cv_score"])
    params = MRParams(**finalist["params"])

    one_minute = load_all_1m()
    mr = build_features(one_minute, params)
    c11 = C11R.prep(allow_shorts=True)
    c11["dt"] = pd.DatetimeIndex(c11["ts"])

    # Restrict comparison to the untouched MR holdout period.
    hold_start = pd.Timestamp(one_minute["ts"].iloc[int(len(one_minute) * 0.6)])
    end = min(pd.Timestamp(mr["ts"].iloc[-1]), pd.Timestamp(c11["dt"].iloc[-1]))
    cur = hold_start.normalize()
    rows = []
    while cur + pd.DateOffset(months=3) <= end:
        nxt = cur + pd.DateOffset(months=3)
        mr_q = mr[(mr["ts"] >= cur) & (mr["ts"] < nxt)].reset_index(drop=True)
        c11_q = c11[(c11["dt"] >= cur) & (c11["dt"] < nxt)].reset_index(drop=True)
        if len(mr_q) < 10_000 or len(c11_q) < 1_000:
            cur = nxt
            continue
        mr_m = run_backtest(mr_q, params, direction=finalist["direction"])["metrics"]
        c11_m = C11R._bt(c11_q)
        rows.append({
            "quarter": str(cur.date()),
            "mr": float(mr_m["total_return"]),
            "mr_trades": int(mr_m["n_trades"]),
            "c11": float(c11_m["total_return"]),
            "c11_trades": int(c11_m["n_trades"]),
        })
        cur = nxt

    result = pd.DataFrame(rows)
    result["c11_plus_25pct_mr"] = result["c11"] + 0.25 * result["mr"]
    result["equal_weight"] = 0.5 * result["c11"] + 0.5 * result["mr"]
    summaries = {
        col: summarize(result[col])
        for col in ("c11", "mr", "c11_plus_25pct_mr", "equal_weight")
    }
    correlation = float(result[["c11", "mr"]].corr().iloc[0, 1])
    payload = {
        "mr_params": finalist["params"],
        "mr_direction": finalist["direction"],
        "selection": "highest train-only temporal CV score",
        "quarters": rows,
        "correlation": correlation,
        "summary": summaries,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2))

    print(f"quarters {len(result)} | C11/MR correlation {correlation:+.3f}")
    print(f"{'book':20} {'total%':>8} {'qtr+':>6} {'Sharpe':>7} {'maxDD%':>8}")
    for name, summary in summaries.items():
        print(f"{name:20} {summary['total_return']*100:>+7.1f} "
              f"{summary['positive_quarters']*100:>5.0f}% "
              f"{summary['sharpe']:>7.2f} {summary['max_drawdown']*100:>8.1f}")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
