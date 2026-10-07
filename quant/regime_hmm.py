"""regime_hmm.py — Markov (Hidden Markov Model) regime for the ES pipeline.

Replaces the strategy's lagging EMA-crossover regime with a data-driven Markov
regime that (a) learns states from returns/volatility/trend and (b) yields
TRANSITION PROBABILITIES so we can anticipate regime shifts.

CAUSALITY is the whole game here (the audit's #1 lesson):
  * The HMM is FIT ON TRAINING DATA ONLY.
  * States are decoded with the FORWARD algorithm (filtering): the state at bar t
    uses only observations 1..t. hmmlearn's `predict`/`predict_proba` use Viterbi/
    full-posterior (which peek at the whole sequence) — we do NOT use those for the
    live regime; we run the forward recursion ourselves.

States are mapped to {+1 bull, 0 neutral, -1 bear} by their fitted mean return.
"""
from __future__ import annotations

import numpy as np
from hmmlearn import hmm
from scipy.special import logsumexp


def _obs(close: np.ndarray) -> np.ndarray:
    """Observation matrix: [log-return, rolling vol, trend slope]. Causal."""
    import pandas as pd
    c = pd.Series(close)
    r = np.log(c / c.shift(1))
    vol = r.rolling(20).std()
    slope = (c - c.shift(20)) / c.shift(20)
    X = np.column_stack([r, vol, slope])
    return X


def fit(close_train: np.ndarray, n_states: int = 3, seed: int = 0):
    """Fit a Gaussian HMM on TRAIN observations. Returns (model, state->sign map)."""
    X = _obs(close_train)
    ok = ~np.isnan(X).any(axis=1)
    Xk = X[ok]
    model = hmm.GaussianHMM(n_components=n_states, covariance_type="diag",
                            n_iter=100, random_state=seed)
    model.fit(Xk)
    # map each state to a sign by its mean log-return (feature 0)
    order = np.argsort(model.means_[:, 0])     # ascending mean return
    sign = {}
    sign[order[0]] = -1     # lowest mean return -> bear
    sign[order[-1]] = 1     # highest -> bull
    for s in order[1:-1]:
        sign[s] = 0         # middle states -> neutral
    return model, sign


def decode_causal(model, close: np.ndarray):
    """Forward-filtered state path for `close` using a fitted model — CAUSAL.

    Returns (states, posterior[T,S]) where state[t] depends only on obs 1..t.
    """
    X = _obs(close)
    # fill warmup NaNs with the column means so emission probs are defined; the
    # first ~20 bars are unreliable regardless (handled by embargo downstream).
    col_mean = np.nanmean(X, axis=0)
    Xf = np.where(np.isnan(X), col_mean, X)
    logB = model._compute_log_likelihood(Xf)         # (T, S) log emission
    log_start = np.log(model.startprob_ + 1e-12)
    log_A = np.log(model.transmat_ + 1e-12)
    T, S = logB.shape
    log_alpha = np.empty((T, S))
    log_alpha[0] = log_start + logB[0]
    for t in range(1, T):
        for i in range(S):
            log_alpha[t, i] = logsumexp(log_alpha[t - 1] + log_A[:, i]) + logB[t, i]
    post = np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))
    return np.argmax(post, axis=1), post


def regime_series(model, sign_map: dict, close: np.ndarray) -> np.ndarray:
    """Causal regime in {+1,0,-1} for `close`."""
    states, _ = decode_causal(model, close)
    return np.array([sign_map.get(int(s), 0) for s in states], dtype=float)


if __name__ == "__main__":
    import pandas as pd
    rng = np.random.default_rng(1)
    # synthetic: bull drift, then bear, then chop — HMM should separate them
    seg = [np.cumsum(rng.normal(0.5, 2, 400)) + 5000,
           5000 + 200 + np.cumsum(rng.normal(-0.6, 2, 400)),
           5000 - 40 + np.cumsum(rng.normal(0.0, 4, 400))]
    close = np.concatenate(seg)
    train = close[:800]
    model, sign = fit(train, n_states=3, seed=0)
    reg = regime_series(model, sign, close)
    # check the segments get the right majority sign
    for name, lo, hi, exp in [("bull", 50, 380, 1), ("bear", 420, 780, -1)]:
        maj = np.sign(np.mean(reg[lo:hi]))
        print(f"  {name} segment majority regime sign = {maj:+.0f} (expect {exp:+d})")
    # causality check: state[t] unchanged when future bars are appended
    s_full, _ = decode_causal(model, close)
    s_part, _ = decode_causal(model, close[:600])
    diff = int(np.sum(s_full[:600] != s_part))
    print(f"  causal decode mismatches in first 600: {diff} (want 0)")
    assert diff == 0, "HMM decode is not causal!"
    print("regime_hmm self-test PASSED")
