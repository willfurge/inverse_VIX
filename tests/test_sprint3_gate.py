from __future__ import annotations

import pandas as pd
import pytest

from vixharvest.backtest.gate import StressWindow, evaluate_sprint3_gate
from vixharvest.signals.regimes import SignalParameters


PARAMETERS = SignalParameters(0.85, 0.05, 5)


def test_gate_is_no_go_when_a_stress_window_fails_loss_avoidance():
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2018-01-02", "2018-01-03", "2018-01-04"]),
            "underlying_return": [-0.02, 0.06, -0.10],
            "filtered_return": [0.02, -0.06, 0.10],
            "unconditional_return": [0.01, -0.10, 0.01],
            "flat_return": [0.0, 0.0, 0.0],
            "harvest_signal": [True, True, False],
            "filtered_position": [False, True, True],
            "is_backwardation": [False, True, False],
        }
    )
    windows = (StressWindow("synthetic stress", "2018-01-03", "2018-01-03"),)

    evaluation = evaluate_sprint3_gate(
        daily, PARAMETERS, fit_start="2013-01-16", stress_windows=windows
    )

    assert evaluation.verdict == "NO-GO"
    assert not evaluation.criteria.loc[
        evaluation.criteria["criterion"].str.contains("each applicable"), "passed"
    ].item()
    assert evaluation.stress_windows.loc[0, "avoided_loss"] == pytest.approx(0.40)