# Attribution - Sprint 3 filtered short (OOS 2018-present)

Forensics on a NO-GO result. Decomposes realized daily short P&L into carry vs
directional (mechanical beta=1: `carry = idx_ret - vx30_ret`) and by transition
bucket. No parameter is chosen here.

## Headline reconciliation
- Geometric total return: **-40.40%**
- Arithmetic carry contribution (short): **+202.42%**
- Arithmetic directional contribution (short): **-239.55%**
- Compounding interaction (geo - arith): -3.28%
- Robustness: train daily beta(idx~vx30) = 0.970; beta-fit carry +195.35%, directional -232.48%

The carry contribution is the p=1.0000 edge, realized. The directional
contribution is the mean-reversion/spike cost the linear short cannot avoid.

## By transition bucket
| bucket | days | total_short_pnl | total_carry | total_directional | mean_short_pnl | worst_day |
| --- | --- | --- | --- | --- | --- | --- |
| harvest_continues | 255 | +221.19% | +134.45% | +86.75% | +0.87% | -5.57% |
| exit_to_neutral | 122 | -179.24% | +58.37% | -237.61% | -1.47% | -9.94% |
| exit_to_stress | 16 | -79.08% | +9.61% | -88.69% | -4.94% | -13.31% |

`exit_to_stress` is the t+1 lag-day cost: short into the flag, out next session.

## By year
| year | active_days | short_pnl_arith | carry | directional | stress_exit_days | stress_exit_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | 43 | -16.32% | +14.49% | -30.81% | 3 | -15.45% |
| 2019 | 45 | -5.31% | +24.75% | -30.06% | 2 | -12.94% |
| 2020 | 36 | +12.81% | +22.04% | -9.23% | 0 | +0.00% |
| 2021 | 103 | +11.88% | +55.15% | -43.27% | 1 | -4.96% |
| 2022 | 17 | -37.61% | +4.78% | -42.39% | 1 | -2.03% |
| 2023 | 52 | +26.63% | +31.23% | -4.60% | 4 | -12.70% |
| 2024 | 18 | -15.15% | +8.28% | -23.43% | 1 | -0.11% |
| 2025 | 50 | -5.96% | +28.41% | -34.36% | 2 | -20.50% |
| 2026 | 29 | -8.10% | +13.30% | -21.40% | 2 | -10.39% |

## Worst 15 days (29% of all losing-day P&L)
| date | regime | position_regime | bucket | idx_ret_daily | carry_daily | directional_daily | short_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-10-10 | STRESS | HARVEST | exit_to_stress | +13.31% | -0.15% | +13.47% | -13.31% |
| 2022-02-10 | NEUTRAL | HARVEST | exit_to_neutral | +9.94% | +0.61% | +9.33% | -9.94% |
| 2022-04-05 | NEUTRAL | HARVEST | exit_to_neutral | +8.99% | -0.31% | +9.30% | -8.99% |
| 2023-04-25 | STRESS | HARVEST | exit_to_stress | +8.43% | -0.13% | +8.56% | -8.43% |
| 2018-01-29 | STRESS | HARVEST | exit_to_stress | +8.34% | -0.30% | +8.63% | -8.34% |
| 2022-01-05 | NEUTRAL | HARVEST | exit_to_neutral | +8.29% | +0.14% | +8.16% | -8.29% |
| 2026-06-05 | STRESS | HARVEST | exit_to_stress | +7.85% | -0.63% | +8.48% | -7.85% |
| 2022-04-21 | NEUTRAL | HARVEST | exit_to_neutral | +7.39% | +0.29% | +7.10% | -7.39% |
| 2025-01-27 | STRESS | HARVEST | exit_to_stress | +7.19% | -0.10% | +7.29% | -7.19% |
| 2019-12-02 | STRESS | HARVEST | exit_to_stress | +6.56% | -1.08% | +7.64% | -6.56% |
| 2022-01-13 | NEUTRAL | HARVEST | exit_to_neutral | +6.49% | +0.11% | +6.38% | -6.49% |
| 2021-07-08 | NEUTRAL | HARVEST | exit_to_neutral | +6.49% | -0.28% | +6.77% | -6.49% |
| 2019-09-24 | STRESS | HARVEST | exit_to_stress | +6.39% | +0.07% | +6.32% | -6.39% |
| 2019-09-20 | NEUTRAL | HARVEST | exit_to_neutral | +6.08% | -0.13% | +6.22% | -6.08% |
| 2018-08-10 | NEUTRAL | HARVEST | exit_to_neutral | +6.07% | -0.29% | +6.36% | -6.07% |
