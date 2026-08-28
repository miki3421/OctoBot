import datetime
import json
import pathlib
import urllib.parse

import numpy
import pytest

from octobot.ai_strategy_lab import category_momentum_v1 as protocol
from octobot.ai_strategy_lab import category_momentum_v1_research as research


def _market(days=220):
    first = datetime.datetime(2022, 4, 2, tzinfo=datetime.timezone.utc)
    timestamps = numpy.asarray(
        [
            int((first + datetime.timedelta(days=index)).timestamp())
            for index in range(days)
        ],
        dtype=numpy.int64,
    )
    symbols = numpy.asarray([f"ASSET{index:02d}USDT" for index in range(12)])
    slopes = numpy.asarray(
        [0.002] * 4 + [-0.002] * 4 + [0.0001, 0.0, -0.0001, 0.0]
    )
    steps = numpy.arange(days, dtype=numpy.float64)[:, None]
    closes = 100.0 * numpy.exp(steps * slopes[None, :])
    return {
        "timestamps": timestamps,
        "symbols": symbols,
        "closes": closes,
        "quote_volumes": numpy.full_like(closes, 1_000_000.0),
        "funding_rates": numpy.zeros_like(closes),
        "funding_counts": numpy.ones_like(closes, dtype=numpy.int16),
    }


def _taxonomy():
    groups = (
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (8, 9, 10, 11),
        (0, 4, 8, 9),
        (1, 5, 10, 11),
        (2, 6, 8, 10),
    )
    symbols = [f"ASSET{index:02d}USDT" for index in range(12)]
    return {
        "categories": [
            {
                "category_id": f"category-{index}",
                "selected_universe_members": [symbols[value] for value in group],
            }
            for index, group in enumerate(groups)
        ]
    }


def test_public_url_allowlist_rejects_private_or_authenticated_paths():
    research._validate_public_url(
        "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT"
    )

    with pytest.raises(ValueError):
        research._validate_public_url("https://fapi.binance.com/fapi/v1/order")
    with pytest.raises(ValueError):
        research._validate_public_url("https://user:secret@fapi.binance.com/fapi/v1/klines")
    with pytest.raises(ValueError):
        research._validate_public_url("https://example.com/fapi/v1/klines")


def test_liquidity_window_requires_exactly_28_completed_days():
    start = research.SNAPSHOT_CUTOFF - datetime.timedelta(days=28)
    rows = []
    for index in range(28):
        open_time = int((start + datetime.timedelta(days=index)).timestamp() * 1000)
        rows.append([open_time, "1", "1", "1", "1", "1", open_time + 1, str(index + 1)])

    parsed = research._parse_liquidity_rows(rows)

    assert parsed["days"] == 28
    assert parsed["median_daily_quote_volume"] == 14.5
    with pytest.raises(research.DataQualityError):
        research._parse_liquidity_rows(rows[:-1])


def test_taxonomy_collision_uses_highest_snapshot_market_cap():
    contracts = [
        {
            "symbol": "ABCUSDT",
            "base_asset": "ABC",
            "normalized_base": "abc",
            "onboard_timestamp_ms": 0,
        }
    ]
    categories = {
        "first": [
            {"id": "abc-small", "symbol": "abc", "name": "Small", "market_cap": 10}
        ],
        "second": [
            {"id": "abc-large", "symbol": "abc", "name": "Large", "market_cap": 20}
        ],
    }

    mapping, members, collisions = research._taxonomy_mapping(contracts, categories)

    assert mapping["ABCUSDT"]["coin_id"] == "abc-large"
    assert members["second"] == {"ABCUSDT"}
    assert members["first"] == set()
    assert collisions[0]["selected_coin_id"] == "abc-large"


def test_capped_volume_weights_are_feasible_deterministic_and_normalized():
    values = numpy.asarray([90.0, 5.0, 3.0, 2.0])

    weights = research._capped_weights(values, 0.30)

    assert numpy.isclose(numpy.sum(weights), 1.0)
    assert numpy.max(weights) <= 0.30 + 1e-12
    assert weights[0] == pytest.approx(0.30)
    with pytest.raises(ValueError, match="infeasible"):
        research._capped_weights(numpy.ones(3), 0.30)


def test_target_is_causal_neutral_and_uses_published_7_day_direction():
    market = _market()
    taxonomy = _taxonomy()

    target, audit = research.target_weights(market, taxonomy, 120)

    assert audit["status"] == "TARGET"
    assert audit["selected_long"] == ["category-0"]
    assert audit["selected_short"] == ["category-1"]
    assert numpy.all(target[:4] > 0)
    assert numpy.all(target[4:8] < 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.isclose(numpy.sum(numpy.abs(target)), 0.8)

    changed = {
        key: value.copy() if hasattr(value, "copy") else value
        for key, value in market.items()
    }
    changed["closes"][121:] *= numpy.linspace(0.5, 2.0, 12)
    changed["funding_rates"][121:] = 0.25
    changed["funding_counts"][121:] = 0
    changed_target, changed_audit = research.target_weights(changed, taxonomy, 120)
    assert numpy.array_equal(target, changed_target)
    assert audit == changed_audit


def test_exactly_90_contiguous_closes_are_sufficient():
    market = _market(days=100)

    assert research._eligible_symbol_indices(market, 88) == []
    assert len(research._eligible_symbol_indices(market, 89)) == 12

    market["closes"][0, 0] = numpy.nan
    assert 0 not in research._eligible_symbol_indices(market, 89)
    assert 0 in research._eligible_symbol_indices(market, 90)


def test_equal_category_scores_cannot_select_the_same_long_and_short():
    market = _market()
    market["closes"][:] = 100.0

    _target, audit = research.target_weights(market, _taxonomy(), 120)

    assert audit["status"] == "TARGET"
    assert set(audit["selected_long"]).isdisjoint(audit["selected_short"])


def test_simulation_uses_next_day_funding_and_stressed_costs_are_conservative():
    market = _market()
    taxonomy = _taxonomy()
    start = datetime.datetime.fromtimestamp(int(market["timestamps"][100]), datetime.timezone.utc)
    end = datetime.datetime.fromtimestamp(int(market["timestamps"][190]), datetime.timezone.utc)

    baseline = research.simulate_period(market, taxonomy, start, end)
    stress = research.simulate_period(
        market,
        taxonomy,
        start,
        end,
        cost_multiplier=protocol.STRESS_COST_MULTIPLIER,
    )

    assert baseline["total_return"] > 0
    assert stress["total_return"] < baseline["total_return"]
    assert baseline["long_additive_contribution"] > 0
    assert baseline["short_additive_contribution"] > 0
    assert baseline["maximum_gross_exposure"] <= 0.8 + 1e-12
    assert baseline["ever_targeted_symbols"]


def test_incomplete_future_outcome_fails_closed_without_changing_signal():
    market = _market()
    taxonomy = _taxonomy()
    start_index = 120
    start = datetime.datetime.fromtimestamp(
        int(market["timestamps"][start_index]), datetime.timezone.utc
    )
    end = datetime.datetime.fromtimestamp(
        int(market["timestamps"][start_index + 2]), datetime.timezone.utc
    )
    market["funding_counts"][start_index + 1, 0] = 0

    with pytest.raises(research.DataQualityError, match="incomplete next-day"):
        research.simulate_period(market, taxonomy, start, end)


def test_protocol_json_remains_bound_to_research_workflow(tmp_path):
    path = tmp_path / "protocol.json"
    frozen = protocol.write_or_verify_protocol(path)

    loaded = research._load_frozen_protocol(path)

    assert loaded == frozen
    changed = json.loads(path.read_text())
    changed["orders_authorized"] = True
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="not the frozen version"):
        research._load_frozen_protocol(path)


def test_source_snapshot_is_atomic_content_addressed_and_orderless(tmp_path):
    protocol_path = tmp_path / "protocol.json"
    frozen = protocol.write_or_verify_protocol(protocol_path)
    bases = ("AAA", "BBB", "CCC", "DDD")
    cutoff_ms = int(research.SNAPSHOT_CUTOFF.timestamp() * 1000)
    exchange = {
        "symbols": [
            {
                "symbol": f"{base}USDT",
                "baseAsset": base,
                "quoteAsset": "USDT",
                "marginAsset": "USDT",
                "status": "TRADING",
                "contractType": "PERPETUAL",
                "underlyingType": "COIN",
                "onboardDate": cutoff_ms - 365 * research.DAY_MILLISECONDS,
            }
            for base in bases
        ]
    }
    category_list = [
        {"category_id": value, "name": value}
        for value in protocol.COINGECKO_CATEGORY_IDS
    ]

    def fake_fetch(url):
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith("exchangeInfo"):
            value = exchange
        elif parsed.path.endswith("categories/list"):
            value = category_list
        elif parsed.path.endswith("coins/markets"):
            category_id = query["category"][0]
            value = [
                {
                    "id": f"{base.lower()}-coin",
                    "symbol": base.lower(),
                    "name": base,
                    "market_cap": 100 - index,
                    "category": category_id,
                }
                for index, base in enumerate(bases)
            ]
        elif parsed.path.endswith("klines"):
            symbol = query["symbol"][0]
            start = research.SNAPSHOT_CUTOFF - datetime.timedelta(days=28)
            offset = bases.index(symbol[:-4]) + 1
            value = [
                [
                    int((start + datetime.timedelta(days=index)).timestamp() * 1000),
                    "1",
                    "1",
                    "1",
                    "1",
                    "1",
                    "1",
                    str(offset * 1_000_000 + index),
                ]
                for index in range(28)
            ]
        else:
            raise AssertionError(url)
        return json.dumps(value, separators=(",", ":")).encode()

    result = research.snapshot_sources(
        protocol_path,
        tmp_path / "sources",
        fetcher=fake_fetch,
        sleeper=lambda _seconds: None,
    )

    assert result["manifest"]["protocol_sha256"] == frozen["protocol_sha256"]
    assert result["manifest"]["orders_authorized"] is False
    assert result["universe"]["selected_contracts"] == 4
    assert len(result["manifest"]["raw_artifacts"]) == 36
    loaded = research._load_snapshot(result["directory"], frozen["protocol_sha256"])
    assert loaded[2] == result["universe"]

    with pytest.raises(FileExistsError, match="single-run"):
        research.snapshot_sources(
            protocol_path,
            tmp_path / "sources",
            fetcher=lambda _url: pytest.fail("second run reached the network"),
            sleeper=lambda _seconds: None,
        )

    manifest_path = pathlib.Path(result["directory"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["created_at"] = "tampered"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(research.DataQualityError, match="content hash mismatch"):
        research._load_snapshot(result["directory"], frozen["protocol_sha256"])


def test_market_panel_assigns_boundary_funding_without_lookahead():
    day = research.DAY_MILLISECONDS
    start = int(research.HISTORY_START.timestamp() * 1000)
    klines = {
        "AAAUSDT": [
            [start + index * day, "1", "1", "1", str(100 + index), "1", "1", "10"]
            for index in range(3)
        ]
    }
    funding = {
        "AAAUSDT": [
            {"fundingTime": start + 8 * 3_600_000, "fundingRate": "0.001"},
            {"fundingTime": start + 16 * 3_600_000, "fundingRate": "0.002"},
            {"fundingTime": start + day, "fundingRate": "0.003"},
            {"fundingTime": start + day + 8 * 3_600_000, "fundingRate": "0.004"},
        ]
    }

    panel, coverage = research._build_market_panel(["AAAUSDT"], klines, funding)

    assert panel["closes"][0, 0] == 100
    assert panel["funding_rates"][0, 0] == pytest.approx(0.006)
    assert panel["funding_counts"][0, 0] == 3
    assert panel["funding_rates"][1, 0] == pytest.approx(0.004)
    assert coverage["AAAUSDT"]["internal_price_gaps"] == 0
