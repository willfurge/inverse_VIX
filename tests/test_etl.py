from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest
import yaml

from vixharvest.etl.cboe_indices import DataSourceError, fetch_index_history
from vixharvest.etl.cfe_futures import _parse_contract_csv
from vixharvest.etl.etp_prices import CoverageError, fetch_etp_prices
from vixharvest.etl.validate import DataValidationError, validate_etp_prices, validate_vx_contracts


@dataclass
class FakeResponse:
    content: bytes
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = 0

    def get(self, *_args, **_kwargs) -> FakeResponse:
        self.calls += 1
        return self.response


def write_source_config(tmp_path, config: dict) -> str:
    path = tmp_path / "data_sources.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path)


def test_index_fetch_retries_and_rejects_a_stale_http_success(tmp_path):
    config_path = write_source_config(
        tmp_path,
        {
            "cboe_indices": {
                "max_staleness_days": 1,
                "vix": {"url": "https://example.test/VIX.csv"},
            }
        },
    )
    response = FakeResponse(
        b"DATE,OPEN,HIGH,LOW,CLOSE\n07/14/2026,10,11,9,10\n"
    )
    session = FakeSession(response)

    with pytest.raises(DataSourceError, match="failed after three attempts"):
        fetch_index_history(
            "vix",
            config_path=config_path,
            data_dir=tmp_path / "data",
            now="2026-07-17",
            session=session,
        )

    assert session.calls == 3


def test_index_fetch_writes_raw_csv_and_returns_typed_frame(tmp_path):
    config_path = write_source_config(
        tmp_path,
        {
            "cboe_indices": {
                "max_staleness_days": 1,
                "vix": {"url": "https://example.test/VIX.csv"},
            }
        },
    )
    response = FakeResponse(
        b"DATE,OPEN,HIGH,LOW,CLOSE\n07/15/2026,10,11,9,10\n07/16/2026,11,12,10,11\n07/17/2026,12,13,11,12\n"
    )

    frame = fetch_index_history(
        "vix",
        config_path=config_path,
        data_dir=tmp_path / "data",
        now="2026-07-17",
        session=FakeSession(response),
    )

    assert frame.columns.tolist() == ["date", "open", "high", "low", "close"]
    assert frame["date"].dtype.kind == "M"
    assert (tmp_path / "data" / "raw" / "indices" / "VIX_History.csv").exists()


def test_cfe_parser_uses_close_when_legacy_settle_is_zero():
    content = b"Trade Date,Futures,Open,High,Low,Close,Settle,Change,Total Volume,EFP,Open Interest\n2025-01-21,F (Jan 2025),20,21,19,20.5,0,0,12,0,18\n2025-01-22,F (Jan 2025),0,0,0,0,20.5,0,0,0,0\n"

    frame = _parse_contract_csv(content, pd.Timestamp("2025-01-22"))

    assert frame.loc[0, "settle"] == 20.5
    assert frame.loc[1, "settle"] == 20.5
    assert frame.loc[1, "open"] == 0


def test_cfe_parser_discards_all_zero_pre_listing_placeholders():
    content = b"Trade Date,Futures,Open,High,Low,Close,Settle,Change,Total Volume,EFP,Open Interest\n2013-01-18,V (Oct 2013),0,0,0,0,0,0,0,0,0\n2013-01-23,V (Oct 2013),20,21,19,20.5,0,0,3,0,3\n"

    frame = _parse_contract_csv(content, pd.Timestamp("2013-10-16"))

    assert frame["date"].tolist() == [pd.Timestamp("2013-01-23")]
    assert frame.iloc[0]["settle"] == 20.5


def test_vx_validation_allows_a_settle_only_expiry_row():
    contracts = pd.DataFrame(
        {
            "date": ["2025-01-20", "2025-01-20", "2025-01-20", "2025-01-22", "2025-01-22", "2025-01-22"],
            "contract": ["VX/F25", "VX/G25", "VX/H25", "VX/F25", "VX/G25", "VX/H25"],
            "expiry": ["2025-01-22", "2025-02-19", "2025-03-19", "2025-01-22", "2025-02-19", "2025-03-19"],
            "open": [20.0, 21.0, 22.0, 0.0, 21.0, 22.0],
            "high": [21.0, 22.0, 23.0, 0.0, 22.0, 23.0],
            "low": [19.0, 20.0, 21.0, 0.0, 20.0, 21.0],
            "close": [20.0, 21.0, 22.0, 0.0, 21.0, 22.0],
            "settle": [20.0, 21.0, 22.0, 20.5, 21.0, 22.0],
            "volume": [10, 10, 10, 0, 10, 10],
            "oi": [10, 10, 10, 0, 10, 10],
        }
    )

    validate_vx_contracts(contracts)


def test_vx_validation_allows_tuesday_expiry_before_good_friday():
    contracts = pd.DataFrame(
        {
            "date": ["2025-03-17", "2025-03-17", "2025-03-17"],
            "contract": ["VX/H25", "VX/J25", "VX/K25"],
            "expiry": ["2025-03-18", "2025-04-16", "2025-05-21"],
            "open": [22.0, 23.0, 24.0],
            "high": [23.0, 24.0, 25.0],
            "low": [21.0, 22.0, 23.0],
            "close": [22.0, 23.0, 24.0],
            "settle": [22.0, 23.0, 24.0],
            "volume": [10, 10, 10],
            "oi": [10, 10, 10],
        }
    )

    validate_vx_contracts(contracts)


def test_etp_validation_rejects_unadjusted_split_jump():
    prices = pd.DataFrame(
        {
            "date": ["2026-07-13", "2026-07-14", "2026-07-15"],
            "ticker": ["VXX"] * 3,
            "close": [20.0, 100.0, 101.0],
        }
    )

    with pytest.raises(DataValidationError, match="adjusted-close returns"):
        validate_etp_prices(prices, ticker="VXX")


def test_vxx_yahoo_coverage_gap_raises_instead_of_silent_stitch(tmp_path):
    config_path = write_source_config(
        tmp_path,
        {
            "etp_prices": {
                "auto_adjust": True,
                "vxx": {"ticker": "VXX", "required_coverage_start": "2009-01-01"},
            }
        },
    )
    history = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [11.0, 12.0],
            "Low": [9.0, 10.0],
            "Close": [10.0, 11.0],
            "Volume": [100, 100],
            "Dividends": [0.0, 0.0],
            "Stock Splits": [0.0, 0.0],
            "Capital Gains": [0.0, 0.0],
        },
        index=pd.DatetimeIndex(["2018-01-25", "2018-01-26"], name="Date"),
    )

    with pytest.raises(CoverageError, match="do not silently stitch"):
        fetch_etp_prices(
            "VXX",
            config_path=config_path,
            data_dir=tmp_path / "data",
            ticker_factory=lambda _ticker: type("Ticker", (), {"history": lambda self, **_kwargs: history})(),
        )
