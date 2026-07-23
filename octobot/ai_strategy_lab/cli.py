"""Command-line interface for the offline AI strategy laboratory."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import sys
import time
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import experts as experts_module
from octobot.ai_strategy_lab import market_data as market_data_module
from octobot.ai_strategy_lab import model as model_module


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="octobot-ai-lab",
        description=(
            "Offline research only: build point-in-time datasets and run "
            "purged walk-forward AI experiments. This command cannot place orders."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dataset_parser = subparsers.add_parser(
        "build-dataset", help="Build a versioned triple-barrier dataset."
    )
    dataset_parser.add_argument(
        "--input", action="append", required=True, help="OctoBot collector .data file."
    )
    dataset_parser.add_argument("--output", required=True, help="Output .npz path.")
    dataset_parser.add_argument("--candidate-stride", type=int, default=1)
    dataset_parser.add_argument("--atr-multiplier", type=float, default=1.5)
    dataset_parser.add_argument("--reward-risk", type=float, default=2.0)
    dataset_parser.add_argument("--min-stop-pct", type=float, default=0.005)
    dataset_parser.add_argument("--max-stop-pct", type=float, default=0.02)
    dataset_parser.add_argument("--horizon-bars", type=int, default=16)
    dataset_parser.add_argument("--fee-rate", type=float, default=0.0006)
    dataset_parser.add_argument("--slippage-rate", type=float, default=0.0002)
    dataset_parser.add_argument("--funding-rate-8h", type=float, default=0.0)
    dataset_parser.add_argument(
        "--funding-json",
        help="Versioned signed KuCoin funding history produced by fetch-funding.",
    )

    funding_parser = subparsers.add_parser(
        "fetch-funding",
        help="Download public KuCoin funding settlements for reproducible research.",
    )
    funding_parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Mapping in OCTOBOT_SYMBOL=KUCOIN_SYMBOL form.",
    )
    funding_parser.add_argument("--from-date", required=True, help="UTC YYYY-MM-DD.")
    funding_parser.add_argument("--to-date", required=True, help="UTC YYYY-MM-DD inclusive.")
    funding_parser.add_argument("--output", required=True)

    archive_parser = subparsers.add_parser(
        "fetch-binance-archive",
        help=(
            "Build a research-only OctoBot collector from checksummed public "
            "Binance USD-M archives."
        ),
    )
    archive_parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Mapping in OCTOBOT_SYMBOL=BINANCE_SYMBOL form.",
    )
    archive_parser.add_argument("--from-date", required=True, help="UTC YYYY-MM-DD.")
    archive_parser.add_argument("--to-date", required=True, help="UTC YYYY-MM-DD inclusive.")
    archive_parser.add_argument("--output", required=True)
    archive_parser.add_argument("--funding-output")
    archive_parser.add_argument("--cache")

    experiment_parser = subparsers.add_parser(
        "run-experiment",
        help="Train and evaluate the NumPy logistic baseline.",
    )
    experiment_parser.add_argument("--dataset", required=True)
    experiment_parser.add_argument("--output-root", required=True)
    experiment_parser.add_argument("--seed", type=int, default=42)
    experiment_parser.add_argument(
        "--model",
        choices=("logistic", "gradient_boosting"),
        default="logistic",
    )
    experiment_parser.add_argument("--epochs", type=int, default=12)
    experiment_parser.add_argument("--batch-size", type=int, default=8192)
    experiment_parser.add_argument("--learning-rate", type=float, default=0.01)
    experiment_parser.add_argument("--l2", type=float, default=0.001)
    experiment_parser.add_argument("--boosting-trees", type=int, default=32)
    experiment_parser.add_argument("--boosting-depth", type=int, default=2)
    experiment_parser.add_argument("--boosting-bins", type=int, default=16)
    experiment_parser.add_argument("--boosting-learning-rate", type=float, default=0.06)
    experiment_parser.add_argument("--folds", type=int, default=4)
    experiment_parser.add_argument("--minimum-validation-trades", type=int, default=20)
    experiment_parser.add_argument("--position-fraction", type=float, default=0.10)
    experiment_parser.add_argument(
        "--prediction-target",
        choices=("target", "profitable"),
        default="target",
        help="Classify target hits or net-profitable outcomes.",
    )
    experiment_parser.add_argument(
        "--locked-block-status",
        choices=("pristine", "diagnostic_reuse"),
        default="diagnostic_reuse",
        help="Declare whether the final chronological block has ever been inspected.",
    )
    experiment_parser.add_argument(
        "--training-stride",
        type=int,
        default=4,
        help="Train on one of every N 15m timestamps; all test timestamps remain evaluated.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect-dataset", help="Validate and summarize a saved research dataset."
    )
    inspect_parser.add_argument("--dataset", required=True)

    experts_parser = subparsers.add_parser(
        "evaluate-experts",
        help="Evaluate frozen deterministic regime experts without fitting.",
    )
    experts_parser.add_argument("--dataset", required=True)
    experts_parser.add_argument("--output", required=True)
    experts_parser.add_argument("--position-fraction", type=float, default=0.10)
    experts_parser.add_argument("--folds", type=int, default=6)
    return parser


def main(arguments: typing.Optional[list[str]] = None) -> int:
    args = create_parser().parse_args(arguments)
    if args.command == "build-dataset":
        return _build_dataset(args)
    if args.command == "run-experiment":
        return _run_experiment(args)
    if args.command == "fetch-funding":
        return _fetch_funding(args)
    if args.command == "fetch-binance-archive":
        return _fetch_binance_archive(args)
    if args.command == "inspect-dataset":
        return _inspect_dataset(args)
    if args.command == "evaluate-experts":
        return _evaluate_experts(args)
    raise ValueError(f"unknown command: {args.command}")


def _build_dataset(args: argparse.Namespace) -> int:
    barriers = dataset_module.BarrierConfig(
        atr_multiplier=args.atr_multiplier,
        reward_risk_ratio=args.reward_risk,
        minimum_stop_pct=args.min_stop_pct,
        maximum_stop_pct=args.max_stop_pct,
        horizon_bars=args.horizon_bars,
        fee_rate_per_fill=args.fee_rate,
        slippage_rate_per_fill=args.slippage_rate,
        funding_rate_per_8h=args.funding_rate_8h,
    )
    config = dataset_module.DatasetBuildConfig(
        barriers=barriers,
        candidate_stride=args.candidate_stride,
    )
    started = time.monotonic()
    funding_rates = (
        funding_module.load_funding(args.funding_json)
        if args.funding_json
        else None
    )
    dataset = dataset_module.build_dataset(
        args.input,
        config,
        funding_rates=funding_rates,
    )
    manifest = dataset_module.save_dataset(
        dataset,
        args.output,
        collector_paths=args.input,
        config=config,
        funding_path=args.funding_json,
    )
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(_json_safe(manifest), indent=2, sort_keys=True))
    return 0


def _fetch_funding(args: argparse.Namespace) -> int:
    mapping = {}
    for value in args.symbol:
        if "=" not in value:
            raise ValueError(f"invalid symbol mapping: {value}")
        octobot_symbol, kucoin_symbol = value.rsplit("=", 1)
        if not octobot_symbol or not kucoin_symbol:
            raise ValueError(f"invalid symbol mapping: {value}")
        mapping[octobot_symbol] = kucoin_symbol
    payload = funding_module.fetch_kucoin_funding(
        mapping,
        funding_module.parse_utc_date(args.from_date),
        funding_module.parse_utc_date(args.to_date, end_of_day=True),
    )
    artifact = funding_module.save_funding(payload, args.output)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0


def _parse_symbol_mapping(values: list[str]) -> dict[str, str]:
    mapping = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid symbol mapping: {value}")
        octobot_symbol, remote_symbol = value.rsplit("=", 1)
        if not octobot_symbol or not remote_symbol:
            raise ValueError(f"invalid symbol mapping: {value}")
        mapping[octobot_symbol] = remote_symbol
    return mapping


def _fetch_binance_archive(args: argparse.Namespace) -> int:
    result = market_data_module.fetch_binance_archive(
        market_data_module.BinanceArchiveConfig(
            symbol_mapping=_parse_symbol_mapping(args.symbol),
            start_date=market_data_module.parse_date(args.from_date),
            end_date=market_data_module.parse_date(args.to_date),
        ),
        args.output,
        funding_output_value=args.funding_output,
        cache_value=args.cache,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _evaluate_experts(args: argparse.Namespace) -> int:
    dataset_path = pathlib.Path(args.dataset).resolve()
    dataset = dataset_module.load_dataset(dataset_path)
    report = experts_module.evaluate_experts(
        dataset,
        position_fraction=args.position_fraction,
        folds=args.folds,
    )
    report["dataset"] = {
        "path": str(dataset_path),
        "sha256": _sha256(dataset_path),
    }
    report["created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "path": str(output),
        "experts": {
            name: {
                "trades": value["trades"],
                "total_return": value["total_return"],
                "profit_factor": value["profit_factor"],
                "positive_month_ratio": value["calendar"]["positive_month_ratio"],
            }
            for name, value in report["experts"].items()
        },
        "combined_union": {
            "trades": report["combined_union"]["trades"],
            "total_return": report["combined_union"]["total_return"],
            "profit_factor": report["combined_union"]["profit_factor"],
            "positive_month_ratio": report["combined_union"]["calendar"]["positive_month_ratio"],
        },
    }, indent=2, sort_keys=True))
    return 0


def _run_experiment(args: argparse.Namespace) -> int:
    dataset_path = pathlib.Path(args.dataset).resolve()
    dataset = dataset_module.load_dataset(dataset_path)
    logistic_config = model_module.LogisticConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        l2=args.l2,
        seed=args.seed,
    )
    validation_config = model_module.ValidationConfig(
        folds=args.folds,
        minimum_validation_trades=args.minimum_validation_trades,
        position_fraction=args.position_fraction,
        training_stride=args.training_stride,
    )
    boosting_config = model_module.BoostingConfig(
        trees=args.boosting_trees,
        max_depth=args.boosting_depth,
        bins=args.boosting_bins,
        learning_rate=args.boosting_learning_rate,
        seed=args.seed,
    )
    started = time.monotonic()
    result = model_module.run_experiment(
        dataset,
        logistic_config=logistic_config,
        boosting_config=boosting_config,
        validation_config=validation_config,
        prediction_target=args.prediction_target,
        model_type=args.model,
        locked_block_status=args.locked_block_status,
    )
    duration_seconds = time.monotonic() - started
    artifacts = _save_experiment(
        dataset_path,
        dataset,
        result,
        pathlib.Path(args.output_root).resolve(),
        duration_seconds=duration_seconds,
    )
    summary = {
        "experiment_id": artifacts["experiment_id"],
        "experiment_dir": artifacts["experiment_dir"],
        "duration_seconds": round(duration_seconds, 3),
        "walk_forward": result["walk_forward_aggregate"],
        "locked_test": result["locked_test"],
        "leave_one_asset_out": result["leave_one_asset_out"],
    }
    print(json.dumps(_json_safe(summary), indent=2, sort_keys=True))
    return 0


def _inspect_dataset(args: argparse.Namespace) -> int:
    dataset = dataset_module.load_dataset(args.dataset)
    summary = {
        "rows": len(dataset.label),
        "feature_count": len(dataset.feature_names),
        "symbols": sorted(str(value) for value in numpy.unique(dataset.symbol)),
        "start_timestamp": int(numpy.min(dataset.timestamp)),
        "end_timestamp": int(numpy.max(dataset.timestamp)),
        "target_rate": float(numpy.mean(dataset.label)),
        "profitable_rate": float(numpy.mean(dataset.profitable)),
        "outcomes": {
            "target": int(numpy.sum(dataset.outcome == dataset_module.OUTCOME_TARGET)),
            "stop": int(numpy.sum(dataset.outcome == dataset_module.OUTCOME_STOP)),
            "timeout": int(numpy.sum(dataset.outcome == dataset_module.OUTCOME_TIMEOUT)),
        },
        "average_duration_bars": float(numpy.mean(dataset.duration_bars)),
        "feature_names": list(dataset.feature_names),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _save_experiment(
    dataset_path: pathlib.Path,
    dataset: dataset_module.ResearchDataset,
    result: dict,
    output_root: pathlib.Path,
    *,
    duration_seconds: float,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_hash = _sha256(dataset_path)
    public_report = model_module.clean_report(result)
    identity_payload = json.dumps(
        {
            "dataset_sha256": dataset_hash,
            "prediction_target": public_report["prediction_target"],
            "model": public_report["model"],
            "locked_block_status": public_report["locked_block_status"],
            "logistic_config": public_report["logistic_config"],
            "boosting_config": public_report["boosting_config"],
            "validation_config": public_report["validation_config"],
        },
        sort_keys=True,
    ).encode("utf-8")
    short_hash = hashlib.sha256(identity_payload).hexdigest()[:12]
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    experiment_id = f"{timestamp}_{short_hash}"
    experiment_dir = output_root / experiment_id
    experiment_dir.mkdir()

    model_path = experiment_dir / "locked_model.npz"
    model_artifact = result["_locked_model"].save(model_path)
    if public_report["model"] == "numpy_gradient_boosting":
        loaded_model = model_module.NumpyGradientBoostingModel.load(model_path)
    else:
        loaded_model = model_module.NumpyLogisticModel.load(model_path)
    selected_indices = result["_locked_selected_indices"]
    reloaded_probabilities = loaded_model.predict_proba(
        dataset.features[selected_indices]
    )
    expected_probabilities = result["_locked_probabilities"]
    if not numpy.allclose(
        reloaded_probabilities,
        expected_probabilities,
        atol=1e-12,
        rtol=1e-10,
    ):
        raise RuntimeError("saved model does not reproduce locked-test probabilities")

    predictions_path = experiment_dir / "locked_predictions.npz"
    numpy.savez_compressed(
        predictions_path,
        indices=selected_indices,
        probabilities=expected_probabilities,
        timestamp=dataset.timestamp[selected_indices],
        exit_timestamp=dataset.exit_timestamp[selected_indices],
        symbol=dataset.symbol[selected_indices],
        direction=dataset.direction[selected_indices],
        net_return=dataset.net_return[selected_indices],
    )
    report_path = experiment_dir / "report.json"
    report_payload = _json_safe(
        {
            **public_report,
            "duration_seconds": round(duration_seconds, 3),
        }
    )
    report_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "research_only": True,
        "can_place_orders": False,
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_hash,
            "rows": len(dataset.label),
            "feature_schema_sha256": hashlib.sha256(
                "\n".join(dataset.feature_names).encode("utf-8")
            ).hexdigest(),
        },
        "model": model_artifact,
        "predictions": {
            "path": str(predictions_path),
            "sha256": _sha256(predictions_path),
            "rows": int(len(selected_indices)),
        },
        "report": {
            "path": str(report_path),
            "sha256": _sha256(report_path),
        },
        "code": {
            "dataset_schema_version": dataset_module.SCHEMA_VERSION,
            "model_schema_version": model_module.MODEL_SCHEMA_VERSION,
        },
    }
    manifest_path = experiment_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    registry_entry = {
        "experiment_id": experiment_id,
        "created_at": manifest["created_at"],
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "dataset_sha256": dataset_hash,
        "locked_test": report_payload["locked_test"],
        "walk_forward_aggregate": report_payload["walk_forward_aggregate"],
    }
    with (output_root / "experiments.jsonl").open("a", encoding="utf-8") as registry:
        registry.write(json.dumps(registry_entry, sort_keys=True) + "\n")
    return {
        "experiment_id": experiment_id,
        "experiment_dir": str(experiment_dir),
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(element) for key, element in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(element) for element in value]
    if isinstance(value, numpy.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
