import numpy as np
import pandas as pd

from quant.c11_multiyear_x_research import candidate_specs, x_context


def test_candidate_search_is_unique_and_has_control():
    specs = candidate_specs()
    assert len(specs) == 433
    assert len({row["id"] for row in specs}) == len(specs)
    assert sum(row["x_mode"] == "none" for row in specs) == 1


def test_x_context_is_causal_before_modified_bar():
    n = 220
    close = pd.Series(100 + np.sin(np.arange(n) / 4))
    frame = pd.DataFrame({
        "close": close, "high": close + 1, "low": close - 1,
        "volume": 1000 + np.arange(n) % 7, "atr": 1.0,
    })
    spec = candidate_specs()[1]
    first = x_context(frame, spec)
    frame.loc[n - 1, ["close", "high", "low", "volume"]] = [500, 510, 490, 1_000_000]
    second = x_context(frame, spec)
    np.testing.assert_array_equal(first[0][:-1], second[0][:-1])
    np.testing.assert_array_equal(first[1][:-1], second[1][:-1])
