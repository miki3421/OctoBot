import json

from octobot.ai_strategy_lab import scalping_strategy_search


def test_result_free_protocol_is_atomic_and_reproducible(tmp_path):
    path = tmp_path / "protocol.json"

    first = scalping_strategy_search.write_or_verify_protocol(path)
    second = scalping_strategy_search.write_or_verify_protocol(path)

    assert first == second
    assert first["results"] is None
    assert first["orders_authorized"] is False
    assert first["paper_orders_authorized"] is False
    assert first["automatic_promotion"] is False
    assert first["frozen_source"]["snapshot_sha256"] == (
        scalping_strategy_search.SNAPSHOT_SHA256
    )
    assert len(first["protocol_sha256"]) == 64
    assert json.loads(path.read_text()) == first


def test_locked_test_cannot_be_used_for_model_selection():
    protocol = scalping_strategy_search.frozen_protocol()

    assert protocol["temporal_validation"]["locked_test_policy"].startswith(
        "do not compute labels"
    )
    assert protocol["models"]["candidates"] == [
        {
            "name": "numpy_logistic",
            "config": {
                "epochs": 12,
                "batch_size": 8192,
                "learning_rate": 0.01,
                "l2": 0.003,
                "seed": 20260827,
            },
        },
        {
            "name": "numpy_gradient_boosting",
            "config": {
                "trees": 32,
                "max_depth": 2,
                "bins": 24,
                "learning_rate": 0.05,
                "l2": 3.0,
                "minimum_leaf_rows": 500,
                "minimum_gain": 0.001,
                "feature_fraction": 0.75,
                "seed": 20260827,
            },
        },
    ]
