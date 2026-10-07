import numpy as np

from quant.tv_c11_exact_simulation import (
    EXPECTED_PINE_SHA256, EXPECTED_PNL, build_daily_panel,
)


def test_exact_report_reconstruction_and_source_integrity():
    panel, metadata = build_daily_panel()
    assert metadata["pine_sha256"] == EXPECTED_PINE_SHA256
    assert metadata["frozen_pine_sha256"] == EXPECTED_PINE_SHA256
    assert metadata["missing_trade_timestamps"] == 0
    assert metadata["trades"] == 469
    assert np.isclose(metadata["realized_pnl"], EXPECTED_PNL)
    assert np.isclose(panel["c11_return"].sum() * 50_000.0, EXPECTED_PNL)
    assert panel["c11_trades"].sum() == 469
