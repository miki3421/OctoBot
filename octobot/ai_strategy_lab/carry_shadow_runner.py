"""Autonomous public-data shadow runner for the V14 trend/carry portfolio."""

from __future__ import annotations

import dataclasses
import datetime
import fcntl
import pathlib
import tempfile
import typing

from octobot.ai_strategy_lab import carry as carry_module
from octobot.ai_strategy_lab import carry_overlay as carry_overlay_module
from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module
from octobot.ai_strategy_lab import market_data as market_data_module
from octobot.ai_strategy_lab import shadow as shadow_module
from octobot.ai_strategy_lab import shadow_runner as shadow_runner_module
from octobot.ai_strategy_lab import trend as trend_module


RUNNER_SCHEMA_VERSION = 1
STRATEGY_NAME = carry_overlay_module.RISK_BUDGETED_OVERLAY_NAME
KUCOIN_FUTURES_SYMBOLS = shadow_runner_module.KUCOIN_FUTURES_SYMBOLS
KUCOIN_SPOT_SYMBOLS = {
    f"{symbol.split('/', 1)[0]}/USDT": (
        f"{symbol.split('/', 1)[0]}-USDT"
    )
    for symbol in KUCOIN_FUTURES_SYMBOLS
}


@dataclasses.dataclass(frozen=True)
class CarryShadowRunnerConfig:
    output_root: pathlib.Path
    journal_path: pathlib.Path
    health_path: pathlib.Path
    lock_path: pathlib.Path
    history_days: int = 264
    initial_capital: float = 10_000.0
    cost_stress_multiplier: float = 3.0
    max_overlay_fraction: float = 0.20
    rebalance_weekday_utc: int = 6

    def validate(self) -> None:
        if self.history_days < 250:
            raise ValueError("shadow history must contain at least 250 days")
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if self.cost_stress_multiplier < 1:
            raise ValueError("cost stress multiplier must be at least one")
        if not 0 < self.max_overlay_fraction <= 1:
            raise ValueError("max overlay fraction must be in (0, 1]")
        if not 0 <= self.rebalance_weekday_utc <= 6:
            raise ValueError("rebalance weekday must be in [0, 6]")


def run_shadow_once(
    config: CarryShadowRunnerConfig,
    *,
    as_of_date: typing.Optional[datetime.date] = None,
) -> dict:
    """Run one atomic V14 public-data cycle or fail without journaling."""
    config.validate()
    today_utc = datetime.datetime.now(datetime.timezone.utc).date()
    as_of = as_of_date or (today_utc - datetime.timedelta(days=1))
    if as_of >= today_utc:
        raise ValueError("shadow as-of date must be a fully closed UTC day")
    start_date = as_of - datetime.timedelta(days=config.history_days - 1)

    for path in (
        config.output_root,
        config.journal_path.parent,
        config.health_path.parent,
        config.lock_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
    attempt_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with config.lock_path.open("a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(
                lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise RuntimeError("V14 shadow runner is already active") from error
        try:
            return _run_locked(
                config,
                start_date=start_date,
                as_of=as_of,
                attempt_at=attempt_at,
            )
        except Exception as error:
            previous = shadow_runner_module._read_health(
                config.health_path
            )
            shadow_runner_module._write_json_atomic(
                config.health_path,
                {
                    "schema_version": RUNNER_SCHEMA_VERSION,
                    "mode": "shadow_only",
                    "orders_authorized": False,
                    "status": "failed",
                    "last_attempt_at": attempt_at,
                    "last_success_at": previous.get("last_success_at"),
                    "as_of_date": as_of.isoformat(),
                    "strategy_name": STRATEGY_NAME,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            raise


def run_shadow_catchup(
    config: CarryShadowRunnerConfig,
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
        dates = shadow_runner_module.missing_shadow_dates(
            config.journal_path,
            strategy_name=STRATEGY_NAME,
            target_date=target_date,
            max_catchup_days=max_catchup_days,
        )
    except Exception as error:
        shadow_runner_module._write_catchup_failure(
            config.health_path,
            strategy_name=STRATEGY_NAME,
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
        "strategy_name": STRATEGY_NAME,
        "target_date": target_date.isoformat(),
        "cycles": len(results),
        "caught_up_days": sum(
            date.isoformat() not in existing_dates for date in dates
        ),
        "results": results,
    }


def _run_locked(config, *, start_date, as_of, attempt_at):
    with tempfile.TemporaryDirectory(
        prefix=".v14-shadow-", dir=config.output_root
    ) as temporary_value:
        temporary = pathlib.Path(temporary_value)
        futures_path = temporary / "kucoin-futures.data"
        spot_path = temporary / "kucoin-spot.data"
        funding_path = temporary / "kucoin-funding.json"
        futures_config = market_data_module.BinanceArchiveConfig(
            symbol_mapping=KUCOIN_FUTURES_SYMBOLS,
            start_date=start_date,
            end_date=as_of,
            allowed_15m_gaps=0,
        )
        spot_config = market_data_module.BinanceArchiveConfig(
            symbol_mapping=KUCOIN_SPOT_SYMBOLS,
            start_date=start_date,
            end_date=as_of,
            allowed_15m_gaps=0,
        )
        futures_result = market_data_module.fetch_kucoin_futures_hourly(
            futures_config, futures_path
        )
        spot_result = market_data_module.fetch_kucoin_spot_hourly(
            spot_config, spot_path
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
        report = _build_report(
            config,
            futures_path=futures_path,
            spot_path=spot_path,
            funding_path=funding_path,
            as_of=as_of,
        )
        report["created_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        report["shadow_runner"].update(
            {
                "schema_version": RUNNER_SCHEMA_VERSION,
                "mode": "shadow_only",
                "orders_authorized": False,
                "as_of_date": as_of.isoformat(),
                "history_start_date": start_date.isoformat(),
                "history_days": config.history_days,
                "futures_collector_sha256": futures_result[
                    "collector"
                ]["sha256"],
                "spot_collector_sha256": spot_result["collector"]["sha256"],
                "funding_sha256": funding_result["sha256"],
                "futures_coverage": futures_result["coverage"],
                "spot_coverage": spot_result["coverage"],
                "funding_points": funding_result["points"],
            }
        )
        report_path = (
            config.output_root
            / f"v14-shadow-{as_of.strftime('%Y%m%d')}.json"
        )
        shadow_runner_module._write_json_atomic(
            report_path, shadow_runner_module._json_safe(report)
        )
        journal_result = shadow_module.record_trend_shadow(
            report_path,
            STRATEGY_NAME,
            config.journal_path,
        )
        success_at = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        health = {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "mode": "shadow_only",
            "orders_authorized": False,
            "status": "healthy",
            "last_attempt_at": attempt_at,
            "last_success_at": success_at,
            "as_of_date": as_of.isoformat(),
            "history_start_date": start_date.isoformat(),
            "strategy_name": STRATEGY_NAME,
            "futures_symbols": len(KUCOIN_FUTURES_SYMBOLS),
            "spot_symbols": len(KUCOIN_SPOT_SYMBOLS),
            "report_path": str(report_path),
            "report_sha256": shadow_runner_module._sha256(report_path),
            "journal_path": str(config.journal_path),
            "journal_appended": journal_result["appended"],
            "target_gross_exposure": journal_result["record"][
                "target_gross_exposure"
            ],
            "target_net_exposure": journal_result["record"][
                "target_net_exposure"
            ],
        }
        shadow_runner_module._write_json_atomic(config.health_path, health)
        return health


def _build_report(
    config,
    *,
    futures_path,
    spot_path,
    funding_path,
    as_of,
):
    futures = dataset_module.load_collector_series(
        [futures_path], required_time_frames=("1h",)
    )
    spot = dataset_module.load_collector_series(
        [spot_path], required_time_frames=("1h",)
    )
    funding = funding_module.load_funding(funding_path)
    trend_report = trend_module.evaluate_trend(
        [futures_path],
        [funding_path],
        initial_capital=config.initial_capital,
        cost_stress_multiplier=config.cost_stress_multiplier,
        config_names=[
            carry_overlay_module.RISK_BUDGETED_TREND_CONFIG_NAME
        ],
        include_leave_one_asset_out=False,
    )
    trend_strategy_name = (
        f"{carry_overlay_module.RISK_BUDGETED_TREND_CONFIG_NAME}"
        f"_cost_stress_{config.cost_stress_multiplier:g}x"
    )
    if trend_strategy_name not in trend_report["reports"]:
        raise ValueError("V13 trend report is missing the stressed strategy")
    trend_strategy = trend_report["reports"][trend_strategy_name]
    if trend_strategy["evaluation_end_date"] != as_of.isoformat():
        raise ValueError("V14 trend market does not end on requested day")

    pairs = carry_module._pair_symbols(futures, spot, funding)
    carry_config = carry_overlay_module._stressed_carry_config(
        config.cost_stress_multiplier
    )
    sleeves = [
        carry_module._simulate_sleeve(
            base,
            futures[futures_symbol]["1h"],
            spot[spot_symbol]["1h"],
            funding[futures_symbol],
            carry_config,
        )
        for base, futures_symbol, spot_symbol in pairs
    ]
    previous_records = shadow_module.load_shadow_records(
        config.journal_path
    )
    previous = previous_records[-1] if previous_records else None
    rebalance_due = as_of.weekday() == config.rebalance_weekday_utc
    candidate_trend = trend_strategy[
        "latest_rebalance_target_weights"
    ]
    applied_trend = _select_applied_trend_weights(
        candidate_trend,
        previous,
        as_of=as_of,
        rebalance_due=rebalance_due,
    )
    latest_futures = _latest_closes(futures, as_of)
    latest_spot = _latest_closes(spot, as_of)
    candidate = _instrument_state(
        candidate_trend,
        trend_strategy["latest_signal"],
        pairs,
        sleeves,
        latest_futures,
        latest_spot,
        trend_strategy["latest_daily_funding"],
        carry_config,
        trend_cost_per_turnover=(
            float(trend_strategy["config"]["fee_per_turnover"])
            + float(trend_strategy["config"]["slippage_per_turnover"])
        ),
        max_overlay_fraction=config.max_overlay_fraction,
    )
    applied = _instrument_state(
        applied_trend,
        trend_strategy["latest_signal"],
        pairs,
        sleeves,
        latest_futures,
        latest_spot,
        trend_strategy["latest_daily_funding"],
        carry_config,
        trend_cost_per_turnover=(
            float(trend_strategy["config"]["fee_per_turnover"])
            + float(trend_strategy["config"]["slippage_per_turnover"])
        ),
        max_overlay_fraction=config.max_overlay_fraction,
    )
    days_until_rebalance = (
        config.rebalance_weekday_utc - as_of.weekday()
    ) % 7
    strategy = {
        "config": {
            "name": STRATEGY_NAME,
            "trend": trend_strategy["config"],
            "carry": dataclasses.asdict(carry_config),
            "max_overlay_fraction": config.max_overlay_fraction,
            "gross_exposure_cap": 1.0,
            "netting_assumed": False,
        },
        "evaluation_end_date": as_of.isoformat(),
        "ending_weights": applied["weights"],
        "latest_rebalance_target_weights": candidate["weights"],
        "shadow_applied_weights": applied["weights"],
        "latest_signal": applied["signals"],
        "latest_close": applied["closes"],
        "latest_daily_funding": applied["funding"],
        "days_until_next_rebalance": days_until_rebalance,
        "active_carry_pairs": applied["active_carry_pairs"],
        "overlay_allocation": applied["overlay_allocation"],
        "conservative_gross_exposure": applied[
            "conservative_gross_exposure"
        ],
    }
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "research_only": True,
        "orders_authorized": False,
        "reports": {STRATEGY_NAME: strategy},
        "shadow_runner": {
            "rebalance_weekday_utc": config.rebalance_weekday_utc,
            "rebalance_due": rebalance_due,
            "initialized": previous is None,
            "cost_per_turnover": None,
            "cost_per_turnover_by_instrument": applied["costs"],
        },
    }


def _select_applied_trend_weights(
    candidate_weights,
    previous_record,
    *,
    as_of,
    rebalance_due,
):
    if previous_record is None:
        return candidate_weights
    previous_trend = {
        key.split(":", 1)[1]: value
        for key, value in previous_record["target_weights"].items()
        if key.startswith("trend:")
    }
    if set(previous_trend) != set(candidate_weights):
        raise ValueError("V14 trend target universe changed")
    return shadow_runner_module._select_applied_weights(
        candidate_weights,
        {
            "market_end_date": previous_record["market_end_date"],
            "target_weights": previous_trend,
        },
        as_of=as_of,
        rebalance_due=rebalance_due,
    )


def _latest_closes(series_by_symbol, as_of):
    result = {}
    for symbol, time_frames in series_by_symbol.items():
        series = time_frames["1h"]
        close_date = datetime.datetime.fromtimestamp(
            int(series.close_times[-1]) - 1,
            datetime.timezone.utc,
        ).date()
        if close_date != as_of:
            raise ValueError(f"{symbol} does not end on requested day")
        result[symbol] = float(series.values[-1][4])
    return result


def _instrument_state(
    trend_weights,
    trend_signals,
    pairs,
    sleeves,
    futures_closes,
    spot_closes,
    daily_funding,
    carry_config,
    *,
    trend_cost_per_turnover,
    max_overlay_fraction,
):
    if len(pairs) != len(sleeves):
        raise ValueError("carry pair and sleeve counts differ")
    trend_gross = sum(abs(float(value)) for value in trend_weights.values())
    overlay_allocation = min(
        max_overlay_fraction, max(0.0, 1.0 - trend_gross)
    )
    per_sleeve_leg = (
        overlay_allocation * carry_config.leg_fraction / len(pairs)
    )
    weights = {}
    signals = {}
    closes = {}
    funding = {}
    costs = {}
    futures_carry_cost = (
        carry_config.futures_fee_per_fill
        + carry_config.slippage_per_fill
    )
    spot_carry_cost = (
        carry_config.spot_fee_per_fill
        + carry_config.slippage_per_fill
    )
    for symbol in sorted(trend_weights):
        key = f"trend:{symbol}"
        weights[key] = float(trend_weights[symbol])
        signals[key] = int(trend_signals[symbol])
        closes[key] = float(futures_closes[symbol])
        funding[key] = float(daily_funding[symbol])
        costs[key] = trend_cost_per_turnover
    active_pairs = []
    for (
        (base, futures_symbol, spot_symbol),
        sleeve,
    ) in zip(pairs, sleeves):
        is_open = bool(sleeve["position_open_at_end"])
        if is_open:
            active_pairs.append(base)
        future_key = f"carry-futures:{futures_symbol}"
        spot_key = f"carry-spot:{spot_symbol}"
        weights[future_key] = -per_sleeve_leg if is_open else 0.0
        weights[spot_key] = per_sleeve_leg if is_open else 0.0
        signals[future_key] = -1 if is_open else 0
        signals[spot_key] = 1 if is_open else 0
        closes[future_key] = float(futures_closes[futures_symbol])
        closes[spot_key] = float(spot_closes[spot_symbol])
        funding[future_key] = float(daily_funding[futures_symbol])
        funding[spot_key] = 0.0
        costs[future_key] = futures_carry_cost
        costs[spot_key] = spot_carry_cost
    conservative_gross = sum(abs(value) for value in weights.values())
    if conservative_gross > 1.0 + 1e-12:
        raise ValueError("V14 conservative gross exposure exceeds one")
    return {
        "weights": weights,
        "signals": signals,
        "closes": closes,
        "funding": funding,
        "costs": costs,
        "active_carry_pairs": active_pairs,
        "overlay_allocation": overlay_allocation,
        "conservative_gross_exposure": conservative_gross,
    }
