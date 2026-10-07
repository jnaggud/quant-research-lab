# C10 Archived Candidate W44 - 2026-06-21

Saved for later inspection, not promoted.

Source: `reports/c10_participation_carry_refine_200k_20260621.json`, rank 2, worker 44.

Pine: `pine_strategies/JD_ES_15m_C10_Participation_Carry_Archived_W44.pine`

## Local Metrics

| net | excess | PF | DD | trades | win rate | month | forward | core/cap/part |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| $123,210.00 | $80,960.00 | 1.804 | 9.67% | 443 | 45.824% | $16,515.00 | -$2,627.50 | 222/164/57 |

## Why Archived

This candidate beat C9 on net, excess, profit factor, and current-month net, but failed:

| gate | reason |
| --- | --- |
| `dd_le_c9` | DD was 9.67% vs C9 at 9.12%. |
| `forward_gt_c9` | Forward was -$2,627.50 vs C9 at -$2,040.00. |
| `forward_non_negative` | Forward remained negative. |

It is useful as a high-net/high-PF reference for C11 design, but C9 remains the active champion.
