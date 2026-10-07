import numpy as np
import pytest

from quant.quant_desk_methods import (
    monte_carlo_standard_error, peaks_over_threshold, probability_scores,
    smooth_logit_state,
)


def test_probability_scores_match_known_values():
    result = probability_scores([0.7, 0.3, 0.9, 0.1], [1, 0, 1, 0], bins=5)
    assert result["brier"] == pytest.approx(0.05)
    assert sum(row["count"] for row in result["reliability"]) == 4


def test_logit_filter_is_causal_and_smooths_jump():
    obs = np.array([0.5, 0.5, 0.5, 0.9, 0.9])
    filtered = smooth_logit_state(obs, process_variance=0.001,
                                  observation_variance=0.2)
    assert filtered[2] == pytest.approx(0.5)
    assert 0.5 < filtered[3] < 0.9


def test_evt_tail_fit_is_finite_for_exponential_losses():
    losses = np.random.default_rng(7).exponential(1.0, 20_000)
    result = peaks_over_threshold(losses)
    assert abs(result["shape"]) < 0.1
    assert result["expected_shortfall"] > result["value_at_risk"]


def test_mc_standard_error():
    assert monte_carlo_standard_error([0, 0, 1, 1]) == pytest.approx(0.25)
