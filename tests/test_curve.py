from __future__ import annotations

import pandas as pd
import pytest

from vixharvest.curve.calendar import CalendarValidationError, build_expiry_calendar
from vixharvest.curve.constant_maturity import CurveConstructionError, compute_vx30
from vixharvest.curve.features import build_signal_panel


def test_expiry_calendar_derives_contract_lifetimes_and_persists(tmp_path):
    contracts = pd.DataFrame(
        {
            "contract": ["VX_2025-01-22", "VX_2025-01-22", "VX_2025-02-19", "VX_2025-02-19"],
            "date": ["2025-01-20", "2025-01-22", "2025-01-20", "2025-02-19"],
            "expiry": ["2025-01-22", "2025-01-22", "2025-02-19", "2025-02-19"],
        }
    )

    calendar = build_expiry_calendar(contracts, data_dir=tmp_path / "data")

    assert calendar.to_dict("records") == [
        {
            "contract": "VX_2025-01-22",
            "expiry": pd.Timestamp("2025-01-22"),
            "first_date": pd.Timestamp("2025-01-20"),
            "last_date": pd.Timestamp("2025-01-22"),
            "n_obs": 2,
        },
        {
            "contract": "VX_2025-02-19",
            "expiry": pd.Timestamp("2025-02-19"),
            "first_date": pd.Timestamp("2025-01-20"),
            "last_date": pd.Timestamp("2025-02-19"),
            "n_obs": 2,
        },
    ]
    assert (tmp_path / "data" / "interim" / "expiry_calendar.parquet").exists()


def test_expiry_calendar_rejects_expired_contract_without_final_observation():
    contracts = pd.DataFrame(
        {
            "contract": ["VX_2025-01-22", "VX_2025-02-19"],
            "date": ["2025-01-10", "2025-02-19"],
            "expiry": ["2025-01-22", "2025-02-19"],
        }
    )

    with pytest.raises(CalendarValidationError, match="too far before expiry"):
        build_expiry_calendar(contracts, persist=False)


def test_vx30_uses_calendar_day_weights_and_promotes_m2_after_roll():
    contracts = pd.DataFrame(
        {
            "date": ["2025-01-20", "2025-01-20", "2025-01-23", "2025-01-23"],
            "contract": ["VX_2025-01-22", "VX_2025-02-19", "VX_2025-02-19", "VX_2025-03-19"],
            "expiry": ["2025-01-22", "2025-02-19", "2025-02-19", "2025-03-19"],
            "settle": [20.0, 22.0, 21.0, 23.0],
        }
    )
    calendar = pd.DataFrame(
        {
            "contract": ["VX_2025-01-22", "VX_2025-02-19", "VX_2025-03-19"],
            "expiry": ["2025-01-22", "2025-02-19", "2025-03-19"],
        }
    )

    curve = compute_vx30(contracts, calendar)

    assert curve.loc[0, "vx30"] == pytest.approx(22.0)
    assert curve.loc[1, "m1_contract"] == "VX_2025-02-19"
    assert curve.loc[1, "vx30"] == pytest.approx(21.0 * 25 / 28 + 23.0 * 3 / 28)


def test_vx30_honors_a_holiday_shifted_tuesday_expiry():
    contracts = pd.DataFrame(
        {
            "date": ["2025-03-17", "2025-03-17"],
            "contract": ["VX_2025-03-18", "VX_2025-04-16"],
            "expiry": ["2025-03-18", "2025-04-16"],
            "settle": [22.0, 24.0],
        }
    )
    calendar = contracts[["contract", "expiry"]].copy()

    curve = compute_vx30(contracts, calendar)

    assert curve.loc[0, "m1_expiry"] == pd.Timestamp("2025-03-18")
    assert curve.loc[0, "vx30"] == pytest.approx(24.0)


def test_vx30_rejects_a_date_without_m2():
    contracts = pd.DataFrame(
        {
            "date": ["2025-01-20"],
            "contract": ["VX_2025-01-22"],
            "expiry": ["2025-01-22"],
            "settle": [20.0],
        }
    )
    calendar = contracts[["contract", "expiry"]].copy()

    with pytest.raises(CurveConstructionError, match="Fewer than two live VX contracts"):
        compute_vx30(contracts, calendar)


def test_feature_panel_computes_curve_features_roll_yield_and_ratio_deltas(tmp_path):
    data_dir = tmp_path / "data"
    interim_dir = data_dir / "interim"
    interim_dir.mkdir(parents=True)
    dates = pd.DatetimeIndex(
        [
            "2025-01-13",
            "2025-01-14",
            "2025-01-15",
            "2025-01-16",
            "2025-01-17",
            "2025-01-21",
            "2025-01-22",
            "2025-01-23",
        ]
    )
    indices = pd.DataFrame(
        {
            "date": dates,
            "vix_close": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0],
            "vix3m_close": [20.0] * len(dates),
            "vix9d_close": [10.0] * len(dates),
        }
    )
    contracts = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": dates[:7],
                    "contract": "VX_2025-01-22",
                    "expiry": "2025-01-22",
                    "settle": 20.0,
                }
            ),
            pd.DataFrame(
                {
                    "date": dates,
                    "contract": "VX_2025-02-19",
                    "expiry": "2025-02-19",
                    "settle": 21.0,
                }
            ),
            pd.DataFrame(
                {
                    "date": dates,
                    "contract": "VX_2025-03-19",
                    "expiry": "2025-03-19",
                    "settle": 23.0,
                }
            ),
        ],
        ignore_index=True,
    )
    indices.to_parquet(interim_dir / "indices.parquet", index=False)
    contracts.to_parquet(interim_dir / "vx_contracts.parquet", index=False)

    panel = build_signal_panel(data_dir=data_dir)
    post_roll = panel.loc[panel["date"] == pd.Timestamp("2025-01-23")].iloc[0]

    assert panel.loc[0, "basis_m1"] == pytest.approx(10.0)
    assert panel.loc[0, "slope_m1m2"] == pytest.approx(0.05)
    assert panel.loc[5, "ratio_vix_vix3m_delta5"] == pytest.approx(0.25)
    assert post_roll["roll_yield_daily"] == pytest.approx((21.0 - 23.0) / 23.0 / 19)
    assert (data_dir / "processed" / "signal_panel.parquet").exists()