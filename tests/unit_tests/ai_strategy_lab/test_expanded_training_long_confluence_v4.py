import json
import datetime
import pathlib

import numpy
import pytest

from octobot.ai_strategy_lab import expanded_training_long_confluence_v4 as v4


def test_protocol_is_result_free_and_cannot_trade():
    protocol = v4.frozen_protocol()

    assert protocol["status"] == "expanded_training_pre_2026_oos"
    assert protocol["results"] is None
    assert protocol["research_only"] is True
    assert protocol["public_data_only"] is True
    assert protocol["credentials_used"] is False
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False


def test_grid_is_exactly_sixteen_candidates():
    candidates = v4.candidate_configurations()

    assert len(candidates) == 16
    assert {item["rebalance_blocks"] for item in candidates} == {3, 9, 21, 42}
    assert {item["regime"] for item in candidates} == set(v4.REGIMES)
    assert len({item["configuration_id"] for item in candidates}) == 16


def test_training_includes_2025_but_2026_is_single_sealed_oos():
    protocol = v4.frozen_protocol()

    assert protocol["lineage"]["2025_is_oos_for_v4"] is False
    assert protocol["training"]["period"][1].startswith("2026-01-01")
    assert len(protocol["training"]["folds"]) == 7
    assert protocol["oos_test"]["status"] == "sealed_single_query"
    assert protocol["oos_test"]["failed_model_replacement"] is False


def test_selection_and_oos_gate_are_frozen():
    protocol = v4.frozen_protocol()

    assert protocol["training"]["selection"]["selection_count"] == 1
    assert protocol["training"]["selection"]["selection_is_economic_pass"] is False
    assert protocol["oos_test"]["gate"]["minimum_sharpe"] == pytest.approx(0.5)
    assert protocol["oos_test"]["gate"]["stress_total_return_positive"] is True
    assert protocol["forward_gate"]["minimum_calendar_days"] == 180


def test_protocol_persistence_is_content_addressed_and_fail_closed(tmp_path):
    path = tmp_path / "protocol.json"
    first = v4.write_or_verify_protocol(path)
    second = v4.write_or_verify_protocol(path)

    assert first == second
    assert first["protocol_sha256"] == v4.common._json_hash(v4.frozen_protocol())

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training_grid"]["configuration_count"] = 15
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol differs"):
        v4.write_or_verify_protocol(path)


def _market(blocks=500, assets=18):
    first = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
    timestamps = numpy.asarray(
        [
            int((first + datetime.timedelta(hours=8 * index)).timestamp())
            for index in range(blocks)
        ],
        dtype=numpy.int64,
    )
    closes = numpy.ones((blocks, assets), dtype=numpy.float64)
    return {
        "timestamps": timestamps,
        "symbols": [f"ASSET{index:02d}" for index in range(assets)],
        "closes": closes,
        "spot_closes": closes.copy(),
        "returns": numpy.zeros_like(closes),
        "funding": numpy.zeros_like(closes),
        "signed_flow": numpy.zeros_like(closes),
        "quote_volume": numpy.ones_like(closes),
    }


def test_regimes_are_causal_and_dual_requires_both_windows():
    market = _market()
    market["closes"] *= numpy.linspace(1.0, 2.0, len(market["timestamps"]))[:, None]

    assert v4._regime_passes(market, 300, "ew_28d_positive") is True
    assert v4._regime_passes(market, 300, "ew_84d_positive") is True
    assert v4._regime_passes(market, 300, "ew_28d_and_84d_positive") is True

    changed = {key: value for key, value in market.items()}
    changed["closes"] = market["closes"].copy()
    changed["closes"][301:] = 1e9
    assert v4._regime_passes(changed, 300, "ew_84d_positive") is True


def test_selection_prefers_stress_fold_count_then_worst_fold():
    def candidate(identifier, stress_returns):
        folds = [
            {
                "total_return": value,
                "sharpe_zero_rate": value,
                "invested_blocks": 50,
            }
            for value in stress_returns
        ]
        return {
            "configuration": {"configuration_id": identifier},
            "development": {
                "annualized_market_alpha": 0.1,
                "total_turnover": 10.0,
            },
            "stress_folds": folds,
            "eligibility": {"passed": True},
        }

    candidates = [
        candidate("a", [0.1, 0.1, -0.01]),
        candidate("b", [0.2, 0.2, 0.001]),
        candidate("c", [0.3, 0.3, -0.001]),
    ]

    assert v4.select_candidate(candidates)["configuration"][
        "configuration_id"
    ] == "b"


def test_training_never_reads_2026_and_freezes_one_model(tmp_path, monkeypatch):
    protocol_path = tmp_path / "protocol.json"
    v4.write_or_verify_protocol(protocol_path)
    v3_report = tmp_path / "v3-report.json"
    v3_report.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        v4, "EXPECTED_V3_REPORT_SHA256", v4.common._sha256(v3_report)
    )
    market = _market(blocks=5000)
    monkeypatch.setattr(
        v4.engine.parent,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    monkeypatch.setattr(
        v4,
        "build_target_matrix",
        lambda *_args, **_kwargs: numpy.zeros((5000, 18)),
    )
    calls = []

    def fake_simulation(_market, start, end, **kwargs):
        calls.append((start, end))
        report = {
            "invested_blocks": 500,
            "total_return": 0.1,
            "annualized_return": 0.1,
            "annualized_market_alpha": 0.1,
            "sharpe_zero_rate": 1.0,
            "maximum_drawdown": 0.1,
            "market_beta": 0.1,
            "maximum_symbol_absolute_contribution_share": 0.1,
            "total_turnover": 10.0,
        }
        if kwargs.get("include_trajectory"):
            report["_trajectory"] = {}
        return report

    monkeypatch.setattr(v4.engine, "simulate_period", fake_simulation)
    result = v4.train_and_freeze(
        protocol_path,
        v3_report,
        [tmp_path / "futures"],
        [tmp_path / "spot"],
        [tmp_path / "flow"],
        tmp_path / "cache",
        [tmp_path / "funding"],
        tmp_path / "training",
    )

    assert all(end <= v4.TRAINING_END for _, end in calls)
    assert result["report"]["oos_2026_evaluated"] is False
    assert result["report"]["selected_configuration"] is not None
    assert pathlib.Path(result["report"]["selected_model_path"]).is_file()
    assert result["manifest"]["orders_authorized"] is False
