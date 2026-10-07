import json

from dashboard.trader_metrics import summarize_report


def test_frozen_c11_report_summary_matches_tradingview():
    report = json.load(open("archives/c11_frozen_20260714/tv_c11_current_report_20260714.json"))
    result = summarize_report(report)
    assert result["stats"]["net_profit"] == 126_905
    assert result["stats"]["trades"] == 469
    assert result["stats"]["wins"] == 223
    assert result["best_trade"]["pnl"] == 9_070
    assert result["worst_trade"]["pnl"] == -3_917.5
    assert len(result["equity"]) == 469
