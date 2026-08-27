from octobot.ai_strategy_lab import scalping_strategy_search_v2


def test_v2_protocol_is_result_free_and_keeps_locked_test_sealed(tmp_path):
    path = tmp_path / "protocol.json"

    protocol = scalping_strategy_search_v2.write_or_verify_protocol(path)

    assert protocol["results"] is None
    assert protocol["orders_authorized"] is False
    assert protocol["paper_orders_authorized"] is False
    assert protocol["automatic_promotion"] is False
    assert protocol["frozen_source"][
        "locked_test_not_materialized_at_preregistration"
    ] is True
    assert protocol["candidate_family"]["configurations"] == [
        {
            "name": "balanced_5m",
            "target_bps": 40,
            "stop_bps": 20,
            "horizon_seconds": 300,
        },
        {
            "name": "wide_15m",
            "target_bps": 60,
            "stop_bps": 30,
            "horizon_seconds": 900,
        },
    ]


def test_v2_declares_diagnostic_reuse_of_the_middle_block():
    protocol = scalping_strategy_search_v2.frozen_protocol()

    assert protocol["validation"][
        "diagnostic_confirmation_is_not_pristine"
    ] is True
    assert protocol["models"]["selection_candidates"] == 16
