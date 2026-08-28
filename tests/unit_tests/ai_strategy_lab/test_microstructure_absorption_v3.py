import json

import numpy
import pytest

from octobot.ai_strategy_lab import microstructure_absorption_v3 as absorption
from octobot.ai_strategy_lab import scalping_strategy_search_v3 as parent


def _features(rows: int) -> numpy.ndarray:
    return numpy.zeros((rows, len(parent.FEATURE_NAMES)), dtype=numpy.float64)


def _set(
    features: numpy.ndarray, name: str, values: numpy.ndarray
) -> None:
    features[:, parent.FEATURE_NAMES.index(name)] = values


def test_protocol_is_result_free_and_cannot_authorize_orders():
    protocol = absorption.frozen_protocol()

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["validation"]["locked_test_materialized"] is False
    assert protocol["hypothesis"]["primary_candidate_count"] == 1
    assert protocol["markout"]["take_profit"] is None


def test_protocol_write_is_immutable(tmp_path):
    path = tmp_path / "protocol.json"
    first = absorption.write_or_verify_protocol(path)

    assert absorption.write_or_verify_protocol(path) == first
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["signal"]["pressure_absolute_quantile"] = 0.95
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="protocol differs"):
        absorption.write_or_verify_protocol(path)


def test_absorption_direction_is_symmetric_and_opposes_pressure():
    features = _features(3)
    _set(
        features,
        absorption.PRESSURE_FEATURE,
        numpy.asarray([10.0, -10.0, 10.0]),
    )
    _set(
        features,
        absorption.REFILL_FEATURE,
        numpy.asarray([-1.0, 1.0, -1.0]),
    )
    _set(
        features,
        absorption.DIVERGENCE_FEATURE,
        numpy.asarray([-2.0, 2.0, -2.0]),
    )
    _set(
        features,
        absorption.PRICE_RESPONSE_FEATURE,
        numpy.asarray([0.5, -0.5, 0.5]),
    )
    _set(
        features,
        absorption.MICROPRICE_CONFIRMATION_FEATURE,
        numpy.asarray([-1.0, 1.0, 1.0]),
    )
    _set(
        features,
        absorption.SPREAD_FEATURE,
        numpy.asarray([0.01, 0.01, 0.01]),
    )
    thresholds = {
        "pressure_absolute_minimum": 5.0,
        "aligned_refill_maximum": 0.0,
        "aligned_divergence_maximum": -1.0,
        "aligned_price_response_maximum_bps": 1.0,
        "spread_maximum_bps": 0.02,
    }

    directions = absorption.absorption_directions(features, thresholds)

    assert directions.tolist() == [-1, 1, 0]


def test_feature_threshold_fit_uses_feature_distribution():
    rows = 2_000
    features = _features(rows)
    signs = numpy.where(numpy.arange(rows) % 2 == 0, 1.0, -1.0)
    magnitudes = numpy.linspace(0.1, 100.0, rows)
    _set(features, absorption.PRESSURE_FEATURE, signs * magnitudes)
    _set(features, absorption.REFILL_FEATURE, signs * -0.5)
    _set(features, absorption.DIVERGENCE_FEATURE, signs * -1.5)
    _set(features, absorption.PRICE_RESPONSE_FEATURE, signs * 2.0)
    _set(
        features,
        absorption.MICROPRICE_CONFIRMATION_FEATURE,
        signs * -0.1,
    )
    _set(features, absorption.SPREAD_FEATURE, numpy.full(rows, 0.02))

    thresholds = absorption.fit_feature_thresholds(features)
    directions = absorption.absorption_directions(features, thresholds)

    assert thresholds["pressure_absolute_minimum"] > 98.0
    assert thresholds["aligned_refill_maximum"] <= 0.0
    assert numpy.count_nonzero(directions) >= 10
    assert numpy.all(directions[directions != 0] == -signs[directions != 0])


def test_non_overlapping_rows_enforces_fixed_horizon():
    timestamps = numpy.asarray([0, 100, 899, 900, 1_799, 1_800])
    directions = numpy.asarray([1, -1, 1, -1, 1, -1], dtype=numpy.int8)

    rows = absorption.non_overlapping_rows(timestamps, directions)

    assert rows.tolist() == [0, 3, 5]


def test_executable_markout_uses_side_quotes_and_costs():
    length = 2_000
    values = numpy.full(length, 100.0)
    source = absorption.QuoteSource(
        start_second=0,
        end_second=length - 1,
        entry_bid_0=values.copy(),
        entry_ask_0=values.copy(),
        entry_bid_500=values.copy(),
        entry_ask_500=values.copy(),
        last_bid=values.copy(),
        last_ask=values.copy(),
        prefix_last_bid_500=values.copy(),
        prefix_last_ask_500=values.copy(),
    )
    source.prefix_last_bid_500[910] = 101.0
    source.prefix_last_ask_500[920] = 99.0
    source.last_bid[910] = 101.0
    source.last_ask[920] = 99.0
    timestamps = numpy.asarray([10, 20], dtype=numpy.int64)
    directions = numpy.asarray([1, -1], dtype=numpy.int8)

    primary = absorption.executable_markouts(
        source, timestamps, directions, stress=False
    )
    stress = absorption.executable_markouts(
        source, timestamps, directions, stress=True
    )

    assert primary[0] == pytest.approx(0.01 - 0.0014)
    assert primary[1] == pytest.approx(100.0 / 99.0 - 1.0 - 0.0014)
    assert stress[0] == pytest.approx(0.01 - 0.0028)
    assert stress[1] == pytest.approx(100.0 / 99.0 - 1.0 - 0.0028)


def test_gate_requires_both_directions_and_stress_profit():
    timestamps = numpy.arange(60, dtype=numpy.int64) * 86_400
    directions = numpy.asarray([1, -1] * 30, dtype=numpy.int8)
    returns = numpy.full(60, 0.002)
    primary = absorption.trade_metrics(
        timestamps, directions, returns, bootstrap=True
    )
    stress = absorption.trade_metrics(
        timestamps, directions, returns / 2.0, bootstrap=False
    )

    result = absorption.gate(
        primary,
        stress,
        confirmation=False,
        positive_folds=5,
    )

    assert result["passed"] is True
    stress["total_return"] = -0.01
    assert (
        absorption.gate(
            primary,
            stress,
            confirmation=False,
            positive_folds=5,
        )["passed"]
        is False
    )
