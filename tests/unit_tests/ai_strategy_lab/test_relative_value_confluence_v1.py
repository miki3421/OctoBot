import json
import datetime
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import relative_value_confluence_v1 as confluence


def test_protocol_is_result_free_and_cannot_trade():
    protocol = confluence.frozen_protocol()

    assert protocol["status"] == "result_free_evaluation_protocol"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False


def test_protocol_freezes_the_three_way_intersection():
    signal = confluence.frozen_protocol()["signal"]

    assert signal["formation_blocks"] == 21
    assert signal["long_intersection"].startswith("bottom log-basis")
    assert signal["short_intersection"].startswith("top log-basis")
    assert signal["maximum_assets_per_side"] == 3
    assert signal["paired_side_requirement"].startswith("flat unless both")
    assert signal["side_gross_exposure"] == pytest.approx(0.4)
    assert signal["maximum_portfolio_gross"] == pytest.approx(0.8)
    assert signal["learned_thresholds"] is None
    assert signal["filters"] is None
    assert signal["other_lookbacks"] is None


def test_protocol_keeps_costs_and_sealed_periods():
    protocol = confluence.frozen_protocol()

    assert protocol["economics"]["fee_per_turnover"] == pytest.approx(0.0006)
    assert protocol["economics"]["slippage_per_turnover"] == pytest.approx(
        0.0002
    )
    assert protocol["economics"]["stress_cost_multiplier"] == 3
    assert protocol["economics"]["cost_reduction_relative_to_prior_tests"] is False
    assert protocol["validation"]["confirmation_status"] == (
        "sealed_for_confluence_family"
    )
    assert protocol["validation"]["locked_status"] == (
        "sealed_for_confluence_family"
    )


def test_protocol_freezes_strict_activity_and_robustness_gates():
    gate = confluence.frozen_protocol()["development_gate"]

    assert gate["minimum_blocks"] == 2000
    assert gate["minimum_invested_blocks"] == 250
    assert gate["minimum_sharpe"] == pytest.approx(1.0)
    assert gate["minimum_profit_factor"] == pytest.approx(1.1)
    assert gate["minimum_positive_folds"] == 4
    assert gate["minimum_positive_leave_one_symbol_out"] == 15
    assert gate["stress_total_return_positive"] is True
    assert gate["both_side_contributions_nonnegative"] is True


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = confluence.write_or_verify_protocol(path)
    second = confluence.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == confluence.common._json_hash(
        confluence.frozen_protocol()
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["signal"]["formation_blocks"] = 20
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        confluence.write_or_verify_protocol(path)


def _synthetic_market(blocks=100, assets=18):
    first = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
    timestamps = numpy.asarray(
        [
            int((first + datetime.timedelta(hours=8 * index)).timestamp())
            for index in range(blocks)
        ],
        dtype=numpy.int64,
    )
    return {
        "timestamps": timestamps,
        "symbols": [f"ASSET{index:02d}/USDT:USDT" for index in range(assets)],
        "closes": numpy.full((blocks, assets), 100.0),
        "spot_closes": numpy.full((blocks, assets), 100.0),
        "returns": numpy.zeros((blocks, assets)),
        "funding": numpy.zeros((blocks, assets)),
        "signed_flow": numpy.zeros((blocks, assets)),
        "quote_volume": numpy.ones((blocks, assets)),
    }


def _negative_report(include_trajectory=False):
    report = {
        "blocks": 2200,
        "invested_blocks": 300,
        "annualized_return": -0.10,
        "total_return": -0.10,
        "sharpe_zero_rate": -1.0,
        "profit_factor": 0.8,
        "maximum_drawdown": 0.10,
        "positive_month_ratio": 0.0,
        "long_additive_contribution": -0.05,
        "short_additive_contribution": -0.05,
        "market_beta": 0.0,
        "maximum_symbol_absolute_contribution_share": 0.10,
    }
    if include_trajectory:
        report["_trajectory"] = {
            "decision_timestamps": [],
            "end_timestamps": [],
            "equity": [],
            "block_return": [],
            "market_return": [],
            "gross_exposure": [],
            "net_exposure": [],
        }
    return report


def test_feature_intersection_is_neutral_and_uses_fixed_directions():
    symbols = [f"ASSET{index:02d}" for index in range(18)]
    log_basis = numpy.arange(18, dtype=float)
    basis_momentum = numpy.arange(17, -1, -1, dtype=float)
    signed_flow = numpy.arange(17, -1, -1, dtype=float)

    target = confluence.target_from_features(
        log_basis, basis_momentum, signed_flow, symbols
    )

    assert numpy.all(target[:3] > 0)
    assert numpy.all(target[-3:] < 0)
    assert numpy.all(target[3:-3] == 0)
    assert numpy.isclose(numpy.sum(target), 0.0, atol=1e-12)
    assert numpy.isclose(numpy.sum(numpy.abs(target)), 0.8)


def test_feature_intersection_stays_flat_when_one_side_is_absent():
    symbols = [f"ASSET{index:02d}" for index in range(18)]
    log_basis = numpy.arange(18, dtype=float)
    basis_momentum = numpy.arange(17, -1, -1, dtype=float)
    signed_flow = numpy.arange(18, dtype=float)

    target = confluence.target_from_features(
        log_basis, basis_momentum, signed_flow, symbols
    )

    assert not numpy.any(target)


def test_signal_does_not_use_future_values_and_gap_resets_formation():
    market = _synthetic_market()
    asset_scale = numpy.linspace(0.999, 1.001, 18)
    for index in range(len(market["timestamps"])):
        market["spot_closes"][index] *= asset_scale**index
        market["signed_flow"][index] = numpy.linspace(10.0, -10.0, 18)
    original = confluence.signal_values(market, 40)
    changed = {key: value for key, value in market.items()}
    for key in ("closes", "spot_closes", "signed_flow", "returns", "funding"):
        changed[key] = market[key].copy()
        changed[key][41:] = 1e9

    for first, second in zip(original, confluence.signal_values(changed, 40)):
        assert numpy.array_equal(first, second)

    changed_gap = {key: value for key, value in market.items()}
    changed_gap["timestamps"] = market["timestamps"].copy()
    changed_gap["timestamps"][30:] += confluence.BLOCK_SECONDS
    assert all(
        numpy.all(numpy.isnan(values))
        for values in confluence.signal_values(changed_gap, 40)
    )
    assert all(
        numpy.all(numpy.isfinite(values))
        for values in confluence.signal_values(changed_gap, 52)
    )


def test_failed_development_keeps_confirmation_and_lock_sealed(
    tmp_path, monkeypatch
):
    protocol_path = tmp_path / "protocol.json"
    confluence.write_or_verify_protocol(protocol_path)
    market = _synthetic_market(blocks=3200)
    monkeypatch.setattr(
        confluence,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    monkeypatch.setattr(
        confluence,
        "build_target_matrix",
        lambda market, **_kwargs: numpy.zeros(
            (len(market["timestamps"]), len(market["symbols"]))
        ),
    )
    calls = []

    def fake_simulation(_market, start, end, **kwargs):
        calls.append((start, end, kwargs.get("cost_multiplier", 1.0)))
        return _negative_report(kwargs.get("include_trajectory", False))

    monkeypatch.setattr(confluence, "simulate_period", fake_simulation)
    result = confluence.evaluate_prelock(
        protocol_path,
        [tmp_path / "unused-futures.data"],
        [tmp_path / "unused-spot.data"],
        [tmp_path / "unused-flow.json"],
        tmp_path / "unused-cache",
        [tmp_path / "unused-funding.json"],
        tmp_path / "experiments",
    )
    report = result["report"]

    assert all(end <= confluence.DEVELOPMENT_END for _, end, _ in calls)
    assert report["confirmation"] is None
    assert report["locked_test"]["authorized_to_open"] is False
    assert report["locked_test"]["materialized"] is False
    saved = json.loads(
        (pathlib.Path(result["directory"]) / "report.json").read_text()
    )
    assert saved["verdict"] == "REJECTED_PRELOCK_LOCK_REMAINS_SEALED"
