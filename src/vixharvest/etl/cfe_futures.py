"""Download and parse per-contract VIX futures (VX) CSVs from the CBOE CFE
historical data page.

Sprint 1.2 step 2 (plan.md). Writes data/interim/vx_contracts.parquet.
"""

from __future__ import annotations

import calendar
import io
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

from vixharvest.etl.cboe_indices import DataSourceError
from vixharvest.etl.validate import DataValidationError, validate_vx_contracts


def fetch_contract(
    expiry: date | datetime | str,
    *,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    session: requests.Session | Any | None = None,
    allow_missing: bool = False,
) -> pd.DataFrame | None:
    """Download one CFE VX contract by its actual expiration date.

    CFE filenames use the expiration date, and parsed rows retain it as the
    canonical contract identity. A missing candidate is normal during monthly
    enumeration but an explicit request fails loudly by default.
    """
    contract_expiry = pd.Timestamp(expiry).normalize()
    config = _load_config(config_path)["cfe_futures"]
    url = config["contract_csv_url_template"].format(expiry=contract_expiry)
    client = session or requests.Session()
    try:
        response = client.get(url, timeout=30)
    except requests.RequestException as exc:
        raise DataSourceError(f"CFE request failed for {contract_expiry.date()}: {exc}") from exc
    if response.status_code in (403, 404):
        if allow_missing:
            return None
        raise DataSourceError(f"CFE contract is unavailable: {contract_expiry.date()} ({response.status_code})")
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DataSourceError(f"CFE request failed for {contract_expiry.date()}: {exc}") from exc

    frame = _parse_contract_csv(response.content, contract_expiry)
    raw_dir = _raw_contracts_dir(data_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"VX_{contract_expiry:%Y-%m-%d}.csv").write_bytes(response.content)
    return frame


def build_vx_contracts_panel(
    *,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    now: date | datetime | None = None,
    enforce_coverage: bool = True,
) -> pd.DataFrame:
    """Enumerate available CFE contract files and write the normalized VX panel."""
    config = _load_config(config_path)["cfe_futures"]
    first_expiry = pd.Timestamp(config["public_coverage_start"]).date()
    current_date = pd.Timestamp(now or datetime.now()).normalize().date()
    last_expiry = (pd.Timestamp(current_date) + pd.DateOffset(months=12)).date()
    contracts = []
    for candidates in _monthly_expiry_candidates(first_expiry, last_expiry):
        frame = next(
            (
                downloaded
                for candidate in candidates
                if (downloaded := _load_or_fetch_contract(
                    candidate,
                    current_date=current_date,
                    config_path=config_path,
                    data_dir=data_dir,
                )) is not None
            ),
            None,
        )
        if frame is not None:
            contracts.append(frame)
    if not contracts:
        raise DataSourceError("CFE enumeration found no VX contract files.")

    panel = pd.concat(contracts, ignore_index=True).sort_values(
        ["date", "expiry"], ignore_index=True
    )
    validate_vx_contracts(panel)
    required_start = pd.Timestamp(config["required_coverage_start"])
    actual_start = panel["date"].min()
    if enforce_coverage and actual_start > required_start:
        raise CoverageError(
            f"Public CFE VX history starts {actual_start.date()}, but Sprint 1 requires "
            f"{required_start.date()}. Supply a separate pre-2013 data source; do not silently backfill."
        )
    interim_dir = _interim_dir(data_dir)
    interim_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(interim_dir / "vx_contracts.parquet", index=False)
    return panel


class CoverageError(DataValidationError):
    """Raised when public CFE history cannot meet the configured research window."""


def _load_or_fetch_contract(
    expiry: date,
    *,
    current_date: date,
    config_path: Path | None,
    data_dir: Path | None,
) -> pd.DataFrame | None:
    """Reuse an immutable expired raw file; refresh active and future contracts."""
    raw_path = _raw_contracts_dir(data_dir) / f"VX_{expiry:%Y-%m-%d}.csv"
    if expiry < current_date and raw_path.exists():
        return _parse_contract_csv(raw_path.read_bytes(), pd.Timestamp(expiry))
    return fetch_contract(
        expiry,
        config_path=config_path,
        data_dir=data_dir,
        allow_missing=True,
    )


def _parse_contract_csv(content: bytes, expiry: pd.Timestamp) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content))
    required = {
        "Trade Date",
        "Futures",
        "Open",
        "High",
        "Low",
        "Close",
        "Settle",
        "Total Volume",
        "Open Interest",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise DataValidationError(f"CFE VX schema changed; missing columns: {sorted(missing)}")

    renamed = frame.rename(
        columns={
            "Trade Date": "date",
            "Futures": "source_contract",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Settle": "settle",
            "Total Volume": "volume",
            "Open Interest": "oi",
        }
    )
    result = renamed[
        ["date", "source_contract", "open", "high", "low", "close", "settle", "volume", "oi"]
    ].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "settle", "volume", "oi"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    no_price = (result["settle"] <= 0) & (result["close"] <= 0)
    all_zero_placeholder = no_price & (
        result[["open", "high", "low", "volume", "oi"]] == 0
    ).all(axis=1)
    invalid_missing_rows = no_price & ~all_zero_placeholder & (result["date"] != expiry)
    if invalid_missing_rows.any():
        raise DataValidationError(
            f"CFE {expiry.date()} contains non-expiry rows without a close or settlement."
        )
    # Some 2013 expiry rows are placeholders: Open/Close/Settle are zero while
    # High/Low contain values. They are neither a valid market observation nor
    # the settle-only format used by newer files, so exclude them from the panel.
    expiry_placeholder = no_price & (result["date"] == expiry)
    result = result.loc[~(all_zero_placeholder | expiry_placeholder)].copy()
    # Older CFE files use Close where newer files use Settle. Preserve raw files
    # and fill only an absent/zero settlement from the valid close of that row.
    result["settle"] = result["settle"].where(result["settle"] > 0, result["close"])
    if result.empty or result["settle"].isna().any() or (result["settle"] <= 0).any():
        raise DataValidationError(f"CFE {expiry.date()} contains a row without a valid settlement.")
    result["expiry"] = expiry
    result["contract"] = f"VX_{expiry:%Y-%m-%d}"
    return result[
        ["date", "contract", "expiry", "open", "high", "low", "close", "settle", "volume", "oi", "source_contract"]
    ]


def _monthly_expiry_candidates(start: date, end: date) -> list[tuple[date, ...]]:
    """Produce CFE filename candidates from the published VIX-expiry convention.

    Candidates are verified by an actual CFE response; they do not define the
    expiry calendar used later in research, which is derived from downloaded data.
    """
    month = date(start.year, start.month, 1)
    last_month = date(end.year, end.month, 1)
    candidates: list[tuple[date, ...]] = []
    while month <= last_month:
        following_month = _add_month(month)
        third_friday = _third_friday(following_month.year, following_month.month)
        standard_expiry = third_friday - timedelta(days=30)
        candidates.append(
            tuple(standard_expiry + timedelta(days=offset) for offset in (0, -1, 1))
        )
        month = _add_month(month)
    return candidates


def _third_friday(year: int, month: int) -> date:
    weeks = calendar.monthcalendar(year, month)
    fridays = [week[calendar.FRIDAY] for week in weeks if week[calendar.FRIDAY]]
    return date(year, month, fridays[2])


def _add_month(month: date) -> date:
    return date(month.year + (month.month == 12), (month.month % 12) + 1, 1)


def _load_config(config_path: Path | None) -> dict[str, Any]:
    path = Path(config_path) if config_path else _repo_root() / "config" / "data_sources.yaml"
    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir or _repo_root() / "data"


def _raw_contracts_dir(data_dir: Path | None) -> Path:
    return _data_dir(data_dir) / "raw" / "cfe_vx"


def _interim_dir(data_dir: Path | None) -> Path:
    return _data_dir(data_dir) / "interim"
