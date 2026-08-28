import datetime
import json
import pathlib

import numpy

from octobot.ai_strategy_lab import training_selected_long_confluence_v3_oos as oos


def _report(passes=False, include_trajectory=False):
    positive = 0.10 if passes else -0.10
    report = {
        "blocks": 1100,
        "invested_blocks": 300,
        "total_return": positive,
        "annualized_return": positive,
        "annualized_market_alpha": positive,
        "sharpe_zero_rate": 1.0 if passes else -1.0,
        "profit_factor": 1.5 if passes else 0.8,
        "maximum_drawdown": 0.1,
        "positive_month_ratio": 0.75 if passes else 0.25,
        "market_beta": 0.2,
        "maximum_symbol_absolute_contribution_share": 0.2,
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


def _market():
    timestamps = numpy.arange(2000, dtype=numpy.int64) * oos.trainer.BLOCK_SECONDS
    shape = (2000, 18)
    return {
        "timestamps": timestamps,
        "symbols": [f"ASSET{index:02d}" for index in range(18)],
        "closes": numpy.ones(shape),
        "spot_closes": numpy.ones(shape),
        "returns": numpy.zeros(shape),
        "funding": numpy.zeros(shape),
        "signed_flow": numpy.zeros(shape),
        "quote_volume": numpy.ones(shape),
    }


def _frozen_files(tmp_path, monkeypatch):
    protocol_path = tmp_path / "protocol.json"
    protocol = oos.selection.write_or_verify_protocol(protocol_path)
    model_path = tmp_path / "model.json"
    model = {
        "protocol_sha256": protocol["protocol_sha256"],
        "selected_configuration": next(
            item
            for item in oos.trainer.candidate_configurations()
            if item["configuration_id"] == oos.selection.SELECTED_CONFIGURATION_ID
        ),
        "confirmation_evaluated": False,
        "locked_test_evaluated": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
    }
    model["content_sha256"] = oos.common._json_hash(model)
    model_path.write_text(json.dumps(model), encoding="utf-8")
    monkeypatch.setattr(
        oos, "EXPECTED_PROTOCOL_FILE_SHA256", oos.common._sha256(protocol_path)
    )
    monkeypatch.setattr(
        oos,
        "EXPECTED_SELECTION_MODEL_FILE_SHA256",
        oos.common._sha256(model_path),
    )
    monkeypatch.setattr(
        oos,
        "EXPECTED_SELECTION_MODEL_CONTENT_SHA256",
        model["content_sha256"],
    )
    return protocol_path, model_path


def test_frozen_inputs_reject_tampered_model(tmp_path, monkeypatch):
    protocol_path, model_path = _frozen_files(tmp_path, monkeypatch)
    model_path.write_text("{}", encoding="utf-8")

    try:
        oos.verify_frozen_inputs(protocol_path, model_path)
    except ValueError as error:
        assert "hash differs" in str(error)
    else:
        raise AssertionError("tampered model unexpectedly accepted")


def test_failed_confirmation_never_reads_locked_test(tmp_path, monkeypatch):
    protocol_path, model_path = _frozen_files(tmp_path, monkeypatch)
    market = _market()
    monkeypatch.setattr(
        oos.market_loader,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    monkeypatch.setattr(
        oos.trainer,
        "build_target_matrix",
        lambda *_args, **_kwargs: numpy.zeros((2000, 18)),
    )
    calls = []

    def fake_simulation(_market, start, end, **kwargs):
        calls.append((start, end))
        return _report(False, kwargs.get("include_trajectory", False))

    monkeypatch.setattr(oos.trainer, "simulate_period", fake_simulation)
    result = oos.evaluate_oos(
        protocol_path,
        model_path,
        [tmp_path / "futures"],
        [tmp_path / "spot"],
        [tmp_path / "flow"],
        tmp_path / "cache",
        [tmp_path / "funding"],
        tmp_path / "results",
    )

    assert all(end <= oos.selection.CONFIRMATION_END for _, end in calls)
    assert result["report"]["locked_test"]["materialized"] is False
    assert result["report"]["historical_candidate"] is False
    assert result["manifest"]["orders_authorized"] is False


def test_full_confirmation_pass_is_required_before_lock(tmp_path, monkeypatch):
    protocol_path, model_path = _frozen_files(tmp_path, monkeypatch)
    market = _market()
    monkeypatch.setattr(
        oos.market_loader,
        "load_market",
        lambda *_args, **_kwargs: (market, {"fixture": True}),
    )
    monkeypatch.setattr(
        oos.trainer,
        "build_target_matrix",
        lambda *_args, **_kwargs: numpy.zeros((2000, 18)),
    )
    calls = []

    def fake_simulation(_market, start, end, **kwargs):
        calls.append((start, end))
        return _report(True, kwargs.get("include_trajectory", False))

    monkeypatch.setattr(oos.trainer, "simulate_period", fake_simulation)
    result = oos.evaluate_oos(
        protocol_path,
        model_path,
        [tmp_path / "futures"],
        [tmp_path / "spot"],
        [tmp_path / "flow"],
        tmp_path / "cache",
        [tmp_path / "funding"],
        tmp_path / "results",
    )

    assert any(start >= oos.selection.LOCKED_START for start, _ in calls)
    assert result["report"]["locked_test"]["materialized"] is True
    assert result["report"]["historical_candidate"] is True
    assert result["report"]["orders_authorized"] is False
