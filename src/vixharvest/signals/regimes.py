"""HARVEST / NEUTRAL / STRESS regime classification for the Sprint 3 gate."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Mapping

import yaml


class SignalConfigurationError(ValueError):
    """Raised when the frozen signal configuration is incomplete or invalid."""


class SignalInputError(ValueError):
    """Raised when a feature row cannot be classified safely."""


@dataclass(frozen=True)
class SignalParameters:
    """Frozen parameters selected before out-of-sample gate evaluation."""

    theta_1_ratio: float
    theta_2_slope: float
    momentum_lookback_days: int


def load_signal_parameters(config_path: Path | None = None) -> SignalParameters:
    """Load and validate the frozen Sprint 3 signal parameters."""
    path = config_path or _repo_root() / "config" / "signals.yaml"
    with path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise SignalConfigurationError("Signal configuration must be a mapping.")

    try:
        thresholds = config["thresholds"]
        parameters = SignalParameters(
            theta_1_ratio=float(thresholds["theta_1_ratio"]),
            theta_2_slope=float(thresholds["theta_2_slope"]),
            momentum_lookback_days=int(thresholds["momentum_lookback_days"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SignalConfigurationError("Signal thresholds are missing or invalid.") from exc

    if not math.isfinite(parameters.theta_1_ratio) or not math.isfinite(parameters.theta_2_slope):
        raise SignalConfigurationError("Signal thresholds must be finite.")
    if parameters.momentum_lookback_days <= 0:
        raise SignalConfigurationError("Momentum lookback must be positive.")
    return parameters


def classify_regime(
    panel_row: Mapping[str, object], *, parameters: SignalParameters | None = None
) -> str:
    """Classify an EOD feature row with STRESS taking priority over HARVEST."""
    values = {
        name: _finite_feature(panel_row, name)
        for name in ("ratio_vix_vix3m", "slope_m1m2", "ratio_vix_vix3m_delta5", "vix9d_vix")
    }
    frozen = parameters or load_signal_parameters()

    if values["ratio_vix_vix3m"] >= 1.0 or values["vix9d_vix"] >= 1.0:
        return "STRESS"
    if (
        values["ratio_vix_vix3m"] < frozen.theta_1_ratio
        and values["slope_m1m2"] > frozen.theta_2_slope
        and values["ratio_vix_vix3m_delta5"] <= 0.0
    ):
        return "HARVEST"
    return "NEUTRAL"


def _finite_feature(panel_row: Mapping[str, object], name: str) -> float:
    try:
        value = float(panel_row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise SignalInputError(f"Missing or invalid feature: {name}") from exc
    if not math.isfinite(value):
        raise SignalInputError(f"Feature must be finite: {name}")
    return value


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
