from __future__ import annotations

import pytest

from vixharvest.signals.regimes import (
    SignalInputError,
    SignalParameters,
    classify_regime,
    load_signal_parameters,
)


PARAMETERS = SignalParameters(
    theta_1_ratio=0.85,
    theta_2_slope=0.05,
    momentum_lookback_days=5,
)


def _row(**overrides: float) -> dict[str, float]:
    row = {
        "ratio_vix_vix3m": 0.84,
        "slope_m1m2": 0.06,
        "ratio_vix_vix3m_delta5": 0.0,
        "vix9d_vix": 0.90,
    }
    row.update(overrides)
    return row


def test_loads_frozen_completed_fit_parameters():
    assert load_signal_parameters() == PARAMETERS


def test_classifies_harvest_at_strictly_eligible_values():
    assert classify_regime(_row(), parameters=PARAMETERS) == "HARVEST"


@pytest.mark.parametrize(
    "overrides",
    [
        {"ratio_vix_vix3m": 0.85},
        {"slope_m1m2": 0.05},
        {"ratio_vix_vix3m_delta5": 0.001},
    ],
)
def test_harvest_requires_strict_thresholds_and_non_rising_ratio(overrides):
    assert classify_regime(_row(**overrides), parameters=PARAMETERS) == "NEUTRAL"


@pytest.mark.parametrize(
    "overrides",
    [
        {"ratio_vix_vix3m": 1.0},
        {"vix9d_vix": 1.0},
    ],
)
def test_stress_overrides_an_otherwise_harvest_eligible_row(overrides):
    assert classify_regime(_row(**overrides), parameters=PARAMETERS) == "STRESS"


def test_rejects_a_missing_required_feature():
    row = _row()
    del row["vix9d_vix"]

    with pytest.raises(SignalInputError, match="vix9d_vix"):
        classify_regime(row, parameters=PARAMETERS)