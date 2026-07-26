import json

from octobot.ai_strategy_lab import perfect_map_student_v6 as v6


def test_v6_protocol_is_result_free_and_excludes_v5_forward_data():
    protocol = v6.frozen_protocol()
    encoded = json.dumps(protocol, sort_keys=True)

    assert protocol["status"] == "preregistered_design_only"
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["parent"]["immutable"] is True
    assert "/v5-paper/binance/v5-paper.sqlite" in (
        protocol["data_policy"][
            "forbidden_for_fit_calibration_and_selection"
        ]
    )
    assert protocol["decision"]["raw_expected_net_floor_pct"] == 0.075
    assert (
        "sqrt(horizon_hours)"
        in protocol["decision"]["time_normalized_score"]
    )
    assert protocol["implementation_policy"]["results_in_this_protocol"] is False
    assert '"profit_factor": 1.1' in encoded
    assert "win_rate_pct" not in encoded


def test_written_protocol_has_matching_hash(tmp_path):
    path = v6.write_protocol(tmp_path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    expected = v6.frozen_protocol()

    assert persisted["protocol_sha256"] == v6.protocol_sha256(expected)
    assert path.name == "protocol.json"
