import datetime
import gzip
import json
import pathlib
import urllib.parse

import pytest

from octobot.ai_strategy_lab import cross_venue_observer as observer


NOW = datetime.datetime(
    2026, 8, 30, 12, 7, tzinfo=datetime.timezone.utc
)
SERVER_TIME_MS = int(
    datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
)


def _config(tmp_path):
    return observer.CrossVenueObserverConfig(
        archive_root=tmp_path / "records",
        index_path=tmp_path / "index.jsonl",
        health_path=tmp_path / "health.json",
        lock_path=tmp_path / "runner.lock",
        symbol_mapping={
            "BTC/USDT:USDT": {
                "kucoin": "XBTUSDTM",
                "binance": "BTCUSDT",
            }
        },
    )


class PublicResponses:
    def __init__(self, *, missing_premium=False, book_age_ms=0):
        self.calls = []
        self.missing_premium = missing_premium
        self.book_age_ms = book_age_ms

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith("/contracts/active"):
            return {
                "code": "200000",
                "data": [
                    {
                        "symbol": "XBTUSDTM",
                        "multiplier": 0.001,
                        "takerFeeRate": 0.0006,
                        "markPrice": 100,
                        "indexPrice": 100,
                        "openInterest": "10000",
                        "fundingFeeRate": 0.0002,
                        "predictedFundingFeeRate": 0.00025,
                        "currentFundingRateGranularity": None,
                        "fundingRateGranularity": 28_800_000,
                        "nextFundingRateDateTime": SERVER_TIME_MS + 3600_000,
                    }
                ],
            }
        if parsed.path.endswith("/premiumIndex"):
            return [] if self.missing_premium else [
                {
                    "symbol": "BTCUSDT",
                    "markPrice": "100",
                    "indexPrice": "100",
                    "lastFundingRate": "0.0001",
                    "nextFundingTime": SERVER_TIME_MS + 3600_000,
                    "time": SERVER_TIME_MS,
                }
            ]
        if parsed.path.endswith("/fundingInfo"):
            return [
                {
                    "symbol": "BTCUSDT",
                    "adjustedFundingRateCap": "0.003",
                    "adjustedFundingRateFloor": "-0.003",
                    "fundingIntervalHours": 8,
                    "updateTime": SERVER_TIME_MS,
                }
            ]
        if parsed.path.endswith("/level2/depth20"):
            assert query == {"symbol": ["XBTUSDTM"]}
            return {
                "code": "200000",
                "data": {
                    "symbol": "XBTUSDTM",
                    "ts": (SERVER_TIME_MS - self.book_age_ms) * 1_000_000,
                    "bids": [[100, 1000], [99, 1000]],
                    "asks": [[101, 1000], [102, 1000]],
                },
            }
        if parsed.path.endswith("/depth"):
            assert query == {"symbol": ["BTCUSDT"], "limit": ["20"]}
            return {
                "lastUpdateId": 1,
                "E": SERVER_TIME_MS - self.book_age_ms,
                "T": SERVER_TIME_MS - self.book_age_ms,
                "bids": [["99.9", "2"], ["99", "2"]],
                "asks": [["100.1", "2"], ["101", "2"]],
            }
        if parsed.path.endswith("/openInterest"):
            assert query == {"symbol": ["BTCUSDT"]}
            return {
                "symbol": "BTCUSDT",
                "openInterest": "5000",
                "time": SERVER_TIME_MS,
            }
        raise AssertionError(f"unexpected URL: {url}")


def test_observer_writes_one_compressed_hashed_complete_record(tmp_path):
    responses = PublicResponses()
    config = _config(tmp_path)

    health = observer.run_observation_once(
        config, now=NOW, fetch_json=responses
    )
    records = observer.load_records(config)

    assert health["status"] == "healthy"
    assert health["public_data_only"] is True
    assert health["orders_authorized"] is False
    assert health["paper_orders_authorized"] is False
    assert health["archived_records"] == 1
    assert health["full_payload_duplicate_journal"] is False
    assert health["forward_eligible"] is True
    assert health["estimated_compressed_bytes_per_day"] > 0
    assert len(records) == 1
    record = records[0]
    assert record["symbol_count"] == 1
    assert record["eligible_symbol_count"] == 1
    assert record["forward_eligible"] is True
    assert record["previous_record_hash"] is None
    btc = record["symbols"]["BTC"]
    assert btc["timing"]["forward_eligible"] is True
    assert btc["kucoin"]["book"]["bid_depth_quote"] == pytest.approx(
        199
    )
    assert btc["kucoin"]["open_interest_base"] == pytest.approx(10)
    assert btc["binance"]["open_interest_base"] == pytest.approx(5000)
    assert btc["binance"]["funding"]["granularity_ms_estimate"] == (
        8 * 3600 * 1000
    )
    execution = btc["cross_venue"]["execution_by_quote_per_leg"]["100"]
    assert execution["target_base_per_leg"] > 0
    direction = execution["long_binance_short_kucoin"]
    assert direction["sufficient_depth"] is True
    assert direction[
        "four_fill_conservative_taker_fee_bps"
    ] == pytest.approx(24)
    assert direction["immediate_two_leg_return_bps_after_taker_fee"] < 0
    assert len(responses.calls) == 6
    archives = list((tmp_path / "records").glob("*.json.gz"))
    assert len(archives) == 1
    assert json.loads(gzip.decompress(archives[0].read_bytes())) == record
    assert len(config.index_path.read_text().splitlines()) == 1


def test_observer_deduplicates_bucket_without_network(tmp_path):
    responses = PublicResponses()
    config = _config(tmp_path)
    first = observer.run_observation_once(
        config, now=NOW, fetch_json=responses
    )
    calls = len(responses.calls)

    second = observer.run_observation_once(
        config,
        now=NOW + datetime.timedelta(minutes=4),
        fetch_json=responses,
    )

    assert first["journal_appended"] is True
    assert second["journal_appended"] is False
    assert len(responses.calls) == calls
    assert len(observer.load_records(config)) == 1


def test_incomplete_global_snapshot_fails_without_partial_record(tmp_path):
    config = _config(tmp_path)

    with pytest.raises(ValueError, match="missing Binance premium"):
        observer.run_observation_once(
            config,
            now=NOW,
            fetch_json=PublicResponses(missing_premium=True),
        )

    assert not list(config.archive_root.glob("*.json.gz"))
    assert not config.index_path.exists()
    health = json.loads(config.health_path.read_text(encoding="utf-8"))
    assert health["status"] == "failed"
    assert health["orders_authorized"] is False


def test_missing_index_is_rebuilt_from_canonical_archive(tmp_path):
    responses = PublicResponses()
    config = _config(tmp_path)
    observer.run_observation_once(config, now=NOW, fetch_json=responses)
    config.index_path.unlink()
    calls = len(responses.calls)

    health = observer.run_observation_once(
        config,
        now=NOW + datetime.timedelta(minutes=3),
        fetch_json=responses,
    )

    assert health["journal_appended"] is False
    assert len(responses.calls) == calls
    assert len(config.index_path.read_text().splitlines()) == 1
    assert observer.audit_archive(config)["archive_consistent"] is True


def test_archive_tampering_fails_full_audit(tmp_path):
    config = _config(tmp_path)
    observer.run_observation_once(
        config, now=NOW, fetch_json=PublicResponses()
    )
    archive = next(config.archive_root.glob("*.json.gz"))
    record = json.loads(gzip.decompress(archive.read_bytes()))
    record["symbols"]["BTC"]["binance"]["mark_price"] = 999
    archive.write_bytes(
        gzip.compress(
            json.dumps(record, sort_keys=True).encode("utf-8"), mtime=0
        )
    )

    with pytest.raises(ValueError, match="record hash is invalid"):
        observer.audit_archive(config)


def test_pre_forward_bucket_is_kept_but_not_eligible(tmp_path):
    config = _config(tmp_path)
    before_start = observer.FORWARD_START - datetime.timedelta(minutes=1)

    health = observer.run_observation_once(
        config, now=before_start, fetch_json=PublicResponses()
    )

    assert health["archived_records"] == 1
    assert health["forward_eligible"] is False
    assert health["forward_eligible_records"] == 0


def test_stale_server_books_are_recorded_but_not_forward_eligible(tmp_path):
    config = _config(tmp_path)

    health = observer.run_observation_once(
        config,
        now=NOW,
        fetch_json=PublicResponses(book_age_ms=45_000),
    )

    assert health["archived_records"] == 1
    assert health["eligible_symbol_count"] == 0
    assert health["forward_eligible"] is False
