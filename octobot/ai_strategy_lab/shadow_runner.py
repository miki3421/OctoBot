"""Autonomous public-data runner for the no-order trend shadow."""

from __future__ import annotations

import dataclasses
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import tempfile
import typing

import numpy

from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import market_data as market_data_module
from octobot.ai_strategy_lab import shadow as shadow_module
from octobot.ai_strategy_lab import trend as trend_module


RUNNER_SCHEMA_VERSION = 1
DEFAULT_STRATEGY = (
    "bear_regime_short_filter_dual_momentum_30_120_weekly_v3"
    "_cost_stress_3x"
)
KUCOIN_FUTURES_SYMBOLS = {
    "AAVE/USDT:USDT": "AAVEUSDTM",
    "ADA/USDT:USDT": "ADAUSDTM",
    "ATOM/USDT:USDT": "ATOMUSDTM",
    "AVAX/USDT:USDT": "AVAXUSDTM",
    "BCH/USDT:USDT": "BCHUSDTM",
    "BTC/USDT:USDT": "XBTUSDTM",
    "DOGE/USDT:USDT": "DOGEUSDTM",
    "DOT/USDT:USDT": "DOTUSDTM",
    "ETH/USDT:USDT": "ETHUSDTM",
    "HBAR/USDT:USDT": "HBARUSDTM",
    "LINK/USDT:USDT": "LINKUSDTM",
    "LTC/USDT:USDT": "LTCUSDTM",
    "NEAR/USDT:USDT": "NEARUSDTM",
    "PEPE/USDT:USDT": "PEPEUSDTM",
    "SOL/USDT:USDT": "SOLUSDTM",
    "UNI/USDT:USDT": "UNIUSDTM",
    "XLM/USDT:USDT": "XLMUSDTM",
    "XRP/USDT:USDT": "XRPUSDTM",
    "ZEC/USDT:USDT": "ZECUSDTM",
}


@dataclasses.dataclass(frozen=True)
class ShadowRunnerConfig:
    output_root: pathlib.Path
    journal_path: pathlib.Path
    health_path: pathlib.Path
    lock_path: pathlib.Path
    history_days: int = 264
    initial_capital: float = 10_000.0
    cost_stress_multiplier: float = 3.0
    strategy_name: str = DEFAULT_STRATEGY
    rebalance_weekday_utc: int = 6

    def validate(self) -> None:
        if self.history_days < 250:
            raise ValueError("shadow history must contain at least 250 days")
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if self.cost_stress_multiplier < 1:
            raise ValueError("cost stress multiplier must be at least one")
        if not self.strategy_name:
            raise ValueError("strategy name is required")
        if not 0 <= self.rebalance_weekday_utc <= 6:
            raise ValueError("rebalance weekday must be in [0, 6]")


def run_shadow_once(
    config: ShadowRunnerConfig,
    *,
    as_of_date: typing.Optional[datetime.date] = None,
) -> dict:
    """Run one atomic public-data shadow cycle or fail without journaling."""
    config.validate()
    today_utc = datetime.datetime.now(datetime.timezone.utc).date()
    as_of = as_of_date or (today_utc - datetime.timedelta(days=1))
    if as_of >= today_utc:
        raise ValueError("shadow as-of date must be a fully closed UTC day")
    start_date = as_of - datetime.timedelta(days=config.history_days - 1)

    config.output_root.mkdir(parents=True, exist_ok=True)
    config.journal_path.parent.mkdir(parents=True, exist_ok=True)
    config.health_path.parent.mkdir(parents=True, exist_ok=True)
    config.lock_path.parent.mkdir(parents=True, exist_ok=True)
    attempt_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with config.lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(
                lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise RuntimeError("trend shadow runner is already active") from error
        try:
            return _run_locked(
                config,
                start_date=start_date,
                as_of=as_of,
                attempt_at=attempt_at,
            )
        except Exception as error:
            previous = _read_health(config.health_path)
            _write_json_atomic(
                config.health_path,
                {
                    "schema_version": RUNNER_SCHEMA_VERSION,
                    "mode": "shadow_only",
                    "orders_authorized": False,
                    "status": "failed",
                    "last_attempt_at": attempt_at,
                    "last_success_at": previous.get("last_success_at"),
                    "as_of_date": as_of.isoformat(),
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            raise


def run_shadow_catchup(
    config: ShadowRunnerConfig,
    *,
    max_catchup_days: int,
    today_utc: typing.Optional[datetime.date] = None,
) -> dict:
    target_date = (
        today_utc or datetime.datetime.now(datetime.timezone.utc).date()
    ) - datetime.timedelta(days=1)
    existing_dates = {
        value["market_end_date"]
        for value in shadow_module.load_shadow_records(config.journal_path)
    }
    try:
        dates = missing_shadow_dates(
            config.journal_path,
            strategy_name=config.strategy_name,
            target_date=target_date,
            max_catchup_days=max_catchup_days,
        )
    except Exception as error:
        _write_catchup_failure(
            config.health_path,
            strategy_name=config.strategy_name,
            target_date=target_date,
            error=error,
        )
        raise
    results = [
        run_shadow_once(config, as_of_date=date) for date in dates
    ]
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "mode": "shadow_only",
        "orders_authorized": False,
        "strategy_name": config.strategy_name,
        "target_date": target_date.isoformat(),
        "cycles": len(results),
        "caught_up_days": sum(
            date.isoformat() not in existing_dates for date in dates
        ),
        "results": results,
    }


def missing_shadow_dates(
    journal_path,
    *,
    strategy_name,
    target_date,
    max_catchup_days,
):
    if max_catchup_days < 1:
        raise ValueError("max catch-up days must be positive")
    records = shadow_module.load_shadow_records(journal_path)
    if not records:
        return [target_date]
    if any(
        value.get("strategy_name") != strategy_name for value in records
    ):
        raise ValueError("shadow catch-up journal strategy mismatch")
    dates = [
        datetime.date.fromisoformat(value["market_end_date"])
        for value in records
    ]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("shadow catch-up journal is duplicate or out of order")
    if any(
        current - previous != datetime.timedelta(days=1)
        for previous, current in zip(dates, dates[1:])
    ):
        raise ValueError("shadow catch-up journal already contains a gap")
    latest = dates[-1]
    if latest > target_date:
        raise ValueError("shadow catch-up journal contains a future date")
    if latest == target_date:
        return [target_date]
    missing = [
        latest + datetime.timedelta(days=offset)
        for offset in range(1, (target_date - latest).days + 1)
    ]
    if len(missing) > max_catchup_days:
        raise ValueError(
            f"shadow catch-up requires {len(missing)} days, "
            f"limit={max_catchup_days}"
        )
    return missing


def _write_catchup_failure(
    health_path,
    *,
    strategy_name,
    target_date,
    error,
):
    attempt_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    previous = _read_health(health_path)
    _write_json_atomic(
        health_path,
        {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "mode": "shadow_only",
            "orders_authorized": False,
            "status": "failed",
            "last_attempt_at": attempt_at,
            "last_success_at": previous.get("last_success_at"),
            "as_of_date": target_date.isoformat(),
            "strategy_name": strategy_name,
            "error_type": type(error).__name__,
            "error": str(error),
        },
    )


def _run_locked(config, *, start_date, as_of, attempt_at):
    with tempfile.TemporaryDirectory(
        prefix=".trend-shadow-", dir=config.output_root
    ) as temporary_value:
        temporary = pathlib.Path(temporary_value)
        collector_path = temporary / "kucoin-futures.data"
        funding_path = temporary / "kucoin-funding.json"
        market_config = market_data_module.BinanceArchiveConfig(
            symbol_mapping=KUCOIN_FUTURES_SYMBOLS,
            start_date=start_date,
            end_date=as_of,
            allowed_15m_gaps=0,
        )
        collector_result = market_data_module.fetch_kucoin_futures_hourly(
            market_config, collector_path
        )
        funding_payload = funding_module.fetch_kucoin_funding(
            KUCOIN_FUTURES_SYMBOLS,
            funding_module.parse_utc_date(start_date.isoformat()),
            funding_module.parse_utc_date(
                as_of.isoformat(), end_of_day=True
            ),
        )
        funding_result = funding_module.save_funding(
            funding_payload, funding_path
        )
        report = trend_module.evaluate_trend(
            [collector_path],
            [funding_path],
            initial_capital=config.initial_capital,
            cost_stress_multiplier=config.cost_stress_multiplier,
        )
        if config.strategy_name not in report["reports"]:
            raise ValueError(
                f"configured strategy is absent: {config.strategy_name}"
            )
        strategy = report["reports"][config.strategy_name]
        if strategy["evaluation_end_date"] != as_of.isoformat():
            raise ValueError(
                "evaluated market does not end on the requested UTC day"
            )
        report["created_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        previous_records = shadow_module.load_shadow_records(
            config.journal_path
        )
        previous = previous_records[-1] if previous_records else None
        candidate_weights = strategy["latest_rebalance_target_weights"]
        rebalance_due = as_of.weekday() == config.rebalance_weekday_utc
        initialized = previous is None
        applied_weights = _select_applied_weights(
            candidate_weights,
            previous,
            as_of=as_of,
            rebalance_due=rebalance_due,
        )
        strategy["shadow_applied_weights"] = applied_weights
        strategy_config = strategy.get("config", {})
        cost_per_turnover = float(
            strategy_config.get("fee_per_turnover", 0.0)
        ) + float(strategy_config.get("slippage_per_turnover", 0.0))
        report["shadow_runner"] = {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "mode": "shadow_only",
            "orders_authorized": False,
            "as_of_date": as_of.isoformat(),
            "history_start_date": start_date.isoformat(),
            "history_days": config.history_days,
            "collector_sha256": collector_result["collector"]["sha256"],
            "funding_sha256": funding_result["sha256"],
            "collector_coverage": collector_result["coverage"],
            "funding_points": funding_result["points"],
            "rebalance_weekday_utc": config.rebalance_weekday_utc,
            "rebalance_due": rebalance_due,
            "initialized": initialized,
            "cost_per_turnover": cost_per_turnover,
        }
        report_path = (
            config.output_root
            / f"trend-shadow-{as_of.strftime('%Y%m%d')}.json"
        )
        _write_json_atomic(report_path, _json_safe(report))
        journal_result = shadow_module.record_trend_shadow(
            report_path,
            config.strategy_name,
            config.journal_path,
        )
        report_sha256 = _sha256(report_path)
        success_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        health = {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "mode": "shadow_only",
            "orders_authorized": False,
            "status": "healthy",
            "last_attempt_at": attempt_at,
            "last_success_at": success_at,
            "as_of_date": as_of.isoformat(),
            "history_start_date": start_date.isoformat(),
            "symbols": len(KUCOIN_FUTURES_SYMBOLS),
            "report_path": str(report_path),
            "report_sha256": report_sha256,
            "journal_path": str(config.journal_path),
            "journal_appended": journal_result["appended"],
            "strategy_name": config.strategy_name,
            "target_gross_exposure": journal_result["record"][
                "target_gross_exposure"
            ],
            "target_net_exposure": journal_result["record"][
                "target_net_exposure"
            ],
        }
        _write_json_atomic(config.health_path, health)
        return health


def _select_applied_weights(
    candidate_weights,
    previous_record,
    *,
    as_of,
    rebalance_due,
):
    if previous_record is None:
        return candidate_weights
    previous_date = datetime.date.fromisoformat(
        previous_record["market_end_date"]
    )
    if previous_date > as_of:
        raise ValueError("shadow journal contains a future market date")
    previous_weights = previous_record["target_weights"]
    if set(previous_weights) != set(candidate_weights):
        raise ValueError("shadow target universe changed")
    return candidate_weights if rebalance_due else previous_weights


def _read_health(path):
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = pathlib.Path(temporary_value)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(element) for key, element in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(element) for element in value]
    if isinstance(value, numpy.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not numpy.isfinite(value):
        return None
    return value


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
