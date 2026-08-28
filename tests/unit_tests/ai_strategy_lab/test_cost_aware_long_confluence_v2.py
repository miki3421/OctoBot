import json
import datetime
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import cost_aware_long_confluence_v2 as strategy


def test_protocol_is_result_free_public_only_and_cannot_trade():
    protocol = strategy.frozen_protocol()

    assert protocol["status"] == "result_free_training_and_oos_protocol"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False


def test_training_grid_is_exactly_the_six_frozen_candidates():
    candidates = strategy.candidate_configurations()

    assert len(candidates) == 6
    assert {item["rebalance_blocks"] for item in candidates} == {3, 9, 21}
    assert {item["regime"] for item in candidates} == {
        "always_on",
        "ew_market_28d_positive",
    }
    assert len({item["configuration_id"] for item in candidates}) == 6


def test_protocol_declares_development_as_training_and_2025_as_first_oos():
    protocol = strategy.frozen_protocol()

    assert protocol["design_disclosure"]["development_is_evidence"] is False
    assert protocol["training"]["status"] == (
        "training_reuse_not_promotional_evidence"
    )
    assert protocol["confirmation"]["status"] == "sealed_first_oos_for_v2"
    assert protocol["locked_test"]["status"].startswith("sealed")


def test_protocol_freezes_costs_selection_and_strict_oos_gates():
    protocol = strategy.frozen_protocol()

    assert protocol["economics"]["fee_per_turnover"] == pytest.approx(0.0006)
    assert protocol["economics"]["slippage_per_turnover"] == pytest.approx(
        0.0002
    )
    assert protocol["economics"]["stress_cost_multiplier"] == 3
    assert protocol["training"]["selection"]["selection_count"] == 1
    assert protocol["training"]["candidate_gate"]["minimum_positive_folds"] == 4
    assert protocol["confirmation"]["gate"]["minimum_sharpe"] == pytest.approx(
        0.75
    )
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = strategy.write_or_verify_protocol(path)
    second = strategy.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == strategy.common._json_hash(
        strategy.frozen_protocol()
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training_grid"]["configurations"][0]["rebalance_blocks"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        strategy.write_or_verify_protocol(path)


def _market(blocks=400, assets=18):
    first = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
    timestamps = numpy.asarray(
        [
            int((first + datetime.timedelta(hours=8 * index)).timestamp())
            for index in range(blocks)
        ],
        dtype=numpy.int64,
    )
    closes = numpy.full((blocks, assets), 100.0)
    spot_closes = numpy.full((blocks, assets), 100.0)
    return {
        "timestamps": timestamps,
        "symbols": [f"ASSET{index:02d}/USDT:USDT" for index in range(assets)],
        "closes": closes,
        "spot_closes": spot_closes,
        "returns": numpy.zeros_like(closes),
        "funding": numpy.zeros_like(closes),
        "signed_flow": numpy.zeros_like(closes),
        "quote_volume": numpy.ones_like(closes),
    }


def test_long_intersection_has_no_short_and_does_not_require_short_candidate():
    symbols = [f"ASSET{index:02d}" for index in range(18)]
    log_basis = numpy.arange(18, dtype=float)
    momentum = numpy.arange(17, -1, -1, dtype=float)
    flow = numpy.arange(17, -1, -1, dtype=float)

    target = strategy.long_target_from_features(
        log_basis, momentum, flow, symbols
    )

    assert numpy.all(target[:3] > 0)
    assert numpy.all(target[3:] == 0)
    assert numpy.isclose(numpy.sum(target), 0.4)


def test_slow_target_changes_only_on_frozen_boundaries(monkeypatch):
    market = _market()
    configuration = next(
        item
        for item in strategy.candidate_configurations()
        if item["rebalance_blocks"] == 9 and item["regime"] == "always_on"
    )
    calls = []

    def fake_signal(_market, index):
        calls.append(index)
        values = numpy.arange(18, dtype=float)
        return values, values[::-1], values[::-1]

    monkeypatch.setattr(strategy.parent, "signal_values", fake_signal)
    targets = strategy.build_target_matrix(market, configuration)

    changed = numpy.flatnonzero(
        numpy.any(numpy.diff(targets, axis=0) != 0, axis=1)
    )
    assert all(
        strategy._is_rebalance_boundary(
            int(market["timestamps"][index]), 9
        )
        for index in calls
    )
    assert all(
        strategy._is_rebalance_boundary(
            int(market["timestamps"][index + 1]), 9
        )
        for index in changed
    )


def test_regime_is_causal_and_fails_closed_across_gap():
    market = _market()
    trend = numpy.linspace(1.0, 2.0, len(market["timestamps"]))[:, None]
    market["closes"] *= trend

    assert strategy._market_regime_is_positive(market, 100) is True
    changed = {key: value for key, value in market.items()}
    changed["closes"] = market["closes"].copy()
    changed["closes"][101:] = 1e9
    assert strategy._market_regime_is_positive(changed, 100) is True

    changed["timestamps"] = market["timestamps"].copy()
    changed["timestamps"][50:] += strategy.BLOCK_SECONDS
    assert strategy._market_regime_is_positive(changed, 100) is False


def test_selection_is_maximin_then_median_then_turnover_then_id():
    def candidate(identifier, minimum, median, turnover):
        folds = [
            {"total_return": minimum, "sharpe_zero_rate": median},
            {"total_return": 0.2, "sharpe_zero_rate": median},
        ]
        return {
            "configuration": {"configuration_id": identifier},
            "development": {"total_turnover": turnover},
            "folds": folds,
            "gate": {"passed": True},
        }

    candidates = [
        candidate("b", 0.01, 2.0, 10.0),
        candidate("c", 0.02, 1.0, 20.0),
        candidate("a", 0.02, 1.0, 20.0),
    ]

    assert strategy.select_candidate(candidates)["configuration"][
        "configuration_id"
    ] == "a"


def test_training_failure_never_authorizes_confirmation(tmp_path, monkeypatch):
    protocol_path = tmp_path / "protocol.json"
    strategy.write_or_verify_protocol(protocol_path)
    addendum = tmp_path / "addendum.md"
    addendum.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(
        strategy,
        "EXPECTED_METRIC_ADDENDUM_SHA256",
        strategy.common._sha256(addendum),
    )
    market = _market(blocks=3200)
    monkeypatch.setattr(
        strategy.parent,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    monkeypatch.setattr(
        strategy,
        "build_target_matrix",
        lambda *_args, **_kwargs: numpy.zeros(
            (len(market["timestamps"]), len(market["symbols"]))
        ),
    )
    calls = []

    def fake_simulation(_market, start, end, **kwargs):
        calls.append((start, end))
        report = {
            "blocks": 2200,
            "invested_blocks": 0,
            "total_return": -0.1,
            "annualized_return": -0.1,
            "annualized_market_alpha": -0.1,
            "sharpe_zero_rate": -1.0,
            "profit_factor": 0.8,
            "maximum_drawdown": 0.1,
            "positive_month_ratio": 0.0,
            "market_beta": 0.0,
            "maximum_symbol_absolute_contribution_share": 0.1,
            "total_turnover": 0.0,
        }
        if kwargs.get("include_trajectory"):
            report["_trajectory"] = {}
        return report

    monkeypatch.setattr(strategy, "simulate_period", fake_simulation)
    result = strategy.train_design(
        protocol_path,
        addendum,
        [tmp_path / "futures"],
        [tmp_path / "spot"],
        [tmp_path / "flow"],
        tmp_path / "cache",
        [tmp_path / "funding"],
        tmp_path / "designs",
    )

    assert all(end <= strategy.DEVELOPMENT_END for _, end in calls)
    assert result["report"]["selected_configuration"] is None
    assert result["report"]["confirmation_access_authorized"] is False
    assert result["manifest"]["selected_model_path"] is None
    assert not (pathlib.Path(result["directory"]) / "selected-model.json").exists()
