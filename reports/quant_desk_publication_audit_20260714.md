# Quant-desk simulation publication audit

## Executive conclusion

The post is a useful syllabus, not an institutional production stack. Its best
transferable ideas for the ES strategies are proper probability calibration,
empirical execution modeling, regime-preserving simulation, jump/EVT stress,
and portfolio tail dependence. It does not provide evidence that Monte Carlo,
particle filters, copulas, or generative models create entry alpha for C11.

The production C11 remains unchanged. Its frozen SHA-256 is
`f78e404927533c2f37e3b391f3d0e82f98eadeafdb8a90edf637ef90de8611d6`.

## Publication audit

| Publication | Verified contribution | Transfer to our strategies | Decision |
|---|---|---|---|
| Dalen, *Toward Black-Scholes for Prediction Markets* | Logit jump-diffusion framework for binary contracts | Jump-risk concepts only; its contract-price dynamics are not ES dynamics | Defer |
| Saguillo et al., *Probabilistic Forest* | Logical/combinatorial arbitrage across related prediction contracts | No direct C11 application | Reject for ES |
| Madrigal-Cianci et al., *Bayesian Inverse Problems* | Infers latent beliefs from mixtures of informed, noisy, heavy-tailed, and adversarial flow | Motivates latent order-flow monitoring, but requires an ES-specific observation model | Research |
| Farmer, Patelli & Zovko (2005) | Zero-intelligence order-book model links order flow to spreads and volatility | Use the empirical ES book to model fills and slippage; do not use the post's toy ABM | Use now |
| Gode & Sunder (1993) | Budget constraints can yield high allocative efficiency despite zero-intelligence bids | Conceptual validation only; not a realistic ES path generator | Context only |
| Kyle (1985); Glosten & Milgrom (1985) | Price impact and adverse-selection foundations | Condition execution costs on size, imbalance, spread, depth, and volatility | Use now |
| Hoffman & Gelman (2014) | NUTS for efficient Bayesian posterior sampling | Useful only when we define a justified Bayesian model | Conditional |
| Merton (1976) | Jump-diffusion pricing framework | Add gap/jump stress to risk simulations | Use now |
| Linzer (2013); Gelman et al. (2020) | Dynamic hierarchical election forecasting | Supports slow, pooled updates; does not justify rapid C11 parameter refits | Monitor only |
| Aas et al. (2009) | Pair-copula/vine construction for multivariate dependence | Model joint tails only after multiple independently validated sleeves exist | Portfolio only |
| Wiese et al. (2020); Kidger et al. (2021) | Flexible generative time-series models | High estimation and validation burden; no current incremental C11 evidence | Defer |

## Material corrections to the post

1. A Brier score is a proper score, not a calibration-only metric. Universal
   labels such as “below 0.20 is good” are invalid without the event base rate
   and a reference forecast.
2. Forecasting with a physical drift and pricing under a risk-neutral measure
   are different tasks; the post mixes them.
3. Importance sampling gains depend on a correct likelihood ratio and a useful
   proposal. “100 samples beat one million” is not a general result.
4. The displayed stratified estimator does not estimate its standard error from
   within-stratum sampling variance.
5. Antithetic, control-variate, and stratification gains do not universally
   multiply to 100-500x.
6. A Gaussian copula has zero *asymptotic tail dependence*; it does not assign
   zero probability to joint extremes. The 2008 causal claim is oversimplified.
7. The toy ABM is not a calibrated limit-order-book simulator and cannot support
   production fill, impact, or P&L claims.

## Evidence from our strategies

- The exact current TradingView C11 sample produced `$126,905`, with 469 trades,
  but covers only 247 daily observations. That is strong recent performance and
  weak evidence for a stable multi-year distribution at the same time.
- Five-year transport of the tested X-derived variant had a 59.8% drawdown and
  was highly sensitive to execution. One extra tick reduced net P&L from
  `$165,747.50` to `$92,797.50`; four extra ticks made it negative.
- One million regime-block paths put baseline probability of a 30% drawdown at
  37.95% and 50% capital impairment at 5.62%. Under the defined execution/jump
  stress those rose to 90.92% and 52.71%, respectively.
- The exact TradingView X chop veto reduced recent C11 net P&L, profit factor,
  and drawdown quality. It remains rejected.

## Implementation priorities

1. **Execution truth:** aggregate reconstructed MBP-1 into causal spread, depth,
   imbalance, and volatility buckets; estimate marketable-fill and adverse-
   excursion distributions. Replace fixed-tick stress with sampled empirical
   costs.
2. **Probability truth:** for every ML gate, persist time-fold Brier score, log
   loss, reliability, calibration slope/intercept, and base-rate benchmark.
3. **Capital truth:** retain regime block bootstrap; add EVT/jump and reverse
   stress. Set size from stressed drawdown tolerance, not recent TV return.
4. **Adaptation discipline:** use a slow latent-risk filter to reduce exposure or
   alert. Do not let it retrain C11 parameters in real time; our prior rolling
   refit tests did not justify that complexity.
5. **Portfolio tails:** fit t/vine dependence only when strategy histories are
   long enough and genuinely distinct. Compare against synchronized-loss stress.

## Sources

- https://econpapers.repec.org/paper/arxpapers/2510.15205.htm
- https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.27
- https://arxiv.org/abs/2601.18815
- https://pmc.ncbi.nlm.nih.gov/articles/PMC548562/
- https://ideas.repec.org/a/ucp/jpolec/v101y1993i1p119-37.html
- https://econpapers.repec.org/article/ecmemetrp/v_3a53_3ay_3a1985_3ai_3a6_3ap_3a1315-35.htm
- https://www.jmlr.org/papers/v15/hoffman14a.html
- https://econpapers.repec.org/article/eeejfinec/v_3a3_3ay_3a1976_3ai_3a1-2_3ap_3a125-144.htm
- https://hdsr.mitpress.mit.edu/pub/nw1dzd02/release/2
- https://portal.fis.tum.de/en/publications/pair-copula-constructions-of-multiple-dependence/
- https://arxiv.org/abs/1907.06673
- https://proceedings.mlr.press/v139/kidger21b.html
