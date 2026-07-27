import json
import urllib.parse

import numpy

import tentacles.Services.Interfaces.web_interface.models.dashboard as dashboard


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_fetch_public_kucoin_candles_uses_requested_market(monkeypatch):
    requested = []

    def fake_urlopen(request, timeout):
        requested.append((request.full_url, timeout))
        return _JsonResponse(
            {
                "code": "200000",
                "data": [
                    [1_800_000, 100, 102, 99, 101, 12, 1200],
                    [900_000, 90, 101, 89, 100, 10, 1000],
                ],
            }
        )

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", fake_urlopen)

    rows = dashboard._fetch_public_kucoin_candles(
        "ETHUSDTM", 15, 900, 1800
    )

    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(requested[0][0]).query
    )
    assert query["symbol"] == ["ETHUSDTM"]
    assert query["granularity"] == ["15"]
    assert requested[0][1] == 20
    assert [row[0] for row in rows] == [900, 1800]
    assert rows[0][1:6] == [90.0, 101.0, 89.0, 100.0, 10.0]


def test_eth_research_loader_uses_stale_cache_on_network_error(monkeypatch):
    dashboard._percentage_research_market_live_cache.clear()
    now = 1_800_000
    candle_seconds = 900
    start = (
        now
        - (dashboard.PERCENTAGE_RESEARCH_MARKET_HISTORY_LIMIT - 1)
        * candle_seconds
    )
    rows = [
        [
            start + index * candle_seconds,
            100 + index,
            101 + index,
            99 + index,
            100.5 + index,
            10 + index,
        ]
        for index in range(
            dashboard.PERCENTAGE_RESEARCH_MARKET_HISTORY_LIMIT
        )
    ]
    monkeypatch.setattr(dashboard.time, "time", lambda: now)
    monkeypatch.setattr(
        dashboard, "_fetch_public_kucoin_candles", lambda *_args: rows
    )

    candles, metadata = dashboard._load_percentage_research_market_live(
        "ETH/USDT:USDT", "15m"
    )

    assert len(candles[0]) == (
        dashboard.PERCENTAGE_RESEARCH_MARKET_HISTORY_LIMIT
    )
    assert metadata["live"] is True
    assert metadata["orders_authorized"] is False

    monkeypatch.setattr(
        dashboard.time, "time", lambda: now + 61
    )

    def fail_fetch(*_args):
        raise TimeoutError("offline")

    monkeypatch.setattr(
        dashboard, "_fetch_public_kucoin_candles", fail_fetch
    )
    stale_candles, stale_metadata = (
        dashboard._load_percentage_research_market_live(
            "ETH/USDT:USDT", "15m"
        )
    )

    numpy.testing.assert_array_equal(stale_candles[0], candles[0])
    assert stale_metadata["live"] is False
    assert stale_metadata["offline"] is True
    assert stale_metadata["error"] == "offline"


def test_cross_asset_payload_is_explicitly_unvalidated():
    result = {
        "candles": {"time": ["26-07-27 00:00:00"]},
        "percentage_research": {},
        "percentage_probability": {},
        "perfect_map_forecast_v2": {},
        "percentage_long_hypothesis": {},
        "percentage_long_hypothesis_h2": {},
    }
    metadata = {
        "source": "feed pubblico ETH",
        "orders_authorized": False,
    }

    dashboard._mark_cross_asset_research(
        result, "ETH/USDT:USDT", metadata
    )

    assert result["research_only"] is True
    assert result["orders_authorized"] is False
    assert result["percentage_research"]["source_symbol"] == (
        "ETH/USDT:USDT"
    )
    for key in (
        "percentage_probability",
        "percentage_long_hypothesis",
        "percentage_long_hypothesis_h2",
    ):
        assert result[key]["cross_asset_unvalidated"] is True
        assert "modello" in result[key]["cross_asset_warning"].lower()
    assert result["perfect_map_forecast_v2"]["source_symbol"] == (
        "ETH/USDT:USDT"
    )
    assert (
        result["perfect_map_forecast_v2"].get(
            "cross_asset_unvalidated", False
        )
        is False
    )
