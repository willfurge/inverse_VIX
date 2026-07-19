"""Download and parse VIX / VIX3M / VIX9D index history CSVs from the CBOE CDN.

Sprint 1.2 step 1 (plan.md); this unlocks the VIX/VIX3M ratio regime
flag. Writes data/interim/indices.parquet.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

from vixharvest.etl.validate import DataValidationError, validate_panel, validate_positive_columns

INDEX_COLUMNS = ("DATE", "OPEN", "HIGH", "LOW", "CLOSE")


class DataFreshnessError(DataValidationError):
    """Raised when an HTTP-successful source does not contain current data."""


class DataSourceError(RuntimeError):
    """Raised when an external data source cannot be retrieved or parsed."""


def fetch_index_history(
    index_name: str,
    *,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    now: date | datetime | None = None,
    session: requests.Session | Any | None = None,
) -> pd.DataFrame:
    """Download, validate, and persist one CBOE index-history CSV.

    A successful HTTP response is not enough: CBOE occasionally returns stale
    content. The endpoint is retried three times if its latest observation is
    older than the configured freshness limit.
    """
    config = _load_config(config_path)
    source_config = config["cboe_indices"]
    try:
        endpoint = source_config[index_name]
        url = endpoint["url"]
    except KeyError as exc:
        raise ValueError(f"Unsupported CBOE index: {index_name}") from exc

    current_date = pd.Timestamp(now or datetime.now()).normalize()
    client = session or requests.Session()
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = client.get(url, timeout=30)
            response.raise_for_status()
            frame = _parse_index_csv(response.content, index_name=index_name)
            _validate_index_history(
                frame,
                current_date=current_date,
                max_staleness_days=int(source_config["max_staleness_days"]),
            )
            _raw_indices_dir(data_dir).mkdir(parents=True, exist_ok=True)
            (_raw_indices_dir(data_dir) / f"{index_name.upper()}_History.csv").write_bytes(
                response.content
            )
            return frame
        except (requests.RequestException, DataValidationError, UnicodeDecodeError) as exc:
            last_error = exc
    raise DataSourceError(
        f"CBOE {index_name} history failed after three attempts: {last_error}"
    ) from last_error


def build_indices_panel(
    *,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    now: date | datetime | None = None,
) -> pd.DataFrame:
    """Combine CBOE VIX/VIX3M/VIX9D histories into an interim parquet panel."""
    frames = [
        fetch_index_history(
            index_name,
            config_path=config_path,
            data_dir=data_dir,
            now=now,
        )
        for index_name in ("vix", "vix3m", "vix9d")
    ]
    renamed = [
        frame.rename(columns={column: f"{name}_{column}" for column in ("open", "high", "low", "close")})
        for name, frame in zip(("vix", "vix3m", "vix9d"), frames, strict=True)
    ]
    panel = renamed[0]
    for frame in renamed[1:]:
        panel = panel.merge(frame, on="date", how="outer", validate="one_to_one")
    panel = panel.sort_values("date", ignore_index=True)
    interim_dir = _interim_dir(data_dir)
    interim_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(interim_dir / "indices.parquet", index=False)
    return panel


def _parse_index_csv(content: bytes, *, index_name: str) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content))
    if tuple(frame.columns) != INDEX_COLUMNS:
        raise DataValidationError(
            f"CBOE {index_name} schema changed; expected {INDEX_COLUMNS}, got {tuple(frame.columns)}"
        )
    frame.columns = [column.lower() for column in frame.columns]
    frame["date"] = pd.to_datetime(frame["date"], format="%m/%d/%Y", errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _validate_index_history(
    frame: pd.DataFrame,
    *,
    current_date: pd.Timestamp,
    max_staleness_days: int,
) -> None:
    validate_panel(frame, date_column="date")
    validate_positive_columns(frame, ("open", "high", "low", "close"))
    latest_date = frame["date"].max().normalize()
    age_days = (current_date - latest_date).days
    if age_days > max_staleness_days:
        raise DataFreshnessError(
            f"CBOE index history is stale: latest={latest_date.date()}, age={age_days} days."
        )


def _load_config(config_path: Path | None) -> dict[str, Any]:
    path = Path(config_path) if config_path else _repo_root() / "config" / "data_sources.yaml"
    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir or _repo_root() / "data"


def _raw_indices_dir(data_dir: Path | None) -> Path:
    return _data_dir(data_dir) / "raw" / "indices"


def _interim_dir(data_dir: Path | None) -> Path:
    return _data_dir(data_dir) / "interim"
