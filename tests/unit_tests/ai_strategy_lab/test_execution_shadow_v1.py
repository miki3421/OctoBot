import datetime
import json
import sqlite3

import numpy
import pytest

from octobot.ai_strategy_lab import execution_shadow_v1 as shadow
from octobot.ai_strategy_lab import maker_execution_v1 as v1
from octobot.ai_strategy_lab import maker_execution_v2 as v2


START = "2026-08-28T10:00:00+00:00"


def test_protocol_is_future_aligned_result_free_and_orderless(tmp_path):
    start_ns = v1._epoch_ns(START)
    protocol = shadow.frozen_protocol(START)
    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["prediction"]["late_action"].startswith("append permanent")
    assert protocol["official_forward_gate"]["observation_days"] == 30
    path = tmp_path / "protocol.json"
    first = shadow.write_or_verify_protocol(path, START, now_ns=start_ns - 1)
    assert first == shadow.write_or_verify_protocol(
        path, START, now_ns=start_ns + 1
    )
    with pytest.raises(ValueError, match="start in the future"):
        shadow.write_or_verify_protocol(
            tmp_path / "past.json", START, now_ns=start_ns
        )
    with pytest.raises(ValueError, match="quarter hour"):
        shadow.frozen_protocol("2026-08-28T10:01:00+00:00")


def _journal(tmp_path):
    protocol = {
        **shadow.frozen_protocol(START),
    }
    protocol["protocol_sha256"] = v2._json_hash(protocol)
    connection = shadow._open_journal(tmp_path / "journal.sqlite")
    shadow._initialize_metadata(connection, protocol)
    return connection, protocol


def test_journal_is_append_only_and_hash_chained(tmp_path):
    connection, _ = _journal(tmp_path)
    start = v1._epoch_ns(START)
    first = shadow._append_decision(
        connection,
        decision_ns=start,
        side="buy",
        recorded_at_ns=start + 2_000_000_000,
        status="MISSED",
        reason="test",
        features=None,
        fill_probability=None,
        predicted_fallback=None,
        expected_saving=None,
        selected=None,
    )
    second = shadow._append_decision(
        connection,
        decision_ns=start,
        side="sell",
        recorded_at_ns=start + 2_000_000_000,
        status="MISSED",
        reason="test",
        features=None,
        fill_probability=None,
        predicted_fallback=None,
        expected_saving=None,
        selected=None,
    )
    connection.commit()
    row = connection.execute(
        "SELECT previous_record_hash,record_hash FROM decisions WHERE side='sell'"
    ).fetchone()
    assert row["previous_record_hash"] == first
    assert row["record_hash"] == second
    assert shadow._verify_tail(connection) is True
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("UPDATE decisions SET reason='changed'")
    connection.rollback()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("DELETE FROM metadata")
    connection.rollback()
    connection.execute("DROP TRIGGER decisions_no_update")
    connection.execute(
        "UPDATE decisions SET expected_saving_bps=99 WHERE side='sell'"
    )
    connection.commit()
    assert shadow._verify_tail(connection) is False
    connection.close()


def test_late_predictions_are_missed_without_loading_market_data(
    tmp_path, monkeypatch
):
    journal, protocol = _journal(tmp_path)
    start = v1._epoch_ns(START)
    monkeypatch.setattr(
        v2,
        "_load_window",
        lambda *args: pytest.fail("late prediction queried market data"),
    )
    result = shadow._process_predictions(
        None,
        journal,
        protocol,
        None,
        now_ns=start + 16_000_000_000,
        collector_healthy=True,
    )
    assert result == {"predicted": 0, "missed": 2}
    assert [
        tuple(row)
        for row in journal.execute(
            "SELECT side,status,reason FROM decisions ORDER BY side"
        )
    ] == [
        ("buy", "MISSED", "prediction_deadline_missed"),
        ("sell", "MISSED", "prediction_deadline_missed"),
    ]
    journal.close()


class _FakeModel:
    def predict(self, features):
        rows = len(features)
        return (
            numpy.full(rows, 0.5),
            numpy.full(rows, -0.2),
            numpy.full(rows, 1.0),
        )


def test_timely_predictions_are_stored_before_outcomes(tmp_path, monkeypatch):
    journal, protocol = _journal(tmp_path)
    start = v1._epoch_ns(START)
    features = numpy.arange(len(v2.FEATURE_NAMES), dtype=numpy.float64)
    monkeypatch.setattr(v2, "_load_window", lambda source, decision: object())
    monkeypatch.setattr(v2, "_features", lambda window, side: features.copy())
    result = shadow._process_predictions(
        object(),
        journal,
        protocol,
        _FakeModel(),
        now_ns=start + 3_000_000_000,
        collector_healthy=True,
    )
    assert result == {"predicted": 2, "missed": 0}
    rows = journal.execute(
        "SELECT status,selected,recorded_at_ns,features_json FROM decisions"
    ).fetchall()
    assert len(rows) == 2
    assert all(row["status"] == "PREDICTED" for row in rows)
    assert all(row["selected"] == 1 for row in rows)
    assert all(row["recorded_at_ns"] <= start + 15_000_000_000 for row in rows)
    assert json.loads(rows[0]["features_json"]) == features.tolist()
    assert journal.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 0
    journal.close()


def test_outcome_waits_for_maturity_and_fee_neutralizes_stress(
    tmp_path, monkeypatch
):
    journal, protocol = _journal(tmp_path)
    start = v1._epoch_ns(START)
    for side in ("buy", "sell"):
        shadow._append_decision(
            journal,
            decision_ns=start,
            side=side,
            recorded_at_ns=start + 3_000_000_000,
            status="PREDICTED",
            reason=None,
            features=numpy.zeros(len(v2.FEATURE_NAMES)),
            fill_probability=0.5,
            predicted_fallback=0.0,
            expected_saving=1.0,
            selected=True,
        )
    journal.commit()
    monkeypatch.setattr(v2, "_load_window", lambda source, decision: object())

    def outcome(window, side, policy):
        stress = policy is v1.STRESS_POLICY
        return {
            "completed": True,
            "filled": stress,
            "saving_bps": 3.0 if stress else 1.0,
            "exclusion": None,
        }

    monkeypatch.setattr(v2, "_unconditional_outcome", outcome)
    assert shadow._process_outcomes(
        object(), journal, now_ns=start + 124_000_000_000
    ) == {"completed": 0, "incomplete": 0}
    result = shadow._process_outcomes(
        object(), journal, now_ns=start + 125_000_000_000
    )
    assert result == {"completed": 2, "incomplete": 0}
    values = [
        row[0]
        for row in journal.execute(
            "SELECT fee_neutral_stress_saving_bps FROM outcomes"
        )
    ]
    assert values == [1.0, 1.0]
    journal.close()


def _side(attempts=150, saving=0.5):
    return {
        "selected_attempts": attempts,
        "mean_selected_saving_bps": saving,
    }


def test_forward_gate_is_conjunctive_and_separate_by_side():
    report = {
        "source": {
            "prediction_coverage": 0.99,
            "outcome_coverage": 0.99,
            "valid_predictions": 1_500,
            "selected_pct": 30.0,
        },
        "fill_calibration": {"auc": 0.7, "brier": 0.1, "constant_brier": 0.2},
        "primary": {
            "selected_attempts": 400,
            "selected_fill_rate": 0.4,
            "mean_selected_saving_bps": 0.5,
            "positive_operating_days_pct": 60.0,
            "daily_bootstrap_lower_policy_saving_bps_90pct": 0.1,
            "by_side": {"buy": _side(200), "sell": _side(200)},
        },
        "fee_neutral_stress": {
            "mean_selected_saving_bps": 0.2,
            "by_side": {"buy": _side(200, 0.2), "sell": _side(200, 0.1)},
        },
    }
    gate = shadow._forward_gate(report, shadow.frozen_protocol(START))
    assert gate["passed"] is True
    report["fee_neutral_stress"]["by_side"]["sell"][
        "mean_selected_saving_bps"
    ] = -0.01
    gate = shadow._forward_gate(report, shadow.frozen_protocol(START))
    assert gate["passed"] is False
    assert gate["checks"][
        "fee_neutral_stress_each_side_strictly_positive"
    ] is False


def test_collector_health_is_checked_against_wall_clock(tmp_path):
    now = datetime.datetime(2026, 8, 28, 10, 0, tzinfo=datetime.timezone.utc)
    path = tmp_path / "health.json"
    path.write_text(
        json.dumps(
            {
                "status": "healthy",
                "connected": True,
                "database_operational": True,
                "public_data_only": True,
                "credentials_used": False,
                "orders_authorized": False,
                "symbol": "XBTUSDTM",
                "last_success_at": (now - datetime.timedelta(seconds=5)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    _, healthy = shadow._read_collector_health(
        path, int(now.timestamp() * 1_000_000_000)
    )
    assert healthy is True
    _, stale = shadow._read_collector_health(
        path, int((now + datetime.timedelta(seconds=20)).timestamp() * 1_000_000_000)
    )
    assert stale is False
