# Equity overlay using the VIX term-structure signal

Book: SPY total return. OOS 2018-01-02 to 2026-07-16. Thresholds frozen at 2013-2017. rf=0 on cash (conservative against overlays).
**Post-hoc disclosure:** the de-risking framing was formed after the short strategy failed its gate; this is an OOS evaluation of a fixed rule, not a new fit.

## Full period (2018-present)
| strategy | total_return | cagr | vol | sharpe | sortino | max_drawdown | calmar | pct_invested | downside_capture | upside_capture |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buy_hold | +218.2% | +14.6% | +19.2% | 0.81 | 0.99 | -33.7% | 0.43 | 100% | +100.0% | +100.0% |
| naive_vix_level | +53.8% | +5.2% | +9.6% | 0.57 | 0.58 | -14.7% | 0.35 | 64% | +45.8% | +44.3% |
| naive_inversion_only | +148.9% | +11.3% | +12.1% | 0.95 | 1.09 | -19.1% | 0.59 | 75% | +58.7% | +60.9% |
| overlay_stress_off | +155.2% | +11.6% | +11.6% | 1.01 | 1.14 | -22.0% | 0.53 | 74% | +56.6% | +59.3% |
| overlay_harvest_only | +6.2% | +0.7% | +4.1% | 0.19 | 0.10 | -16.0% | 0.04 | 18% | +10.9% | +10.1% |

## 2022 test (no-inversion bear and the predicted blind spot)
| strategy | total_return | cagr | vol | sharpe | sortino | max_drawdown | calmar | pct_invested | downside_capture | upside_capture |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buy_hold | -18.6% | -18.8% | +24.3% | -0.74 | -1.18 | -24.5% | -0.77 | 100% | +100.0% | +100.0% |
| naive_vix_level | -10.3% | -10.4% | +5.0% | -2.15 | -0.95 | -10.3% | -1.01 | 9% | +9.4% | +3.0% |
| naive_inversion_only | -10.5% | -10.5% | +16.6% | -0.59 | -0.77 | -17.4% | -0.60 | 62% | +54.7% | +54.7% |
| overlay_stress_off | -11.7% | -11.8% | +16.2% | -0.69 | -0.89 | -20.4% | -0.58 | 61% | +53.3% | +52.1% |
| overlay_harvest_only | -10.0% | -10.1% | +4.9% | -2.15 | -1.13 | -10.0% | -1.01 | 7% | +8.7% | +2.5% |

## How to read
- The bar is not maxDD reduction alone (trivial: hold less, drop less). It is risk-adjusted return (Sortino, Calmar) NET of foregone upside, vs buy-and-hold.
- `naive_inversion_only` is the control. The 3-condition signal must beat it or it adds nothing over a one-line rule.
- `downside_capture` low is good ONLY if `upside_capture` stays high; read together.
- `pct_invested` is the cost ledger: exposure given up to get the protection.
