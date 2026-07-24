import datetime
import json

import numpy
import pytest

from octobot.ai_strategy_lab import forward_carry_dataset
from octobot.ai_strategy_lab import forward_evidence
from octobot.ai_strategy_lab import microstructure


START = datetime.datetime(
    2026, 7, 23, 0, 0, tzinfo=datetime.timezone.utc
)


def _curve(vwap):
    return {
        "target_quote": 1000.0,
        "filled_quote": 1000.0,
        "filled_base": 1000.0 / vwap,
        "vwap": vwap,
        "last_price": vwap,
        "sufficient_depth": True,
    }


def _levels(price):
    return [
        {
            "price": price,
            "base_quantity": 100_000,
            "quote_quantity": price * 100_000,
        }
    ]


def _symbol(
    *,
    spot_bid,
    spot_ask,
    futures_bid,
    futures_ask,
    settled,
):
    return {
        "spot": {
            "best_bid": spot_bid,
            "best_ask": spot_ask,
            "spread_bps": (spot_ask / spot_bid - 1) * 10_000,
            "bid_vwap_by_quote": {"1000": _curve(spot_bid)},
            "ask_vwap_by_quote": {"1000": _curve(spot_ask)},
            "normalized_bids": _levels(spot_bid),
            "normalized_asks": _levels(spot_ask),
            "conservative_taker_fee_rate": 0.001,
        },
        "futures": {
            "best_bid": futures_bid,
            "best_ask": futures_ask,
            "spread_bps": (
                futures_ask / futures_bid - 1
            )
            * 10_000,
            "bid_vwap_by_quote": {"1000": _curve(futures_bid)},
            "ask_vwap_by_quote": {"1000": _curve(futures_ask)},
            "normalized_bids": _levels(futures_bid),
            "normalized_asks": _levels(futures_ask),
            "conservative_taker_fee_rate": 0.0006,
            "open_interest_quote": 2_000_000,
            "mark_index_basis_bps": 2.0,
        },
        "carry_execution": {
            "entry_basis_bps": (
                futures_bid / spot_ask - 1
            )
            * 10_000,
            "round_trip_book_width_bps": 3.0,
            "entry_capacity_usdt_depth20": 10_000,
            "exit_capacity_usdt_depth20": 9_000,
        },
        "funding": {
            "current_rate": 0.0001,
            "predicted_rate": None,
            "granularity_ms": 28_800_000,
            "settled_last_24h": settled,
        },
    }


def _record(bucket, *, previous_hash, symbol):
    value = {
        "schema_version": microstructure.SCHEMA_VERSION,
        "mode": "observation_only",
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "bucket_start_utc": bucket.isoformat(),
        "interval_minutes": 15,
        "previous_record_hash": previous_hash,
        "symbols": {"BTC": symbol},
    }
    value["record_hash"] = microstructure._record_hash(value)
    return value


def _artifacts(tmp_path, *, ready):
    settlement_ms = int(
        (START + datetime.timedelta(hours=4)).timestamp() * 1000
    )
    first = _record(
        START,
        previous_hash=None,
        symbol=_symbol(
            spot_bid=99,
            spot_ask=100,
            futures_bid=101,
            futures_ask=102,
            settled=[],
        ),
    )
    second = _record(
        START + datetime.timedelta(hours=8),
        previous_hash=first["record_hash"],
        symbol=_symbol(
            spot_bid=103,
            spot_ask=104,
            futures_bid=99,
            futures_ask=100,
            settled=[
                {"timestamp_ms": settlement_ms, "rate": 0.0002}
            ],
        ),
    )
    journal = tmp_path / "market.jsonl"
    journal.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )
    config = (
        forward_evidence.ForwardEvidenceConfig(
            minimum_span_days=0.34,
            minimum_coverage=0.05,
            maximum_gap_minutes=480,
            minimum_settlements_per_symbol=1,
            expected_symbol_count=1,
        )
        if ready
        else forward_evidence.ForwardEvidenceConfig()
    )
    evidence = forward_evidence.evaluate_forward_market_evidence(
        journal, config=config
    )
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    return journal, evidence_path, config


def test_builds_execution_and_funding_aware_forward_label(tmp_path):
    journal, evidence, config = _artifacts(tmp_path, ready=True)

    dataset = forward_carry_dataset.build_forward_carry_dataset(
        journal,
        evidence,
        horizon_hours=(8,),
        evidence_config=config,
    )

    assert dataset["row_count"] == 1
    row = dataset["rows"][0]
    expected_spot = 103 / 100 - 1
    expected_futures = 1 - 100 / 101
    spot_exit_quote = 10 * 103
    futures_exit_quote = (1000 / 101) * 100
    expected_fee = (
        1000 * 0.001
        + spot_exit_quote * 0.001
        + 1000 * 0.0006
        + futures_exit_quote * 0.0006
    ) / 2000
    expected_net = (
        0.5 * (expected_spot + expected_futures + 0.0002)
        - expected_fee
    )
    assert row["label"]["spot_price_return"] == pytest.approx(
        expected_spot
    )
    assert row["label"]["futures_price_return"] == pytest.approx(
        expected_futures
    )
    assert row["label"]["settled_funding_return"] == 0.0002
    assert row["label"]["conservative_fee_return"] == expected_fee
    assert row["label"]["net_pair_return"] == pytest.approx(expected_net)
    assert len(row["features"]) == len(
        forward_carry_dataset.FEATURE_NAMES
    )

    manifest = forward_carry_dataset.save_forward_carry_dataset(
        dataset, tmp_path / "carry.npz"
    )
    saved = numpy.load(tmp_path / "carry.npz")
    assert saved["features"].shape == (
        1,
        len(forward_carry_dataset.FEATURE_NAMES),
    )
    assert saved["net_pair_return"][0] == pytest.approx(expected_net)
    assert manifest["output"]["sha256"]
    loaded = forward_carry_dataset.load_forward_carry_dataset(
        tmp_path / "carry.npz"
    )
    assert loaded["features"].shape == saved["features"].shape
    assert loaded["net_pair_return"][0] == pytest.approx(expected_net)
    assert loaded["manifest"]["row_count"] == 1


def test_refuses_dataset_before_default_readiness_gate(tmp_path):
    journal, evidence, config = _artifacts(tmp_path, ready=False)
    assert config == forward_evidence.ForwardEvidenceConfig()

    with pytest.raises(
        ValueError, match="strategy development is not ready"
    ):
        forward_carry_dataset.build_forward_carry_dataset(
            journal, evidence, horizon_hours=(8,)
        )


def test_refuses_stale_evidence_hash(tmp_path):
    journal, evidence, config = _artifacts(tmp_path, ready=True)
    with journal.open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(ValueError, match="journal hash mismatch"):
        forward_carry_dataset.build_forward_carry_dataset(
            journal,
            evidence,
            horizon_hours=(8,),
            evidence_config=config,
        )


def test_loader_rejects_tampered_dataset(tmp_path):
    journal, evidence, config = _artifacts(tmp_path, ready=True)
    dataset = forward_carry_dataset.build_forward_carry_dataset(
        journal,
        evidence,
        horizon_hours=(8,),
        evidence_config=config,
    )
    forward_carry_dataset.save_forward_carry_dataset(
        dataset, tmp_path / "carry.npz"
    )
    with (tmp_path / "carry.npz").open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(ValueError, match="dataset hash mismatch"):
        forward_carry_dataset.load_forward_carry_dataset(
            tmp_path / "carry.npz"
        )


def test_loader_recomputes_label_accounting_identity(tmp_path):
    journal, evidence, config = _artifacts(tmp_path, ready=True)
    dataset = forward_carry_dataset.build_forward_carry_dataset(
        journal,
        evidence,
        horizon_hours=(8,),
        evidence_config=config,
    )
    path = tmp_path / "carry.npz"
    forward_carry_dataset.save_forward_carry_dataset(dataset, path)
    with numpy.load(path, allow_pickle=False) as saved:
        values = {name: saved[name].copy() for name in saved.files}
    values["net_pair_return"][0] += 0.01
    numpy.savez_compressed(path, **values)
    manifest_path = path.with_suffix(".npz.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output"]["sha256"] = forward_carry_dataset._sha256(path)
    manifest["output"]["bytes"] = path.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="accounting identity failed"):
        forward_carry_dataset.load_forward_carry_dataset(path)
