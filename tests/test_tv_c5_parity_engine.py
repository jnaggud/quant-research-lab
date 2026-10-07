import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tv_c5_parity_engine import SignalBar, default_c5_params, run_tv_compatible_signal_bars


def params(**overrides):
    data = default_c5_params()
    data.update(
        {
            "stop_atr": 1.0,
            "trail_atr": 5.0,
            "cooldown": 0,
            "cap_stop_atr": 1.0,
            "cap_trail_atr": 5.0,
            "cap_target_atr": 2.0,
            "cap_min_hold": 0,
            "cap_max_hold": 99,
            "cap_cooldown": 0,
        }
    )
    data.update(overrides)
    return data


class TvC5ParityEngineTests(unittest.TestCase):
    def test_nonmarketable_entry_bar_stop_waits_for_next_script_pass(self):
        bars = [
            SignalBar(0, 100, 101, 99, 100, atr=1, core_long=True),
            SignalBar(1, 100, 101, 95, 100, atr=1),
            SignalBar(2, 100, 101, 99.5, 100, atr=1),
        ]

        result = run_tv_compatible_signal_bars(bars, params())

        self.assertEqual(result.n_trades, 1)
        self.assertEqual(result.trades[0].exit_bar, 2)
        self.assertEqual(result.trades[0].exit_reason, "end_of_data")

    def test_recalculated_trailing_stop_uses_prior_entry_high_until_next_bar(self):
        bars = [
            SignalBar(0, 100, 100, 100, 100, atr=1, core_long=True),
            SignalBar(1, 100, 101, 100, 100, atr=1),
            SignalBar(2, 100, 110, 104, 106, atr=1),
            SignalBar(3, 106, 106, 104, 105, atr=1),
        ]

        result = run_tv_compatible_signal_bars(bars, params(stop_atr=20.0, trail_atr=2.0))

        self.assertEqual(result.n_trades, 1)
        self.assertEqual(result.trades[0].exit_bar, 3)
        self.assertEqual(result.trades[0].exit_reason, "stop")

    def test_close_based_exit_does_not_reenter_on_same_bar(self):
        bars = [
            SignalBar(0, 100, 100, 100, 100, atr=1, core_long=True),
            SignalBar(1, 100, 101, 99, 100, atr=1),
            SignalBar(2, 100, 101, 99, 100, atr=1, core_long=True, core_long_close_exit=True),
            SignalBar(3, 100, 101, 99, 100, atr=1),
        ]

        result = run_tv_compatible_signal_bars(bars, params(stop_atr=20.0, trail_atr=20.0))

        self.assertEqual(result.n_trades, 1)
        self.assertEqual(result.trades[0].exit_bar, 2)
        self.assertEqual(result.core_trades, 1)

    def test_normal_protective_exit_can_reenter_on_same_bar(self):
        bars = [
            SignalBar(0, 100, 100, 100, 100, atr=1, core_long=True),
            SignalBar(1, 100, 101, 100, 100, atr=1),
            SignalBar(2, 100, 101, 98, 100, atr=1, core_long=True),
            SignalBar(3, 100, 101, 99, 100, atr=1),
        ]

        result = run_tv_compatible_signal_bars(bars, params())

        self.assertEqual(result.core_trades, 2)
        self.assertEqual(result.trades[0].exit_bar, 2)
        self.assertEqual(result.trades[0].exit_reason, "stop")

    def test_cap_dual_hit_uses_historical_ohlc_path(self):
        bars = [
            SignalBar(0, 100, 100, 100, 100, atr=1, cap_long=True),
            SignalBar(1, 100, 101, 100, 100, atr=1),
            SignalBar(2, 100, 103, 98, 100, atr=1),
        ]

        result = run_tv_compatible_signal_bars(bars, params())

        self.assertEqual(result.n_trades, 1)
        self.assertEqual(result.trades[0].exit_reason, "stop")

    def test_cap_limit_gap_fills_at_open_better_price(self):
        bars = [
            SignalBar(0, 100, 100, 100, 100, atr=1, cap_long=True),
            SignalBar(1, 100, 101, 100, 100, atr=1),
            SignalBar(2, 105, 106, 104, 105, atr=1),
        ]

        result = run_tv_compatible_signal_bars(bars, params(cap_target_atr=2.0))

        self.assertEqual(result.n_trades, 1)
        self.assertEqual(result.trades[0].exit_bar, 2)
        self.assertEqual(result.trades[0].exit_reason, "limit")
        self.assertEqual(result.trades[0].exit_price, 105.0)


if __name__ == "__main__":
    unittest.main()
