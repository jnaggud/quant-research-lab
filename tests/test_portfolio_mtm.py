import pandas as pd

from quant.es_portfolio_simulation import CAPITAL, _daily_mtm_from_result


def test_daily_mtm_reconciles_to_closed_trade_pnl():
    frame = pd.DataFrame({
        "ts": pd.to_datetime([
            "2026-01-05 20:00Z", "2026-01-06 20:00Z", "2026-01-07 20:00Z",
        ]),
        "close": [100.0, 101.0, 102.0],
    })
    result = {"trades": [{
        "entry_i": 0, "exit_i": 2, "dir": 1,
        "entry_px": 100.0, "pnl": 95.0,
    }]}
    daily = _daily_mtm_from_result(result, frame, "test", slippage_ticks=0)
    assert abs(daily["test_return"].sum() - 95.0 / CAPITAL) < 1e-12
    assert daily["test_trades"].sum() == 1
    # Open-position marks appear before the eventual exit.
    assert (daily["test_return"].iloc[:2] != 0).all()
