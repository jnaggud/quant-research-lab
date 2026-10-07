"""greeks.py — Black-76 option pricing, greeks, and implied-vol for options on FUTURES.

ES/NQ/CL/GC… options are options on the underlying *future*, so the correct model
is **Black-76** (Black 1976), not Black-Scholes-Merton (which assumes a spot with
carry). The difference: the underlying is the futures price F (no dividend/carry
term), and everything is discounted at exp(-rT).

Databento serves raw option trades/quotes but NOT IV/greeks — this module fills
that gap: given an option mid (or trade) price, the underlying future, strike,
time-to-expiry and rate, it solves for implied vol and returns the greeks.

Conventions
-----------
* T in YEARS (use 252 trading days or actual/365 — be consistent with your DTE).
* sigma is annualized vol (e.g. 0.18 = 18%).
* cp: +1 / 'C' / 'call' for calls, -1 / 'P' / 'put' for puts.
* Greeks are returned per 1.0 of underlying-price and per 1.0 vol / 1.0 year;
  multiply by the contract multiplier ($50 for ES) downstream for dollar greeks.
* Vega is per 1.00 (100 vol points) change; divide by 100 for per-1-vol-point.
* Theta is per YEAR; divide by 365 for per-calendar-day.
"""
from __future__ import annotations

import numpy as np

SQRT2PI = np.sqrt(2.0 * np.pi)


def _norm_cdf(x):
    # vectorized standard-normal CDF via erf (no scipy dependency)
    from math import erf  # scalar fallback
    if np.isscalar(x):
        return 0.5 * (1.0 + erf(x / np.sqrt(2.0)))
    x = np.asarray(x, dtype=float)
    # numpy-vectorized erf via np.vectorize(math.erf) is slow; use the
    # Abramowitz-Stegun-free identity through np.special if available, else erf map.
    try:
        from scipy.special import ndtr  # type: ignore
        return ndtr(x)
    except Exception:
        verf = np.vectorize(erf)
        return 0.5 * (1.0 + verf(x / np.sqrt(2.0)))


def _norm_pdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / SQRT2PI


def _cp_sign(cp):
    """+1 for calls, -1 for puts. Accepts scalar or array; numeric (+/-) or 'C'/'P'."""
    if isinstance(cp, str):
        return 1 if cp.upper().startswith("C") else -1
    arr = np.asarray(cp)
    if arr.ndim == 0:
        if arr.dtype.kind in ("U", "S", "O"):
            return 1 if str(arr).upper().startswith("C") else -1
        return 1 if float(arr) > 0 else -1
    if arr.dtype.kind in ("U", "S", "O"):
        upper = np.array([str(x).upper().startswith("C") for x in arr])
        return np.where(upper, 1, -1)
    return np.where(arr > 0, 1, -1)


def _d1_d2(F, K, T, sigma):
    F = np.asarray(F, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    vol_t = sigma * np.sqrt(T)
    # guard degenerate inputs
    vol_t = np.where(vol_t <= 0, np.nan, vol_t)
    d1 = (np.log(F / K) + 0.5 * sigma * sigma * T) / vol_t
    d2 = d1 - vol_t
    return d1, d2


def price(F, K, T, r, sigma, cp) -> float | np.ndarray:
    """Black-76 option price (premium in points of the underlying)."""
    s = _cp_sign(cp)
    d1, d2 = _d1_d2(F, K, T, sigma)
    disc = np.exp(-np.asarray(r, float) * np.asarray(T, float))
    F = np.asarray(F, float); K = np.asarray(K, float)
    call = disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    put = disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))
    return np.where(s > 0, call, put)


def greeks(F, K, T, r, sigma, cp) -> dict:
    """Return Black-76 greeks: delta, gamma, vega, theta, rho.

    delta : dPrice/dF
    gamma : d2Price/dF2
    vega  : dPrice/dsigma   (per 1.00 = 100 vol pts; /100 for per point)
    theta : dPrice/dt       (per YEAR; /365 for per calendar day; negative = decay)
    rho   : dPrice/dr
    """
    s = _cp_sign(cp)
    F = np.asarray(F, float); K = np.asarray(K, float)
    T = np.asarray(T, float); r = np.asarray(r, float)
    sigma = np.asarray(sigma, float)
    d1, d2 = _d1_d2(F, K, T, sigma)
    disc = np.exp(-r * T)
    pdf1 = _norm_pdf(d1)
    sqrtT = np.sqrt(T)

    delta = np.where(s > 0, disc * _norm_cdf(d1), -disc * _norm_cdf(-d1))
    gamma = disc * pdf1 / (F * sigma * sqrtT)
    vega = F * disc * pdf1 * sqrtT
    # Black-76 theta (per year)
    term_decay = -F * disc * pdf1 * sigma / (2.0 * sqrtT)
    theta_call = term_decay + r * disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    theta_put = term_decay + r * disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))
    theta = np.where(s > 0, theta_call, theta_put)
    rho_call = -T * disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    rho_put = -T * disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))
    rho = np.where(s > 0, rho_call, rho_put)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def implied_vol(opt_price, F, K, T, r, cp, lo=1e-4, hi=5.0, tol=1e-6, max_iter=100):
    """Solve Black-76 implied vol from an observed option price.

    Newton-Raphson seeded by a Brenner-Subrahmanyam ATM guess, with bisection
    fallback for robustness (vectorized; returns NaN where no solution, e.g. price
    below intrinsic). opt_price, F, K can be scalars or arrays of equal shape.
    """
    opt_price = np.asarray(opt_price, float)
    F = np.broadcast_to(np.asarray(F, float), opt_price.shape).astype(float)
    K = np.broadcast_to(np.asarray(K, float), opt_price.shape).astype(float)
    T = np.broadcast_to(np.asarray(T, float), opt_price.shape).astype(float)
    r = np.broadcast_to(np.asarray(r, float), opt_price.shape).astype(float)
    s = _cp_sign(cp)

    disc = np.exp(-r * T)
    intrinsic = disc * np.where(s > 0, np.maximum(F - K, 0.0), np.maximum(K - F, 0.0))
    valid = (opt_price > intrinsic + 1e-12) & (T > 0)

    # Brenner-Subrahmanyam ATM seed: sigma ≈ price/F * sqrt(2π/T)
    with np.errstate(all="ignore"):
        sigma = np.where(valid, (opt_price / (disc * F)) * np.sqrt(2 * np.pi / T), 0.2)
    sigma = np.clip(sigma, lo, hi)

    lo_a = np.full(opt_price.shape, lo)
    hi_a = np.full(opt_price.shape, hi)
    for _ in range(max_iter):
        p = price(F, K, T, r, sigma, cp)
        diff = p - opt_price
        v = greeks(F, K, T, r, sigma, cp)["vega"]
        # maintain bisection bracket
        lo_a = np.where(diff < 0, sigma, lo_a)
        hi_a = np.where(diff > 0, sigma, hi_a)
        with np.errstate(all="ignore"):
            step = diff / np.where(v > 1e-12, v, np.nan)
            newton = sigma - step
        # if Newton step leaves bracket or is nan, bisect
        use_bisect = ~np.isfinite(newton) | (newton <= lo_a) | (newton >= hi_a)
        sigma_new = np.where(use_bisect, 0.5 * (lo_a + hi_a), newton)
        if np.all(np.abs(sigma_new - sigma) < tol):
            sigma = sigma_new
            break
        sigma = sigma_new
    return np.where(valid, sigma, np.nan)


# --------------------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    import math
    F, K, T, r, sig = 6000.0, 6000.0, 30 / 365, 0.045, 0.18
    c = float(price(F, K, T, r, sig, "C"))
    p = float(price(F, K, T, r, sig, "P"))
    # put-call parity for Black-76: C - P = disc*(F - K)  (=0 at the money)
    parity = c - p - math.exp(-r * T) * (F - K)
    iv = float(implied_vol(c, F, K, T, r, "C"))
    g = greeks(F, K, T, r, sig, "C")
    print(f"ATM call={c:.4f}  put={p:.4f}  parity_resid={parity:.2e}")
    print(f"recovered IV={iv:.6f} (true {sig})  err={abs(iv-sig):.2e}")
    print(f"delta={float(g['delta']):.4f} gamma={float(g['gamma']):.6f} "
          f"vega/pt={float(g['vega'])/100:.4f} theta/day={float(g['theta'])/365:.4f}")
    assert abs(parity) < 1e-6, "parity broken"
    assert abs(iv - sig) < 1e-4, "IV solver off"
    print("greeks.py self-test PASSED")
