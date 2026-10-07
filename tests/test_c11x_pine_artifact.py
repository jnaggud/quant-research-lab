from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_c11x_is_separate_and_explicitly_rejected():
    original = (ROOT / "pine_strategies/JD_ES_15m_C11_Trend_Carry_200k_C1.pine").read_text()
    candidate = (ROOT / "pine_strategies/JD_ES_15m_C11X_Chop_Veto_C1.pine").read_text()
    assert 'strategy("JD ES 15m C11 Trend Carry' in original
    assert 'strategy("JD ES 15m C11-X Causal Chop Veto' in candidate
    assert "REJECTED 2026-07-14" in candidate
    assert "causalChop" in candidate
    assert original != candidate
