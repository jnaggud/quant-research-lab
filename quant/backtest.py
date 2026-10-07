"""backtest.py — vectorized event backtest engine for the ES pipeline.

Ports the *integrity-hardened* discipline from Pattern_FindR's
`velocity_trading/core/backtest_engine.py`, with the flaws fixed and the missing
futures contract economics added. The guards that matter (from docs/architecture.md):

  * COMPLETED-BAR signals → entry on the NEXT bar (no same-bar look-ahead).
  * GAP-THROUGH fills: a bar that gaps past a stop fills at the gap (open),
    not at the exact stop level (the optimistic-fill flaw).
  * HIGH-WATERMARK exit guard: break-even / trailing exits are credited only if
    the running extreme actually reached the level AND the bar traded back to it
    (kills the "phantom break-even" fabricated-profit bug).
  * COSTS IN THE SIM: per-side commission + slippage (ticks), always — so the
    optimizer can't select cost-fragile sub-tick scalps.
  * Real ES contract model: 0.25 tick = $12.50, $50/point.

Input `bars`: a Polars (or pandas) frame with columns
    ts, open, high, low, close, signal
where `signal` ∈ {+1 enter long, -1 enter short, 0 nothing} is computed by a
CAUSAL strategy on the *completed* bar. Optional `exit_signal` ∈ {0,1}.

All prices are in index POINTS; P&L is converted to dollars via the contract.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Contract:
    name: str = "ES"
    tick: float = 0.25
    tick_value: float = 12.50     # $ per tick
    commission: float = 2.50      # $ per contract per side (round-trip = 2x)

    @property
    def point_value(self) -> float:
        return self.tick_value / self.tick   # ES: 12.5 / 0.25 = $50 / point


ES = Contract()


def _to_arrays(bars):
    """Accept Polars or pandas; return numpy O/H/L/C/signal/exit arrays."""
    cols = ("open", "high", "low", "close", "signal")
    try:  # polars
        o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
        l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
        sig = bars["signal"].to_numpy()
        ex = bars["exit_signal"].to_numpy() if "exit_signal" in bars.columns else np.zeros(len(o))
    except Exception:  # pandas
        o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
        l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
        sig = bars["signal"].to_numpy()
        ex = bars["exit_signal"].to_numpy() if "exit_signal" in bars.columns else np.zeros(len(o))
    return (o.astype(float), h.astype(float), l.astype(float),
            c.astype(float), sig.astype(float), ex.astype(float))


def run_backtest(
    bars,
    *,
    contract: Contract = ES,
    entry_mode: str = "next_bar_open",     # next_bar_open | near_close
    direction: str = "both",               # long | short | both (default: honor signal sign)
    stop_loss_pts: float | None = None,
    take_profit_pts: float | None = None,
    trailing_pts: float | None = None,
    breakeven_trigger_pts: float | None = None,
    breakeven_offset_pts: float = 0.0,
    slippage_ticks: float = 1.0,
    min_hold_bars: int = 0,
    max_hold_bars: int | None = None,
    min_bars_between: int = 0,
    contracts: int = 1,
    starting_equity: float = 100_000.0,
) -> dict:
    """Run the backtest. Returns {trades, equity_curve, metrics}.

    Exit priority each bar (intrabar): hard stop / target / breakeven / trailing
    via high/low, then signal-based exit (respects min_hold_bars). Stops & targets
    bypass min_hold (a real stop fires regardless).
    """
    o, h, l, c, sig, ex = _to_arrays(bars)
    n = len(o)
    pv = contract.point_value
    slip_dollars = slippage_ticks * contract.tick_value   # $ slippage per side per contract
    comm = contract.commission
    allow_long = direction in ("long", "both")
    allow_short = direction in ("short", "both")

    trades = []
    equity = starting_equity
    eq_curve = np.full(n, np.nan)

    pos = 0           # +1 long, -1 short, 0 flat
    entry_px = 0.0
    entry_i = -1
    hwm = -np.inf     # high-water mark of price since entry (for longs)
    lwm = np.inf      # low-water mark (for shorts)
    stop = None
    last_exit_i = -10**9

    def _dollars(exit_px):
        # Slippage is baked into BOTH fill prices (entry_px raised, exit_px lowered
        # against us). Here we charge only round-trip commission.
        gross = (exit_px - entry_px) * pos * pv * contracts
        return gross - (2 * comm) * contracts

    for i in range(n):
        # ---- manage an open position on bar i ----
        if pos != 0:
            exit_px = None
            reason = None
            held = i - entry_i

            if pos > 0:
                hwm = max(hwm, h[i])
                # breakeven: once trigger hit, raise stop to entry+offset
                if breakeven_trigger_pts is not None and hwm >= entry_px + breakeven_trigger_pts:
                    be = entry_px + breakeven_offset_pts
                    stop = be if stop is None else max(stop, be)
                # trailing
                if trailing_pts is not None:
                    trail = hwm - trailing_pts
                    stop = trail if stop is None else max(stop, trail)
                # hard stop (incl. breakeven/trailing) with GAP-THROUGH + HWM guard
                if stop is not None and l[i] <= stop and hwm >= stop:
                    exit_px = min(o[i], stop)        # gap-through: fill at open if gapped below
                    reason = "stop"
                elif stop_loss_pts is not None and l[i] <= entry_px - stop_loss_pts:
                    lvl = entry_px - stop_loss_pts
                    exit_px = min(o[i], lvl)
                    reason = "stop_loss"
                elif take_profit_pts is not None and h[i] >= entry_px + take_profit_pts:
                    lvl = entry_px + take_profit_pts
                    exit_px = max(o[i], lvl)         # gap-through favorable
                    reason = "take_profit"
            else:  # short
                lwm = min(lwm, l[i])
                if breakeven_trigger_pts is not None and lwm <= entry_px - breakeven_trigger_pts:
                    be = entry_px - breakeven_offset_pts
                    stop = be if stop is None else min(stop, be)
                if trailing_pts is not None:
                    trail = lwm + trailing_pts
                    stop = trail if stop is None else min(stop, trail)
                if stop is not None and h[i] >= stop and lwm <= stop:
                    exit_px = max(o[i], stop)
                    reason = "stop"
                elif stop_loss_pts is not None and h[i] >= entry_px + stop_loss_pts:
                    lvl = entry_px + stop_loss_pts
                    exit_px = max(o[i], lvl)
                    reason = "stop_loss"
                elif take_profit_pts is not None and l[i] <= entry_px - take_profit_pts:
                    lvl = entry_px - take_profit_pts
                    exit_px = min(o[i], lvl)
                    reason = "take_profit"

            # max-hold cap: force-close a stale trade (caps runaway bleed)
            if exit_px is None and max_hold_bars is not None and held >= max_hold_bars:
                exit_px = c[i]
                reason = "max_hold"

            # signal-based exit (respects min_hold)
            if exit_px is None and held >= min_hold_bars:
                opp = (pos > 0 and sig[i] < 0) or (pos < 0 and sig[i] > 0)
                if ex[i] > 0 or opp:
                    exit_px = c[i]
                    reason = "signal"

            if exit_px is not None:
                # exit slippage against us (long sells lower, short buys higher)
                exit_px = exit_px - slippage_ticks * contract.tick * pos
                pnl = _dollars(exit_px)
                equity += pnl
                trades.append({
                    "entry_i": entry_i, "exit_i": i, "dir": pos,
                    "entry_px": entry_px, "exit_px": exit_px,
                    "bars_held": held, "reason": reason, "pnl": pnl, "equity": equity,
                })
                pos = 0; stop = None; hwm = -np.inf; lwm = np.inf
                last_exit_i = i

        # ---- look for a new entry (signal on COMPLETED bar i → enter next bar) ----
        if pos == 0 and (i - last_exit_i) >= min_bars_between:
            want = int(sig[i])
            if want > 0 and allow_long or want < 0 and allow_short:
                if entry_mode == "near_close":
                    entry_px = c[i]; entry_i = i
                    pos = 1 if want > 0 else -1
                    hwm = h[i]; lwm = l[i]
                elif entry_mode == "next_bar_open" and i + 1 < n:
                    entry_px = o[i + 1]; entry_i = i + 1
                    pos = 1 if want > 0 else -1
                    hwm = h[i + 1]; lwm = l[i + 1]
                # apply entry slippage by shifting fill against us
                if pos != 0:
                    entry_px += (slippage_ticks * contract.tick) * pos  # buy higher / sell lower

        eq_curve[i] = equity

    metrics = _metrics(trades, eq_curve, starting_equity)
    return {"trades": trades, "equity_curve": eq_curve, "metrics": metrics}


def _metrics(trades, eq_curve, start) -> dict:
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "total_return": 0.0, "win_rate": 0.0,
                "profit_factor": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "final_equity": start}
    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    eq = eq_curve[~np.isnan(eq_curve)]
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    # per-trade returns for a simple Sharpe (not annualized — comparison metric)
    rets = pnls / start
    sharpe = float(rets.mean() / rets.std() * np.sqrt(len(rets))) if rets.std() > 0 else 0.0
    return {
        "n_trades": n,
        "total_return": float((eq[-1] - start) / start),
        "win_rate": float((pnls > 0).mean()),
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
        "max_drawdown": float(abs(dd.min())) if len(dd) else 0.0,
        "sharpe": sharpe,
        "final_equity": float(eq[-1]),
    }


# --------------------------------------------------------------------------------------
# Self-test (synthetic — no drive I/O)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    import pandas as pd

    # Build a synthetic series where we can hand-verify P&L.
    # Bars: enter long signal at bar 0 → enter at bar1 open=100. Price rises to 110.
    o = [100, 100, 102, 104, 106, 108, 110, 109, 108, 107]
    h = [101, 101, 103, 105, 107, 109, 111, 110, 109, 108]
    l = [99,  100, 101, 103, 105, 107, 109, 108, 107, 106]
    c = [100, 101, 103, 105, 107, 109, 110, 109, 108, 107]
    sig = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "signal": sig})

    # Take-profit at +8 pts (108) → should fill at 108. Entry at bar1 open=100 + 1tick slip.
    r = run_backtest(df, contract=ES, entry_mode="next_bar_open",
                     take_profit_pts=8, slippage_ticks=1, contracts=1)
    t = r["trades"][0]
    print(f"entry={t['entry_px']} exit={t['exit_px']} reason={t['reason']} pnl=${t['pnl']:.2f}")
    # entry: bar1 open 100 + 1 tick slip = 100.25; TP level = 100.25+8 = 108.25 → hit bar5 (h=109),
    # raw fill max(open108,108.25)=108.25, minus 1 tick exit slip = 108.00.
    # gross=(108.00-100.25)*50=$387.50; commission round-trip=2*2.50=$5 → pnl=$382.50
    exp_pnl = (t["exit_px"] - t["entry_px"]) * ES.point_value - 2 * ES.commission
    print(f"expected pnl=${exp_pnl:.2f}  metrics={r['metrics']}")
    assert abs(t["pnl"] - exp_pnl) < 1e-6, "pnl mismatch"
    assert t["reason"] == "take_profit"

    # Gap-through stop test: price gaps DOWN through a stop → fill at the gap open, not the level.
    o2 = [100, 100,  90]   # bar2 gaps to 90
    h2 = [101, 101,  91]
    l2 = [99,  100,  89]
    c2 = [100, 100,  90]
    df2 = pd.DataFrame({"open": o2, "high": h2, "low": l2, "close": c2, "signal": [1, 0, 0]})
    r2 = run_backtest(df2, contract=ES, entry_mode="next_bar_open", stop_loss_pts=5, slippage_ticks=0)
    t2 = r2["trades"][0]
    print(f"GAP stop: entry={t2['entry_px']} exit={t2['exit_px']} (stop level was 95; gap open 90)")
    assert t2["exit_px"] == 90.0, "gap-through fill not applied"
    print("backtest.py self-test PASSED")
