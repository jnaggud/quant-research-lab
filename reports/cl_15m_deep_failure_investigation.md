# CL1! Deep Failure Investigation

- Trades: `288`
- Net: `$91,187.15`
- Win rate: `48.61%`
- Profit factor: `2.308`

## Interpretation

This report separates pre-entry filterable conditions from ex-post failure behavior. Filters can be tested directly; ex-post labels identify exit/entry timing issues but cannot be used as live filters without a predictive proxy.

## Worst Single Conditions To Filter

| filter | removed_trades | removed_net | kept_net | net_delta | kept_pf | kept_win_rate |
|---|---|---|---|---|---|---|
| atr_too_quiet | 54 | $3,240.26 | $87,946.89 | $-3,240.26 | 2.65 | 48.72 |
| against_daily | 62 | $8,557.46 | $82,629.69 | $-8,557.46 | 2.68 | 51.77 |
| sleeve_reversion | 46 | $17,980.48 | $73,206.66 | $-17,980.48 | 2.17 | 43.80 |
| low_adx | 46 | $17,980.48 | $73,206.66 | $-17,980.48 | 2.17 | 43.80 |
| against_h4 | 74 | $21,094.96 | $70,092.19 | $-21,094.96 | 2.20 | 45.33 |
| atr_too_hot | 89 | $25,062.93 | $66,124.22 | $-25,062.93 | 2.46 | 50.75 |
| volume_extreme | 48 | $29,134.49 | $62,052.66 | $-29,134.49 | 2.16 | 49.17 |
| outside_primary_ny | 147 | $45,132.29 | $46,054.86 | $-45,132.29 | 2.25 | 43.97 |
| far_from_vwap | 168 | $52,383.57 | $38,803.57 | $-52,383.57 | 2.39 | 46.67 |
| core_trend | 242 | $73,206.66 | $17,980.48 | $-73,206.66 | 3.48 | 73.91 |
| high_adx | 242 | $73,206.66 | $17,980.48 | $-73,206.66 | 3.48 | 73.91 |

## Worst Two-Condition Intersections

| filter | removed_trades | removed_net | kept_net | net_delta | kept_pf | kept_win_rate |
|---|---|---|---|---|---|---|
| far_from_vwap AND against_daily | 42 | $-5,914.48 | $97,101.62 | $5,914.48 | 2.74 | 51.22 |
| atr_too_hot AND against_daily | 22 | $-4,285.00 | $95,472.14 | $4,285.00 | 2.57 | 49.62 |
| volume_extreme AND against_daily | 12 | $-1,478.78 | $92,665.93 | $1,478.78 | 2.47 | 49.28 |
| atr_too_quiet AND far_from_vwap | 28 | $-335.56 | $91,522.70 | $335.56 | 2.51 | 48.85 |
| atr_too_quiet AND against_daily | 11 | $-328.64 | $91,515.79 | $328.64 | 2.41 | 48.38 |
| atr_too_hot AND outside_primary_ny | 12 | $262.80 | $90,924.35 | $-262.80 | 2.37 | 48.19 |
| atr_too_hot AND against_h4 | 23 | $1,870.46 | $89,316.69 | $-1,870.46 | 2.38 | 48.30 |
| volume_extreme AND against_h4 | 9 | $2,312.42 | $88,874.73 | $-2,312.42 | 2.33 | 48.03 |
| core_trend AND atr_too_quiet | 54 | $3,240.26 | $87,946.89 | $-3,240.26 | 2.65 | 48.72 |
| high_adx AND atr_too_quiet | 54 | $3,240.26 | $87,946.89 | $-3,240.26 | 2.65 | 48.72 |
| atr_too_quiet AND against_h4 | 14 | $4,420.17 | $86,766.98 | $-4,420.17 | 2.27 | 47.45 |
| atr_too_quiet AND outside_primary_ny | 49 | $5,135.26 | $86,051.89 | $-5,135.26 | 2.56 | 48.12 |
| sleeve_reversion AND far_from_vwap | 23 | $6,204.34 | $84,982.80 | $-6,204.34 | 2.32 | 46.42 |
| low_adx AND far_from_vwap | 23 | $6,204.34 | $84,982.80 | $-6,204.34 | 2.32 | 46.42 |
| sleeve_reversion AND against_h4 | 15 | $8,309.67 | $82,877.48 | $-8,309.67 | 2.20 | 46.89 |

## Worst Groups By Session

| key | trades | net | win_rate | profit_factor | avg_mae | avg_mfe |
|---|---|---|---|---|---|---|
| post_ny_15_18 | 9 | $441.18 | 55.56 | 1.37 | $382.22 | $630.00 |
| pre_ny_06_08 | 54 | $9,042.85 | 42.59 | 1.50 | $697.04 | $1,013.70 |
| ny_midday_12_14 | 39 | $14,755.92 | 35.90 | 2.85 | $567.18 | $1,533.08 |
| ny_morning_09_11 | 60 | $27,568.72 | 50.00 | 3.17 | $589.33 | $1,223.67 |
| overnight_00_05 | 119 | $32,442.95 | 52.10 | 2.18 | $469.33 | $910.17 |

## Worst Groups By Side/Kind

| key | trades | net | win_rate | profit_factor | avg_mae | avg_mfe |
|---|---|---|---|---|---|---|
| short_core | 126 | $10,421.38 | 39.68 | 1.31 | $438.89 | $728.41 |
| long_sleeve | 45 | $17,664.28 | 73.33 | 3.44 | $659.33 | $916.44 |
| long_core | 116 | $62,785.28 | 48.28 | 3.14 | $661.81 | $1,560.78 |

## Worst Groups By Exit Reason

| key | trades | net | win_rate | profit_factor | avg_mae | avg_mfe |
|---|---|---|---|---|---|---|
| momentum | 190 | $-39,080.00 | 30.53 | 0.34 | $539.89 | $704.16 |
| stop | 8 | $-8,950.62 | 0.00 | 0.00 | $1,392.50 | $337.50 |
| time | 8 | $3,810.00 | 62.50 | 5.21 | $1,371.25 | $1,531.25 |
| vwap_reversion | 16 | $5,180.00 | 68.75 | 7.95 | $688.75 | $651.25 |
| target | 66 | $130,227.77 | 100.00 | 0.00 | $398.48 | $2,353.18 |

## Worst VWAP Distance Buckets

| key | trades | net | win_rate | profit_factor | avg_mae | avg_mfe |
|---|---|---|---|---|---|---|
| vwap_0_0.5 | 23 | $1,058.31 | 30.43 | 1.16 | $454.35 | $618.26 |
| vwap_1.5_2.5 | 111 | $5,019.11 | 47.75 | 1.17 | $506.94 | $786.49 |
| vwap_0.5_1 | 30 | $18,816.77 | 63.33 | 6.35 | $503.33 | $1,126.00 |
| vwap_1_1.5 | 67 | $18,928.49 | 44.78 | 2.07 | $690.90 | $1,117.91 |
| vwap_gt_2.5 | 57 | $47,364.47 | 54.39 | 5.05 | $594.74 | $1,829.30 |

## Worst ATR Regime Buckets

| key | trades | net | win_rate | profit_factor | avg_mae | avg_mfe |
|---|---|---|---|---|---|---|
| atr_lt_0.8 | 47 | $5,900.74 | 51.06 | 1.46 | $474.26 | $999.36 |
| atr_1.2_1.5 | 53 | $10,815.98 | 41.51 | 1.89 | $621.70 | $1,080.38 |
| atr_gt_1.5 | 34 | $14,826.94 | 50.00 | 2.26 | $623.82 | $1,311.18 |
| atr_1_1.2 | 65 | $23,162.43 | 41.54 | 2.93 | $482.77 | $980.46 |
| atr_0.8_1 | 89 | $36,481.04 | 56.18 | 2.73 | $608.76 | $1,145.28 |

## Next Tests

1. Convert the best pre-entry filter rows into candidate strategy branches and run walk-forward validation.
2. For `gave_back_profit`, test predictive proxies such as MFE-based trailing after 0.8–1.2 ATR favorable excursion.
3. For `immediate_adverse`, test entry delay/confirmation filters rather than wider stops.
