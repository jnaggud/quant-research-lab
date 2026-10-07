from dataclasses import replace

import numpy as np

from quant.portfolio_simulation import SimulationSpec, simulate


def sample_inputs():
    rng = np.random.default_rng(11)
    returns = np.column_stack([
        rng.normal(0.0010, 0.004, 240),
        rng.normal(0.0002, 0.002, 240),
    ])
    trades = rng.poisson(0.25, (240, 2))
    regimes = np.repeat(np.arange(4), 60)
    return returns, trades, regimes


def test_simulation_is_deterministic_and_finite():
    returns, trades, regimes = sample_inputs()
    spec = SimulationSpec(n_paths=200, horizon_days=126, mean_block_days=10)
    weights = np.array([0.8, 0.2])
    first, _ = simulate(returns, trades, regimes, weights, spec, seed=17, workers=2)
    second, _ = simulate(returns, trades, regimes, weights, spec, seed=17, workers=2)
    assert first.shape == (200, 4)
    assert np.isfinite(first).all()
    assert np.array_equal(first, second)


def test_execution_and_dependence_stress_reduce_median_return():
    returns, trades, regimes = sample_inputs()
    base = SimulationSpec(n_paths=400, horizon_days=252, mean_block_days=10)
    stress = replace(
        base, extra_slippage_ticks=2.0,
        synchronized_loss_probability=0.5,
    )
    weights = np.array([0.8, 0.2])
    _, baseline = simulate(returns, trades, regimes, weights, base, seed=23, workers=2)
    _, stressed = simulate(returns, trades, regimes, weights, stress, seed=23, workers=2)
    assert stressed["return_quantiles"]["0.5"] < baseline["return_quantiles"]["0.5"]


def test_all_bootstrap_and_equity_modes_produce_finite_paths():
    returns, trades, regimes = sample_inputs()
    weights = np.array([0.8, 0.2])
    for method in ("regime", "stationary", "moving", "circular", "crisis_weighted"):
        for equity_mode in ("fixed_notional", "compound"):
            spec = SimulationSpec(
                n_paths=40, horizon_days=80, mean_block_days=10,
                bootstrap_method=method, equity_mode=equity_mode,
            )
            paths, _ = simulate(returns, trades, regimes, weights, spec,
                                seed=31, workers=2)
            assert paths.shape == (40, 4)
            assert np.isfinite(paths).all()


def test_fixed_notional_path_cannot_recover_after_insolvency():
    returns = np.array([[-1.1], [2.0]])
    trades = np.zeros_like(returns)
    regimes = np.zeros(2, dtype=int)
    spec = SimulationSpec(n_paths=20, horizon_days=2, mean_block_days=2,
                          bootstrap_method="moving")
    paths, _ = simulate(returns, trades, regimes, np.array([1.0]), spec,
                        seed=7, workers=1)
    insolvent = paths[:, 3] > 0
    assert insolvent.any()
    assert np.all(paths[insolvent, 0] == -1.0)
