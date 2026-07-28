import dataclasses
import json
import math
import sqlite3

from octobot.ai_strategy_lab import scalping_crash_case_study as study


def _database(path):
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE book_events (
            id INTEGER PRIMARY KEY
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE trade_events (
            id INTEGER PRIMARY KEY
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE second_buckets (
            bucket_ts_s INTEGER PRIMARY KEY,
            book_event_count INTEGER NOT NULL,
            trade_event_count INTEGER NOT NULL,
            first_mid REAL,
            high_mid REAL,
            low_mid REAL,
            last_mid REAL,
            spread_bps_sum REAL NOT NULL,
            imbalance_5_sum REAL NOT NULL,
            buy_trade_size REAL NOT NULL,
            sell_trade_size REAL NOT NULL,
            buy_trade_count INTEGER NOT NULL,
            sell_trade_count INTEGER NOT NULL
        )
        """
    )
    connection.execute("INSERT INTO book_events VALUES (1)")
    connection.execute("INSERT INTO trade_events VALUES (1)")
    start = 1_780_000_000
    start -= start % study.BUCKET_SECONDS
    for second in range(study.BUCKET_SECONDS * 2):
        timestamp = start + second
        bucket_index = second // study.BUCKET_SECONDS
        mid = 100 + bucket_index + second / 100_000
        connection.execute(
            """
            INSERT INTO second_buckets VALUES (
                ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1
            )
            """,
            (
                timestamp,
                mid,
                mid,
                mid,
                mid,
                0.02,
                -0.2,
                1.0,
                3.0,
            ),
        )
    connection.commit()
    connection.close()


def test_protocol_is_result_free_and_cannot_trade(tmp_path):
    protocol = study.frozen_protocol()

    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["implementation"]["results_in_this_protocol"] is False
    assert protocol["post_event_candidate_hypothesis"]["not_a_short_entry"]

    path = study.write_protocol(tmp_path)
    assert json.loads(path.read_text())["protocol_sha256"]


def test_load_buckets_uses_complete_causal_intervals(tmp_path):
    database = tmp_path / "observer.sqlite"
    _database(database)

    buckets, source = study.load_complete_buckets(database)

    assert len(buckets) == 2
    assert source["snapshot_max_book_id"] == 1
    assert buckets[0].trade_flow_imbalance == -0.5
    assert math.isnan(buckets[0].trade_flow_imbalance_2)
    assert buckets[1].trade_flow_imbalance_2 == -0.5
    assert math.isclose(buckets[1].book_imbalance_2, -0.2)
    assert buckets[0].future_returns_pct[1] > 0


def test_average_ranks_and_spearman_handle_ties():
    ranks = study._average_ranks([1.0, 1.0, 3.0, 4.0])

    assert ranks == [0.5, 0.5, 2.0, 3.0]
    assert study._spearman([1, 2, 3], [3, 2, 1]) == -1


def test_fast_drop_recall_requires_an_earlier_available_trigger():
    first = study.Bucket(
        timestamp=study.EVENT_ONSET_TS - 900,
        observed_seconds=900,
        book_events=1,
        trade_events=1,
        open_price=100,
        close_price=99,
        mean_spread_bps=0.1,
        mean_book_imbalance=-0.2,
        buy_trade_size=1,
        sell_trade_size=2,
        buy_trade_count=1,
        sell_trade_count=1,
        return_pct=-1,
    )
    second = dataclasses.replace(
        first,
        timestamp=study.EVENT_ONSET_TS,
    )
    result = study._descriptive_fast_drop_recall(
        [first, second],
        [
            {
                "available_at": study._iso(
                    study.EVENT_ONSET_TS - 1_800
                )
            }
        ],
    )

    assert result["fast_down_buckets_through_known_onset"] == 2
    assert result["preceded_by_candidate_within_two_hours"] == 2
    assert result["descriptive_recall_pct"] == 100


def test_evaluate_requires_the_frozen_protocol(tmp_path):
    database = tmp_path / "observer.sqlite"
    _database(database)

    try:
        study.evaluate(database, tmp_path / "result")
    except FileNotFoundError as error:
        assert "protocol.json" in str(error)
    else:
        raise AssertionError("evaluation unexpectedly skipped preregistration")
