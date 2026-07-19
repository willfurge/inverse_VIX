from __future__ import annotations

import pandas as pd
import pytest

from vixharvest.backtest.engine import BacktestInputError, run_backtest


def test_signal_changes_position_on_the_next_observed_trading_day():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "harvest_signal": [False, True, False],
            "underlying_return": [0.10, 0.20, -0.30],
        }
    )

    result = run_backtest(frame)

    assert result["filtered_position"].tolist() == [False, False, True]
    assert result["filtered_return"].tolist() == [0.0, 0.0, 0.30]
    assert result["unconditional_return"].tolist() == [-0.10, -0.20, 0.30]


def test_rejects_non_boolean_signal_values():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "harvest_signal": [1],
            "underlying_return": [0.01],
        }
    )

    with pytest.raises(BacktestInputError, match="Boolean"):
        run_backtest(frame)