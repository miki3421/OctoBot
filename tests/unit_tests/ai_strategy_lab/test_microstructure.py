import datetime
import json
import urllib.parse

import pytest

from octobot.ai_strategy_lab import microstructure


NOW = datetime.datetime(
    2026, 7, 23, 12, 7, tzinfo=datetime.timezone.utc
)


def _config(tmp_path):
    return microstructure.MicrostructureConfig(
        journal_path=tmp_path / "market.jsonl",
        health_path=tmp_path / "health.json",
        lock_path=tmp_path / "runner.lock",
        futures_symbols={"BTC/USDT:USDT": "XBTUSDTM"},
        spot_symbols={"BTC/USDT": "BTC-USDT"},
    )


class PublicResponses:
    def __init__(self, *, missing_futures_ticker=False):
        self.calls = []
        self.missing_futures_ticker = missing_futures_ticker

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if url == microstructure.SPOT_TICKERS_URL:
            return {
                "code": "200000",
                "data": {
                    "time": 1_753_271_220_000,
                    "ticker": [
                        {
                            "symbol": "BTC-USDT",
                            "buy": "100",
                            "sell": "101",
                            "takerFeeRate": "0.0008",
                            "takerCoefficient": "1",
                        }
                    ],
                },
            }
        if url == microstructure.FUTURES_TICKERS_URL:
            data = [] if self.missing_futures_ticker else [
                {
                    "symbol": "XBTUSDTM",
                    "bestBidPrice": "102",
                    "bestAskPrice": "103",
                    "ts": 1_753_271_220_000_000_000,
                }
            ]
            return {"code": "200000", "data": data}
        if url == microstructure.FUTURES_CONTRACTS_URL:
            return {
                "code": "200000",
                "data": [
                    {
                        "symbol": "XBTUSDTM",
                        "multiplier": 0.1,
                        "openInterest": "1000",
                        "markPrice": "102.5",
                        "indexPrice": "101.5",
                        "takerFeeRate": 0.0005,
                    }
                ],
            }
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith("/market/orderbook/level2_20"):
            assert query == {"symbol": ["BTC-USDT"]}
            return {
                "code": "200000",
                "data": {
                    "time": 1_753_271_220_100,
                    "sequence": "1",
                    "bids": [["100", "3"]],
                    "asks": [["101", "2"]],
                },
            }
        if parsed.path.endswith("/level2/depth20"):
            assert query == {"symbol": ["XBTUSDTM"]}
            return {
                "code": "200000",
                "data": {
                    "ts": 1_753_271_220_200_000_000,
                    "sequence": 2,
                    "bids": [[102, 10]],
                    "asks": [[103, 20]],
                },
            }
        if parsed.path.endswith("/funding-rate/XBTUSDTM/current"):
            return {
                "code": "200000",
                "data": {
                    "value": 0.0001,
                    "predictedValue": 0.0002,
                    "granularity": 28_800_000,
                    "timePoint": 1_753_257_600_000,
                    "fundingTime": 1_753_286_400_000,
                    "fundingRateCap": 0.003,
                    "fundingRateFloor": -0.003,
                },
            }
        if parsed.path.endswith("/contract/funding-rates"):
            assert query["symbol"] == ["XBTUSDTM"]
            assert int(query["to"][0]) - int(query["from"][0]) == 86_400_000
            return {
                "code": "200000",
                "data": [
                    {
                        "symbol": "XBTUSDTM",
                        "fundingRate": 0.00009,
                        "timepoint": 1_753_257_600_000,
                    },
                    {
                        "symbol": "XBTUSDTM",
                        "fundingRate": 0.00008,
                        "timepoint": 1_753_228_800_000,
                    },
                ],
            }
        raise AssertionError(f"unexpected URL: {url}")


def test_observer_appends_complete_hashed_record(tmp_path):
    responses = PublicResponses()
    config = _config(tmp_path)

    health = microstructure.run_observation_once(
        config, now=NOW, fetch_json=responses
    )
    records = microstructure.load_microstructure_records(
        config.journal_path
    )

    assert health["status"] == "healthy"
    assert health["journal_appended"] is True
    assert health["orders_authorized"] is False
    assert health["archived_records"] == 1
    assert health["archive_consistent"] is True
    assert len(list((tmp_path / "records").glob("*.json"))) == 1
    assert len(records) == 1
    record = records[0]
    assert record["bucket_start_utc"] == "2026-07-23T12:00:00+00:00"
    assert record["symbol_count"] == 1
    assert record["spot_ticker_snapshot_timestamp_ms"] == 1_753_271_220_000
    assert record["previous_record_hash"] is None
    btc = record["symbols"]["BTC"]
    assert btc["spot"]["book_timestamp_ms"] == 1_753_271_220_100
    assert btc["spot"]["bid_depth_quote"] == pytest.approx(300)
    assert btc["spot"]["ask_depth_quote"] == pytest.approx(202)
    assert btc["spot"]["published_taker_fee_rate"] == pytest.approx(
        0.0008
    )
    assert btc["spot"]["conservative_taker_fee_rate"] == pytest.approx(
        0.001
    )
    assert btc["futures"][
        "published_taker_fee_rate"
    ] == pytest.approx(0.0005)
    assert btc["futures"][
        "conservative_taker_fee_rate"
    ] == pytest.approx(0.0006)
    assert btc["spot"]["bid_vwap_by_quote"]["100"] == {
        "target_quote": 100.0,
        "filled_quote": 100.0,
        "filled_base": 1.0,
        "vwap": 100.0,
        "last_price": 100.0,
        "sufficient_depth": True,
    }
    assert btc["spot"]["ask_vwap_by_quote"]["500"][
        "sufficient_depth"
    ] is False
    assert btc["futures"]["bid_vwap_by_quote"]["100"]["vwap"] == 102
    assert btc["futures"]["bid_vwap_by_quote"]["500"][
        "sufficient_depth"
    ] is False
    assert btc["spot"]["normalized_bids"] == [
        {
            "price": 100.0,
            "base_quantity": 3.0,
            "quote_quantity": 300.0,
        }
    ]
    assert btc["futures"]["normalized_bids"] == [
        {
            "price": 102.0,
            "base_quantity": 1.0,
            "quote_quantity": 102.0,
        }
    ]
    assert btc["futures"]["bid_depth_quote"] == pytest.approx(102)
    assert btc["futures"]["ask_depth_quote"] == pytest.approx(206)
    assert btc["carry_execution"][
        "entry_capacity_usdt_depth20"
    ] == pytest.approx(102)
    assert btc["carry_execution"][
        "exit_capacity_usdt_depth20"
    ] == pytest.approx(206)
    assert btc["carry_execution"]["entry_basis_bps"] == pytest.approx(
        (102 / 101 - 1) * 10_000
    )
    assert btc["funding"]["predicted_simple_annualized"] == pytest.approx(
        0.0002 * 3 * 365
    )
    assert btc["funding"]["settled_last_24h"] == [
        {"timestamp_ms": 1_753_228_800_000, "rate": 0.00008},
        {"timestamp_ms": 1_753_257_600_000, "rate": 0.00009},
    ]
    assert len(responses.calls) == 7


def test_observer_deduplicates_same_utc_bucket_without_network(tmp_path):
    responses = PublicResponses()
    config = _config(tmp_path)
    first = microstructure.run_observation_once(
        config, now=NOW, fetch_json=responses
    )
    calls = len(responses.calls)

    second = microstructure.run_observation_once(
        config,
        now=NOW + datetime.timedelta(minutes=5),
        fetch_json=responses,
    )

    assert first["journal_appended"] is True
    assert second["journal_appended"] is False
    assert len(responses.calls) == calls
    assert len(
        microstructure.load_microstructure_records(config.journal_path)
    ) == 1


def test_observer_chains_next_bucket(tmp_path):
    responses = PublicResponses()
    config = _config(tmp_path)
    microstructure.run_observation_once(
        config, now=NOW, fetch_json=responses
    )
    microstructure.run_observation_once(
        config,
        now=NOW + datetime.timedelta(minutes=15),
        fetch_json=responses,
    )

    records = microstructure.load_microstructure_records(
        config.journal_path
    )
    assert len(records) == 2
    assert records[1]["previous_record_hash"] == records[0]["record_hash"]


def test_incomplete_collection_fails_without_partial_append(tmp_path):
    config = _config(tmp_path)

    with pytest.raises(ValueError, match="missing futures ticker"):
        microstructure.run_observation_once(
            config,
            now=NOW,
            fetch_json=PublicResponses(missing_futures_ticker=True),
        )

    assert not config.journal_path.exists()
    health = json.loads(config.health_path.read_text(encoding="utf-8"))
    assert health["status"] == "failed"
    assert health["orders_authorized"] is False


def test_loader_rejects_tampered_record(tmp_path):
    config = _config(tmp_path)
    microstructure.run_observation_once(
        config, now=NOW, fetch_json=PublicResponses()
    )
    record = json.loads(
        config.journal_path.read_text(encoding="utf-8")
    )
    record["symbols"]["BTC"]["spot"]["best_bid"] = 99
    config.journal_path.write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="record hash is invalid"):
        microstructure.load_microstructure_records(config.journal_path)


def test_archive_recovers_complete_record_missing_from_journal(tmp_path):
    config = _config(tmp_path)
    microstructure.run_observation_once(
        config, now=NOW, fetch_json=PublicResponses()
    )
    config.journal_path.write_text("", encoding="utf-8")

    def no_network(url, timeout):
        raise AssertionError(f"network should not be called: {url}")

    health = microstructure.run_observation_once(
        config,
        now=NOW + datetime.timedelta(minutes=5),
        fetch_json=no_network,
    )

    assert health["journal_appended"] is False
    assert health["archived_records"] == 1
    assert len(
        microstructure.load_microstructure_records(config.journal_path)
    ) == 1


def test_archive_tampering_fails_before_new_collection(tmp_path):
    config = _config(tmp_path)
    microstructure.run_observation_once(
        config, now=NOW, fetch_json=PublicResponses()
    )
    archive = next((tmp_path / "records").glob("*.json"))
    value = json.loads(archive.read_text(encoding="utf-8"))
    value["symbols"]["BTC"]["spot"]["best_bid"] = 99
    archive.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="archive record mismatch"):
        microstructure.run_observation_once(
            config,
            now=NOW + datetime.timedelta(minutes=15),
            fetch_json=PublicResponses(),
        )
