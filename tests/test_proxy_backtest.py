from __future__ import annotations

import pandas as pd

from vixharvest.backtest.proxy import build_stf_proxy_index, run_proxy_backtest
from vixharvest.signals.regimes import SignalParameters


PARAMETERS = SignalParameters(0.85, 0.05, 5)


def _contracts() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-13", "2025-01-14", "2025-01-16", "2025-01-17"])
    rows = []
    for expiry, settlements in {
        "2025-01-15": [20.0, 20.0, None, None],
        "2025-02-12": [21.0, 21.5, 22.0, 22.5],
        "2025-03-12": [23.0, 23.5, 24.0, 24.5],
    }.items():
        for date, settle in zip(dates, settlements, strict=True):
            if settle is not None:
                rows.append(
                    {
                        "date": date,
                        "contract": f"VX_{expiry}",
                        "expiry": pd.Timestamp(expiry),
                        "settle": settle,
                    }
                )
    return pd.DataFrame(rows)


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-16", "2025-01-17"]),
            "ratio_vix_vix3m": [0.84, 0.84],
            "slope_m1m2": [0.06, 0.06],
            "ratio_vix_vix3m_delta5": [0.0, 0.0],
            "vix9d_vix": [0.90, 0.90],
        }
    )


def test_stf_proxy_applies_previous_day_roll_weight_to_returns():
    stf = build_stf_proxy_index(_contracts())

    assert stf["date"].tolist() == [pd.Timestamp("2025-01-16"), pd.Timestamp("2025-01-17")]
    assert stf.loc[0, "underlying_return"] == 0.0
    expected_return = stf.loc[0, "near_weight"] * (22.5 / 22.0 - 1) + (
        1 - stf.loc[0, "near_weight"]
    ) * (24.5 / 24.0 - 1)
    assert stf.loc[1, "underlying_return"] == expected_return


def test_proxy_backtest_executes_harvest_on_the_next_row():
    result = run_proxy_backtest(_panel(), _contracts(), parameters=PARAMETERS)

    assert result["harvest_signal"].tolist() == [True, True]
    assert result["filtered_position"].tolist() == [False, True]
    assert result.loc[0, "filtered_return"] == 0.0
    assert result.loc[1, "filtered_return"] == -result.loc[1, "underlying_return"]