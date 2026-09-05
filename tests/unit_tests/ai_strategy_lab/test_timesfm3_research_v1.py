import json

import numpy
import pytest

from octobot.ai_strategy_lab import timesfm3_research_v1 as timesfm3


def _panel(rows=None):
    rows = rows or timesfm3.CONTEXT_HOURS + timesfm3.HORIZON_HOURS + 48
    timestamps = 1_700_006_400 + numpy.arange(rows) * 3_600
    timestamps -= timestamps[0] % 3_600
    assets = len(timesfm3.ASSETS)
    candles = numpy.zeros((assets, rows, 6), dtype=float)
    spot = numpy.zeros_like(candles)
    for asset in range(assets):
        close = 100 * (asset + 1) * numpy.exp(numpy.arange(rows) * 0.0001)
        open_price = numpy.concatenate(([close[0]], close[:-1]))
        candles[asset, :, 0] = timestamps
        candles[asset, :, 1] = open_price
        candles[asset, :, 2] = numpy.maximum(open_price, close) * 1.001
        candles[asset, :, 3] = numpy.minimum(open_price, close) * 0.999
        candles[asset, :, 4] = close
        candles[asset, :, 5] = 100 + numpy.arange(rows)
        spot[asset] = candles[asset]
        spot[asset, :, 4] *= 0.999
    return timesfm3.MarketPanel(
        open_timestamps=timestamps,
        futures_candles=candles,
        spot_candles=spot,
        funding_rates=numpy.full((assets, rows), 0.0001),
    )


def test_protocol_is_result_free_and_orderless():
    protocol = timesfm3.frozen_protocol()

    assert protocol["results"] is None
    assert protocol["license_gate"]["accepted_in_this_protocol"] is False
    assert protocol["license_gate"]["weights_downloaded_in_this_protocol"] is False
    assert protocol["runtime_boundaries"]["orders_authorized"] is False
    assert protocol["runtime_boundaries"]["paper_orders_authorized"] is False
    assert protocol["runtime_boundaries"]["container_network"] == "none during inference and evaluation"
    assert protocol["inputs"]["total_variates"] <= protocol["model"]["maximum_variates"]


def test_protocol_write_is_immutable(tmp_path):
    path = timesfm3.write_protocol(tmp_path / "protocol.json")
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert persisted["protocol_sha256"] == timesfm3.logical_hash(timesfm3.frozen_protocol())
    assert timesfm3.write_protocol(path) == path
    persisted["results"] = {"peeked": True}
    path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(timesfm3.DataQualityError, match="differs"):
        timesfm3.write_protocol(path)


def test_causal_query_has_frozen_geometry():
    panel = _panel()
    origin = timesfm3.CONTEXT_HOURS + 12
    query = timesfm3.build_causal_query(panel, origin)

    assert query.targets.shape == (4, 1_536)
    assert query.past_only_covariates.shape == (16, 1_536)
    assert query.past_future_covariates.shape == (5, 1_560)
    assert timesfm3.TOTAL_VARIATES == 25


def test_future_price_edit_cannot_change_query():
    panel = _panel()
    origin = timesfm3.CONTEXT_HOURS + 12
    original = timesfm3.build_causal_query(panel, origin)
    changed_futures = panel.futures_candles.copy()
    changed_spot = panel.spot_candles.copy()
    changed_futures[:, origin + 1 :, 1:6] *= 2
    changed_spot[:, origin + 1 :, 1:6] *= 3
    changed = dataclass_replace(
        panel,
        futures_candles=changed_futures,
        spot_candles=changed_spot,
    )
    updated = timesfm3.build_causal_query(changed, origin)

    numpy.testing.assert_array_equal(original.targets, updated.targets)
    numpy.testing.assert_array_equal(
        original.past_only_covariates,
        updated.past_only_covariates,
    )
    numpy.testing.assert_array_equal(
        original.past_future_covariates,
        updated.past_future_covariates,
    )


def dataclass_replace(value, **changes):
    values = {
        field.name: getattr(value, field.name)
        for field in value.__dataclass_fields__.values()
    }
    values.update(changes)
    return type(value)(**values)


def test_license_gate_requires_explicit_matching_record(tmp_path):
    missing = tmp_path / "acceptance.json"
    with pytest.raises(timesfm3.LicenseAcceptanceRequired):
        timesfm3.validate_license_acceptance(missing)

    payload = {
        "schema_version": 1,
        "model_repository": timesfm3.MODEL_REPOSITORY,
        "model_revision": timesfm3.MODEL_REVISION,
        "license_id": timesfm3.MODEL_LICENSE_ID,
        "accepted": True,
        "noncommercial_research_only": True,
        "production_use": False,
        "commercial_use": False,
        "accepted_by": "test-user",
        "accepted_at": "2026-09-03T00:00:00+00:00",
    }
    missing.write_text(json.dumps(payload), encoding="utf-8")
    assert timesfm3.validate_license_acceptance(missing) == payload

    payload["production_use"] = True
    missing.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(timesfm3.LicenseAcceptanceRequired, match="differs"):
        timesfm3.validate_license_acceptance(missing)


def test_implementation_lock_rejects_a_peeked_preflight(tmp_path):
    protocol_path = timesfm3.write_protocol(tmp_path / "protocol.json")
    preflight = {
        "protocol_sha256": timesfm3.logical_hash(timesfm3.frozen_protocol()),
        "economic_outcomes_read": True,
        "model_forecasts_run": False,
        "license_accepted": False,
        "weights_downloaded": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "results": None,
    }
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(
        json.dumps(
            {
                "timesfm": timesfm3.TIMESFM_PACKAGE_VERSION,
                "torch": timesfm3.TORCH_CPU_VERSION,
                "cuda_available": False,
                "model_weights_loaded": False,
                "credentials_used": False,
                "orders_authorized": False,
                "paper_orders_authorized": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(timesfm3.DataQualityError, match="result-free"):
        timesfm3.write_implementation_lock(
            protocol_value=protocol_path,
            preflight_value=preflight_path,
            environment_value=environment_path,
            artifacts={"source": __file__},
            image_id="sha256:" + "a" * 64,
            output_value=tmp_path / "lock.json",
        )
