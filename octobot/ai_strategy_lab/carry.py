"""Delta-neutral spot/perpetual funding-carry research."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module
from octobot.ai_strategy_lab import funding as funding_module


CARRY_SCHEMA_VERSION = 2


@dataclasses.dataclass(frozen=True)
class CarryConfig:
    name: str
    lookback_settlements: int
    entry_average_rate: float
    entry_min_monthly_gross: float
    entry_min_basis: float
    exit_average_rate: float
    max_holding_days: int
    spot_fee_per_fill: float = 0.001
    futures_fee_per_fill: float = 0.0006
    slippage_per_fill: float = 0.0002
    leg_fraction: float = 0.5
    positive_funding_realization: float = 1.0
    entry_delay_settlements: int = 0
    entry_positive_funding_realization: float = 1.0
    entry_round_trip_cost_rate: float = 0.0
    maximum_cost_payback_days: float = 0.0
    revalidate_entry_at_execution: bool = False

    def validate(self) -> None:
        if self.lookback_settlements < 2:
            raise ValueError("carry lookback must be at least two settlements")
        if self.max_holding_days < 1:
            raise ValueError("max holding days must be positive")
        if not 0 < self.leg_fraction <= 0.5:
            raise ValueError("leg_fraction must be in (0, 0.5]")
        if not 0 <= self.positive_funding_realization <= 1:
            raise ValueError(
                "positive_funding_realization must be in [0, 1]"
            )
        if self.entry_delay_settlements < 0:
            raise ValueError("entry_delay_settlements cannot be negative")
        if not 0 < self.entry_positive_funding_realization <= 1:
            raise ValueError(
                "entry_positive_funding_realization must be in (0, 1]"
            )
        if self.entry_round_trip_cost_rate < 0:
            raise ValueError("entry round-trip cost cannot be negative")
        if self.maximum_cost_payback_days < 0:
            raise ValueError("maximum cost payback days cannot be negative")
        if (
            bool(self.entry_round_trip_cost_rate)
            != bool(self.maximum_cost_payback_days)
        ):
            raise ValueError(
                "entry cost and maximum payback days must be set together"
            )
        for field in (
            "entry_average_rate",
            "entry_min_monthly_gross",
            "spot_fee_per_fill",
            "futures_fee_per_fill",
            "slippage_per_fill",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} cannot be negative")


# Pre-registered screening protocols. Add a new version rather than editing
# these constants after observing their reports.
CARRY_CONFIGS = (
    CarryConfig(
        name="steady_positive_v1",
        lookback_settlements=6,
        entry_average_rate=0.0001,
        entry_min_monthly_gross=0.003,
        entry_min_basis=0.0,
        exit_average_rate=0.000025,
        max_holding_days=90,
    ),
    CarryConfig(
        name="high_carry_v1",
        lookback_settlements=3,
        entry_average_rate=0.0003,
        entry_min_monthly_gross=0.006,
        entry_min_basis=-0.002,
        exit_average_rate=0.00005,
        max_holding_days=45,
    ),
    CarryConfig(
        name="persistent_carry_v1",
        lookback_settlements=12,
        entry_average_rate=0.00008,
        entry_min_monthly_gross=0.003,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=120,
    ),
    CarryConfig(
        name="cost_aware_persistent_v2",
        lookback_settlements=30,
        entry_average_rate=0.00008,
        entry_min_monthly_gross=0.003,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=120,
        entry_delay_settlements=1,
        entry_positive_funding_realization=0.5,
        entry_round_trip_cost_rate=0.01,
        maximum_cost_payback_days=60.0,
    ),
    CarryConfig(
        name="execution_guarded_cost_aware_v3",
        lookback_settlements=30,
        entry_average_rate=0.00008,
        entry_min_monthly_gross=0.003,
        entry_min_basis=0.0,
        exit_average_rate=0.0,
        max_holding_days=120,
        entry_delay_settlements=1,
        entry_positive_funding_realization=0.5,
        entry_round_trip_cost_rate=0.01,
        maximum_cost_payback_days=60.0,
        revalidate_entry_at_execution=True,
    ),
)


def evaluate_carry(
    futures_collector: typing.Union[
        str,
        "pathlib.Path",
        typing.Iterable[typing.Union[str, "pathlib.Path"]],
    ],
    spot_collector: typing.Union[str, "pathlib.Path"],
    funding_path: typing.Union[str, "pathlib.Path"],
    *,
    initial_capital: float = 10_000.0,
    cost_stress_multiplier: float = 1.5,
) -> dict:
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    if cost_stress_multiplier < 1:
        raise ValueError("cost stress multiplier must be at least one")
    futures_values = (
        [futures_collector]
        if isinstance(futures_collector, (str, pathlib.Path))
        else list(futures_collector)
    )
    futures = dataset_module.load_collector_series(
        [pathlib.Path(value).resolve() for value in futures_values],
        required_time_frames=("1h",),
    )
    spot = dataset_module.load_collector_series(
        [pathlib.Path(spot_collector).resolve()],
        required_time_frames=("1h",),
    )
    funding = funding_module.load_funding(funding_path)
    pairs = _pair_symbols(futures, spot, funding)
    reports = {}
    for config in CARRY_CONFIGS:
        config.validate()
        for evaluated_config in (
            config,
            dataclasses.replace(
                config,
                name=f"{config.name}_cost_stress_{cost_stress_multiplier:g}x",
                spot_fee_per_fill=(
                    config.spot_fee_per_fill * cost_stress_multiplier
                ),
                futures_fee_per_fill=(
                    config.futures_fee_per_fill * cost_stress_multiplier
                ),
                slippage_per_fill=(
                    config.slippage_per_fill * cost_stress_multiplier
                ),
            ),
        ):
            sleeves = []
            for base, futures_symbol, spot_symbol in pairs:
                sleeves.append(
                    _simulate_sleeve(
                        base,
                        futures[futures_symbol]["1h"],
                        spot[spot_symbol]["1h"],
                        funding[futures_symbol],
                        evaluated_config,
                    )
                )
            reports[evaluated_config.name] = _portfolio_report(
                sleeves, evaluated_config, initial_capital
            )
            rotation = _simulate_rotation(
                [
                    (
                        base,
                        futures[futures_symbol]["1h"],
                        spot[spot_symbol]["1h"],
                        funding[futures_symbol],
                    )
                    for base, futures_symbol, spot_symbol in pairs
                ],
                evaluated_config,
            )
            rotation_report = _portfolio_report(
                [rotation], evaluated_config, initial_capital
            )
            by_symbol = {}
            for trade in rotation["trades"]:
                symbol = by_symbol.setdefault(
                    trade["base"],
                    {"trades": 0, "compounded_trade_return": 0.0},
                )
                symbol["trades"] += 1
                symbol["compounded_trade_return"] = (
                    (1.0 + symbol["compounded_trade_return"])
                    * (1.0 + trade["net_return"])
                    - 1.0
                )
            rotation_report["by_symbol"] = by_symbol
            rotation_report["allocation"] = (
                "single full-capital sleeve rotated to highest eligible carry"
            )
            reports[f"rotation_{evaluated_config.name}"] = rotation_report
    return {
        "schema_version": CARRY_SCHEMA_VERSION,
        "research_only": True,
        "assumptions": {
            "portfolio": "equal-weight independent asset sleeves",
            "hedge": "equal spot-long and perpetual-short entry notionals",
            "funding": "signed historical rate applied to current short notional",
            "execution": "hourly close at/after known settlement plus explicit slippage",
            "excluded": [
                "tax",
                "exchange default",
                "withdrawal latency",
                "order book depth beyond configured slippage",
            ],
        },
        "initial_capital": initial_capital,
        "cost_stress_multiplier": cost_stress_multiplier,
        "pairs": [
            {
                "base": base,
                "futures_symbol": futures_symbol,
                "spot_symbol": spot_symbol,
            }
            for base, futures_symbol, spot_symbol in pairs
        ],
        "configs": [dataclasses.asdict(value) for value in CARRY_CONFIGS],
        "reports": reports,
    }


def _pair_symbols(futures, spot, funding):
    futures_by_base = {
        symbol.split("/", 1)[0]: symbol for symbol in futures
    }
    spot_by_base = {symbol.split("/", 1)[0]: symbol for symbol in spot}
    bases = sorted(set(futures_by_base) & set(spot_by_base))
    result = []
    for base in bases:
        futures_symbol = futures_by_base[base]
        if futures_symbol not in funding:
            raise ValueError(f"missing funding for {futures_symbol}")
        result.append((base, futures_symbol, spot_by_base[base]))
    if not result:
        raise ValueError("no common spot/perpetual symbols")
    return result


def _simulate_sleeve(base, futures, spot, funding, config):
    funding_timestamps, funding_rates = funding
    common = _aligned_settlements(
        futures, spot, funding_timestamps, funding_rates
    )
    equity = 1.0
    position = None
    pending_entry = None
    rate_history = []
    timestamp_history = []
    equity_points = []
    active_points = []
    trades = []
    for point in common:
        timestamp, rate, futures_price, spot_price = point
        rate_history.append(rate)
        timestamp_history.append(timestamp)
        if position is not None:
            current_futures_notional = (
                config.leg_fraction
                * position["entry_equity"]
                * futures_price
                / position["futures_entry"]
            )
            position["funding_cash"] += (
                current_futures_notional
                * _realized_funding_rate(rate, config)
            )
            rolling = float(
                numpy.mean(rate_history[-config.lookback_settlements :])
            )
            age_days = (
                timestamp - position["entry_timestamp"]
            ) / 86400.0
            if (
                rolling <= config.exit_average_rate
                or age_days >= config.max_holding_days
            ):
                equity = _position_equity(
                    position,
                    futures_price,
                    spot_price,
                    config,
                    include_exit_cost=True,
                )
                trades.append(
                    {
                        "base": base,
                        "signal_timestamp": position.get(
                            "signal_timestamp",
                            position["entry_timestamp"],
                        ),
                        "signal_basis": position.get(
                            "signal_basis", position["entry_basis"]
                        ),
                        "signal_expected_monthly_gross": position.get(
                            "signal_expected_monthly_gross"
                        ),
                        "signal_stressed_cost_payback_days": position.get(
                            "signal_stressed_cost_payback_days"
                        ),
                        "execution_expected_monthly_gross": position.get(
                            "execution_expected_monthly_gross"
                        ),
                        "execution_stressed_cost_payback_days": (
                            position.get(
                                "execution_stressed_cost_payback_days"
                            )
                        ),
                        "entry_timestamp": position["entry_timestamp"],
                        "exit_timestamp": timestamp,
                        "holding_days": age_days,
                        "entry_basis": position["entry_basis"],
                        "exit_basis": futures_price / spot_price - 1.0,
                        "funding_cash": position["funding_cash"],
                        "net_return": equity / position["entry_equity"] - 1.0,
                        "exit_reason": (
                            "max_holding"
                            if age_days >= config.max_holding_days
                            else "funding_decay"
                        ),
                    }
                )
                position = None

        opened_from_pending = False
        if position is None and pending_entry is not None:
            pending_entry["remaining_settlements"] -= 1
            if pending_entry["remaining_settlements"] <= 0:
                execution_metrics = _entry_metrics(
                    rate_history,
                    timestamp_history,
                    futures_price,
                    spot_price,
                    config,
                )
                can_execute = (
                    not config.revalidate_entry_at_execution
                    or execution_metrics is not None
                )
                if can_execute:
                    basis = futures_price / spot_price - 1.0
                    entry_cost = _fill_cost(
                        equity,
                        config,
                        spot_ratio=1.0,
                        futures_ratio=1.0,
                    )
                    position = {
                        "signal_timestamp": pending_entry[
                            "signal_timestamp"
                        ],
                        "signal_basis": pending_entry["signal_basis"],
                        "signal_expected_monthly_gross": pending_entry.get(
                            "signal_expected_monthly_gross"
                        ),
                        "signal_stressed_cost_payback_days": (
                            pending_entry.get(
                                "signal_stressed_cost_payback_days"
                            )
                        ),
                        "execution_expected_monthly_gross": (
                            execution_metrics["expected_monthly"]
                            if execution_metrics is not None
                            else None
                        ),
                        "execution_stressed_cost_payback_days": (
                            execution_metrics["payback_days"]
                            if execution_metrics is not None
                            else None
                        ),
                        "entry_timestamp": timestamp,
                        "entry_equity": equity,
                        "futures_entry": futures_price,
                        "spot_entry": spot_price,
                        "entry_basis": basis,
                        "funding_cash": 0.0,
                        "entry_cost": entry_cost,
                    }
                    opened_from_pending = True
                pending_entry = None

        if (
            position is None
            and pending_entry is None
            and not opened_from_pending
            and len(rate_history) >= config.lookback_settlements
        ):
            recent = rate_history[-config.lookback_settlements :]
            average_rate = float(numpy.mean(recent))
            intervals_per_month = _intervals_per_month(
                timestamp_history[-config.lookback_settlements :]
            )
            expected_monthly = (
                average_rate * intervals_per_month * config.leg_fraction
            )
            payback_days = _stressed_cost_payback_days(
                expected_monthly, config
            )
            basis = futures_price / spot_price - 1.0
            if (
                all(value > 0 for value in recent)
                and average_rate >= config.entry_average_rate
                and expected_monthly >= config.entry_min_monthly_gross
                and basis >= config.entry_min_basis
                and (
                    not config.maximum_cost_payback_days
                    or payback_days <= config.maximum_cost_payback_days
                )
            ):
                if config.entry_delay_settlements:
                    pending_entry = {
                        "signal_timestamp": timestamp,
                        "signal_basis": basis,
                        "signal_expected_monthly_gross": expected_monthly,
                        "signal_stressed_cost_payback_days": payback_days,
                        "remaining_settlements": (
                            config.entry_delay_settlements
                        ),
                    }
                else:
                    entry_cost = _fill_cost(
                        equity,
                        config,
                        spot_ratio=1.0,
                        futures_ratio=1.0,
                    )
                    position = {
                        "signal_timestamp": timestamp,
                        "signal_basis": basis,
                        "signal_expected_monthly_gross": expected_monthly,
                        "signal_stressed_cost_payback_days": payback_days,
                        "entry_timestamp": timestamp,
                        "entry_equity": equity,
                        "futures_entry": futures_price,
                        "spot_entry": spot_price,
                        "entry_basis": basis,
                        "funding_cash": 0.0,
                        "entry_cost": entry_cost,
                    }

        marked_equity = (
            equity
            if position is None
            else _position_equity(
                position,
                futures_price,
                spot_price,
                config,
                include_exit_cost=False,
            )
        )
        equity_points.append((timestamp, marked_equity))
        active_points.append((timestamp, position is not None))

    position_open_at_end = position is not None
    if position is not None and common:
        timestamp, _, futures_price, spot_price = common[-1]
        equity = _position_equity(
            position,
            futures_price,
            spot_price,
            config,
            include_exit_cost=True,
        )
        trades.append(
            {
                "base": base,
                "signal_timestamp": position.get(
                    "signal_timestamp", position["entry_timestamp"]
                ),
                "signal_basis": position.get(
                    "signal_basis", position["entry_basis"]
                ),
                "signal_expected_monthly_gross": position.get(
                    "signal_expected_monthly_gross"
                ),
                "signal_stressed_cost_payback_days": position.get(
                    "signal_stressed_cost_payback_days"
                ),
                "execution_expected_monthly_gross": position.get(
                    "execution_expected_monthly_gross"
                ),
                "execution_stressed_cost_payback_days": position.get(
                    "execution_stressed_cost_payback_days"
                ),
                "entry_timestamp": position["entry_timestamp"],
                "exit_timestamp": timestamp,
                "holding_days": (
                    timestamp - position["entry_timestamp"]
                )
                / 86400.0,
                "entry_basis": position["entry_basis"],
                "exit_basis": futures_price / spot_price - 1.0,
                "funding_cash": position["funding_cash"],
                "net_return": equity / position["entry_equity"] - 1.0,
                "exit_reason": "end_of_data",
            }
        )
        equity_points[-1] = (timestamp, equity)
    return {
        "base": base,
        "equity_points": equity_points,
        "active_points": active_points,
        "trades": trades,
        "final_equity": equity,
        "position_open_at_end": position_open_at_end,
        "latest_settlement_timestamp": (
            int(common[-1][0]) if common else None
        ),
    }


def _simulate_rotation(pair_inputs, config):
    points_by_base = {
        base: _aligned_settlements(
            futures, spot, funding[0], funding[1]
        )
        for base, futures, spot, funding in pair_inputs
    }
    events = {}
    for base, points in points_by_base.items():
        for point in points:
            events.setdefault(point[0], {})[base] = point
    histories = {
        base: {"rates": [], "timestamps": []} for base in points_by_base
    }
    latest = {}
    equity = 1.0
    position = None
    pending_entry = None
    trades = []
    equity_points = []
    active_points = []
    for timestamp in sorted(events):
        event = events[timestamp]
        for base, point in event.items():
            latest[base] = point
            histories[base]["rates"].append(point[1])
            histories[base]["timestamps"].append(timestamp)

        if position is not None and position["base"] in event:
            base = position["base"]
            _, rate, futures_price, spot_price = event[base]
            current_futures_notional = (
                config.leg_fraction
                * position["entry_equity"]
                * futures_price
                / position["futures_entry"]
            )
            position["funding_cash"] += (
                current_futures_notional
                * _realized_funding_rate(rate, config)
            )
            rolling = float(
                numpy.mean(
                    histories[base]["rates"][-config.lookback_settlements :]
                )
            )
            age_days = (
                timestamp - position["entry_timestamp"]
            ) / 86400.0
            if (
                rolling <= config.exit_average_rate
                or age_days >= config.max_holding_days
            ):
                equity = _position_equity(
                    position,
                    futures_price,
                    spot_price,
                    config,
                    include_exit_cost=True,
                )
                trades.append(
                    _closed_trade(
                        position,
                        timestamp,
                        futures_price,
                        spot_price,
                        equity,
                        (
                            "max_holding"
                            if age_days >= config.max_holding_days
                            else "funding_decay"
                        ),
                    )
                )
                position = None

        opened_from_pending = False
        if (
            position is None
            and pending_entry is not None
            and pending_entry["base"] in event
        ):
            pending_entry["remaining_settlements"] -= 1
            if pending_entry["remaining_settlements"] <= 0:
                base = pending_entry["base"]
                _, _, futures_price, spot_price = event[base]
                execution_metrics = _entry_metrics(
                    histories[base]["rates"],
                    histories[base]["timestamps"],
                    futures_price,
                    spot_price,
                    config,
                )
                can_execute = (
                    not config.revalidate_entry_at_execution
                    or execution_metrics is not None
                )
                if can_execute:
                    basis = futures_price / spot_price - 1.0
                    position = {
                        "base": base,
                        "signal_timestamp": pending_entry[
                            "signal_timestamp"
                        ],
                        "signal_basis": pending_entry["signal_basis"],
                        "signal_expected_monthly_gross": pending_entry.get(
                            "signal_expected_monthly_gross"
                        ),
                        "signal_stressed_cost_payback_days": (
                            pending_entry.get(
                                "signal_stressed_cost_payback_days"
                            )
                        ),
                        "execution_expected_monthly_gross": (
                            execution_metrics["expected_monthly"]
                            if execution_metrics is not None
                            else None
                        ),
                        "execution_stressed_cost_payback_days": (
                            execution_metrics["payback_days"]
                            if execution_metrics is not None
                            else None
                        ),
                        "entry_timestamp": timestamp,
                        "entry_equity": equity,
                        "futures_entry": futures_price,
                        "spot_entry": spot_price,
                        "entry_basis": basis,
                        "funding_cash": 0.0,
                        "entry_cost": _fill_cost(
                            equity,
                            config,
                            spot_ratio=1.0,
                            futures_ratio=1.0,
                        ),
                    }
                    opened_from_pending = True
                pending_entry = None

        if (
            position is None
            and pending_entry is None
            and not opened_from_pending
        ):
            candidates = []
            for base, point in event.items():
                rates = histories[base]["rates"]
                times = histories[base]["timestamps"]
                if len(rates) < config.lookback_settlements:
                    continue
                recent = rates[-config.lookback_settlements :]
                average_rate = float(numpy.mean(recent))
                expected_monthly = (
                    average_rate
                    * _intervals_per_month(
                        times[-config.lookback_settlements :]
                    )
                    * config.leg_fraction
                )
                payback_days = _stressed_cost_payback_days(
                    expected_monthly, config
                )
                _, _, futures_price, spot_price = point
                basis = futures_price / spot_price - 1.0
                if (
                    all(value > 0 for value in recent)
                    and average_rate >= config.entry_average_rate
                    and expected_monthly >= config.entry_min_monthly_gross
                    and basis >= config.entry_min_basis
                    and (
                        not config.maximum_cost_payback_days
                        or payback_days
                        <= config.maximum_cost_payback_days
                    )
                ):
                    candidates.append(
                        (
                            expected_monthly,
                            basis,
                            base,
                            futures_price,
                            spot_price,
                            payback_days,
                        )
                    )
            if candidates:
                (
                    selected_expected_monthly,
                    basis,
                    base,
                    futures_price,
                    spot_price,
                    payback_days,
                ) = max(candidates)
                if config.entry_delay_settlements:
                    pending_entry = {
                        "base": base,
                        "signal_timestamp": timestamp,
                        "signal_basis": basis,
                        "signal_expected_monthly_gross": (
                            selected_expected_monthly
                        ),
                        "signal_stressed_cost_payback_days": payback_days,
                        "remaining_settlements": (
                            config.entry_delay_settlements
                        ),
                    }
                else:
                    position = {
                        "base": base,
                        "signal_timestamp": timestamp,
                        "signal_basis": basis,
                        "signal_expected_monthly_gross": (
                            selected_expected_monthly
                        ),
                        "signal_stressed_cost_payback_days": payback_days,
                        "entry_timestamp": timestamp,
                        "entry_equity": equity,
                        "futures_entry": futures_price,
                        "spot_entry": spot_price,
                        "entry_basis": basis,
                        "funding_cash": 0.0,
                        "entry_cost": _fill_cost(
                            equity,
                            config,
                            spot_ratio=1.0,
                            futures_ratio=1.0,
                        ),
                    }

        if position is None:
            marked_equity = equity
        else:
            _, _, futures_price, spot_price = latest[position["base"]]
            marked_equity = _position_equity(
                position,
                futures_price,
                spot_price,
                config,
                include_exit_cost=False,
            )
        equity_points.append((timestamp, marked_equity))
        active_points.append((timestamp, position is not None))

    if position is not None:
        timestamp = max(events)
        _, _, futures_price, spot_price = latest[position["base"]]
        equity = _position_equity(
            position,
            futures_price,
            spot_price,
            config,
            include_exit_cost=True,
        )
        trades.append(
            _closed_trade(
                position,
                timestamp,
                futures_price,
                spot_price,
                equity,
                "end_of_data",
            )
        )
        equity_points[-1] = (timestamp, equity)
    return {
        "base": "ROTATION",
        "equity_points": equity_points,
        "active_points": active_points,
        "trades": trades,
        "final_equity": equity,
    }


def _closed_trade(
    position,
    timestamp,
    futures_price,
    spot_price,
    equity,
    reason,
):
    return {
        "base": position.get("base", ""),
        "signal_timestamp": position.get(
            "signal_timestamp", position["entry_timestamp"]
        ),
        "signal_basis": position.get(
            "signal_basis", position["entry_basis"]
        ),
        "signal_expected_monthly_gross": position.get(
            "signal_expected_monthly_gross"
        ),
        "signal_stressed_cost_payback_days": position.get(
            "signal_stressed_cost_payback_days"
        ),
        "execution_expected_monthly_gross": position.get(
            "execution_expected_monthly_gross"
        ),
        "execution_stressed_cost_payback_days": position.get(
            "execution_stressed_cost_payback_days"
        ),
        "entry_timestamp": position["entry_timestamp"],
        "exit_timestamp": timestamp,
        "holding_days": (
            timestamp - position["entry_timestamp"]
        )
        / 86400.0,
        "entry_basis": position["entry_basis"],
        "exit_basis": futures_price / spot_price - 1.0,
        "funding_cash": position["funding_cash"],
        "net_return": equity / position["entry_equity"] - 1.0,
        "exit_reason": reason,
    }


def _aligned_settlements(futures, spot, timestamps, rates):
    futures_times = futures.close_times
    spot_times = spot.close_times
    result = []
    for timestamp, rate in zip(timestamps, rates):
        futures_index = int(
            numpy.searchsorted(futures_times, timestamp, side="right") - 1
        )
        spot_index = int(
            numpy.searchsorted(spot_times, timestamp, side="right") - 1
        )
        if futures_index < 0 or spot_index < 0:
            continue
        if (
            timestamp - int(futures_times[futures_index]) > 3600
            or timestamp - int(spot_times[spot_index]) > 3600
        ):
            continue
        result.append(
            (
                int(timestamp),
                float(rate),
                float(futures.values[futures_index, 4]),
                float(spot.values[spot_index, 4]),
            )
        )
    return result


def _position_equity(
    position,
    futures_price,
    spot_price,
    config,
    *,
    include_exit_cost,
):
    entry_equity = position["entry_equity"]
    spot_ratio = spot_price / position["spot_entry"]
    futures_ratio = futures_price / position["futures_entry"]
    price_pnl = config.leg_fraction * entry_equity * (
        (spot_ratio - 1.0) - (futures_ratio - 1.0)
    )
    result = (
        entry_equity
        - position["entry_cost"]
        + price_pnl
        + position["funding_cash"]
    )
    if include_exit_cost:
        result -= _fill_cost(
            entry_equity,
            config,
            spot_ratio=spot_ratio,
            futures_ratio=futures_ratio,
        )
    return result


def _fill_cost(entry_equity, config, *, spot_ratio, futures_ratio):
    spot_notional = config.leg_fraction * entry_equity * spot_ratio
    futures_notional = config.leg_fraction * entry_equity * futures_ratio
    return (
        spot_notional * (config.spot_fee_per_fill + config.slippage_per_fill)
        + futures_notional
        * (config.futures_fee_per_fill + config.slippage_per_fill)
    )


def _realized_funding_rate(rate, config):
    return (
        rate * config.positive_funding_realization
        if rate > 0
        else rate
    )


def _stressed_cost_payback_days(expected_monthly_gross, config):
    stressed_monthly = (
        expected_monthly_gross
        * config.entry_positive_funding_realization
    )
    if config.entry_round_trip_cost_rate <= 0:
        return 0.0
    if stressed_monthly <= 0:
        return float("inf")
    return (
        30.0
        * config.entry_round_trip_cost_rate
        / stressed_monthly
    )


def _entry_metrics(
    rate_history,
    timestamp_history,
    futures_price,
    spot_price,
    config,
):
    if len(rate_history) < config.lookback_settlements:
        return None
    recent = rate_history[-config.lookback_settlements :]
    average_rate = float(numpy.mean(recent))
    intervals_per_month = _intervals_per_month(
        timestamp_history[-config.lookback_settlements :]
    )
    expected_monthly = (
        average_rate * intervals_per_month * config.leg_fraction
    )
    payback_days = _stressed_cost_payback_days(
        expected_monthly, config
    )
    basis = futures_price / spot_price - 1.0
    qualified = (
        all(value > 0 for value in recent)
        and average_rate >= config.entry_average_rate
        and expected_monthly >= config.entry_min_monthly_gross
        and basis >= config.entry_min_basis
        and (
            not config.maximum_cost_payback_days
            or payback_days <= config.maximum_cost_payback_days
        )
    )
    if not qualified:
        return None
    return {
        "average_rate": average_rate,
        "expected_monthly": expected_monthly,
        "payback_days": payback_days,
        "basis": basis,
    }


def _intervals_per_month(recent_timestamps):
    if len(recent_timestamps) < 2:
        return 90.0
    median_seconds = float(numpy.median(numpy.diff(recent_timestamps)))
    return 30.0 * 86400.0 / median_seconds


def _portfolio_equity_points(sleeves):
    all_times = sorted(
        set(
            timestamp
            for sleeve in sleeves
            for timestamp, _ in sleeve["equity_points"]
        )
    )
    if not all_times:
        raise ValueError("carry simulation has no common funding timestamps")
    series_by_base = {
        sleeve["base"]: sleeve["equity_points"] for sleeve in sleeves
    }
    cursors = {base: 0 for base in series_by_base}
    current = {base: 1.0 for base in series_by_base}
    portfolio = []
    for timestamp in all_times:
        for base, points in series_by_base.items():
            cursor = cursors[base]
            while cursor < len(points) and points[cursor][0] <= timestamp:
                current[base] = points[cursor][1]
                cursor += 1
            cursors[base] = cursor
        portfolio.append(
            (timestamp, float(numpy.mean(list(current.values()))))
        )
    return portfolio


def _portfolio_active_fraction_points(sleeves):
    all_times = sorted(
        set(
            timestamp
            for sleeve in sleeves
            for timestamp, _ in sleeve["active_points"]
        )
    )
    if not all_times:
        raise ValueError("carry activity simulation is empty")
    series_by_base = {
        sleeve["base"]: sleeve["active_points"] for sleeve in sleeves
    }
    cursors = {base: 0 for base in series_by_base}
    current = {base: False for base in series_by_base}
    portfolio = []
    for timestamp in all_times:
        for base, points in series_by_base.items():
            cursor = cursors[base]
            while cursor < len(points) and points[cursor][0] <= timestamp:
                current[base] = bool(points[cursor][1])
                cursor += 1
            cursors[base] = cursor
        portfolio.append(
            (
                timestamp,
                sum(current.values()) / len(current),
            )
        )
    return portfolio


def _portfolio_report(sleeves, config, initial_capital):
    portfolio = _portfolio_equity_points(sleeves)
    equities = numpy.asarray([value for _, value in portfolio])
    peaks = numpy.maximum.accumulate(equities)
    drawdown = 1.0 - equities / peaks
    month_ends = {}
    for timestamp, equity in portfolio:
        month = datetime.datetime.fromtimestamp(
            timestamp, datetime.timezone.utc
        ).strftime("%Y-%m")
        month_ends[month] = equity
    monthly_returns = {}
    previous = 1.0
    for month, equity in sorted(month_ends.items()):
        monthly_returns[month] = equity / previous - 1.0
        previous = equity
    trades = [
        trade for sleeve in sleeves for trade in sleeve["trades"]
    ]
    returns = numpy.asarray(
        [trade["net_return"] for trade in trades], dtype=float
    )
    profits = returns[returns > 0]
    losses = -returns[returns < 0]
    final_equity = float(equities[-1])
    elapsed_years = (
        (portfolio[-1][0] - portfolio[0][0]) / (365.25 * 86400.0)
    )
    withdrawals = {
        str(warmup): _historical_fixed_withdrawal(
            list(monthly_returns.values()),
            initial_capital,
            warmup_months=warmup,
            minimum_capital_fraction=1.0,
        )
        for warmup in (0, 12)
        if warmup < len(monthly_returns)
    }
    returns_by_year = {}
    for month, monthly_return in monthly_returns.items():
        returns_by_year.setdefault(month[:4], []).append(monthly_return)
    calendar_year_returns = {
        year: float(numpy.prod(1.0 + numpy.asarray(values)) - 1.0)
        for year, values in sorted(returns_by_year.items())
    }
    return {
        "config": dataclasses.asdict(config),
        "trades": len(trades),
        "winning_trades": int(numpy.sum(returns > 0)),
        "win_rate": float(numpy.mean(returns > 0)) if len(returns) else 0.0,
        "profit_factor": (
            float(numpy.sum(profits) / numpy.sum(losses))
            if len(losses) and numpy.sum(losses) > 0
            else (float("inf") if len(profits) else 0.0)
        ),
        "total_return": final_equity - 1.0,
        "annualized_return": (
            final_equity ** (1.0 / elapsed_years) - 1.0
            if elapsed_years > 0 and final_equity > 0
            else 0.0
        ),
        "final_capital": initial_capital * final_equity,
        "max_drawdown": float(numpy.max(drawdown)),
        "months": len(monthly_returns),
        "positive_months": sum(value > 0 for value in monthly_returns.values()),
        "negative_months": sum(value < 0 for value in monthly_returns.values()),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_returns.values())
            / len(monthly_returns)
        ),
        "median_month_return": float(
            numpy.median(list(monthly_returns.values()))
        ),
        "worst_month_return": min(monthly_returns.values()),
        "best_month_return": max(monthly_returns.values()),
        "median_month_income": initial_capital
        * float(numpy.median(list(monthly_returns.values()))),
        "monthly_returns": monthly_returns,
        "calendar_year_returns": calendar_year_returns,
        "historical_fixed_withdrawal": {
            "warning": (
                "Backtest capacity only; it is not a guaranteed future payment."
            ),
            "minimum_capital_fraction": 1.0,
            "capital_floor_policy": (
                "The original capital must never be used for withdrawals."
            ),
            "scenarios_by_warmup_months": withdrawals,
        },
        "by_symbol": {
            sleeve["base"]: {
                "trades": len(sleeve["trades"]),
                "total_return": sleeve["final_equity"] - 1.0,
            }
            for sleeve in sleeves
        },
        "trade_log": trades,
    }


def _historical_fixed_withdrawal(
    monthly_returns,
    initial_capital,
    *,
    warmup_months,
    minimum_capital_fraction,
):
    def simulate(withdrawal):
        balance = initial_capital
        minimum_balance = balance
        withdrawn = 0.0
        for index, monthly_return in enumerate(monthly_returns):
            balance *= 1.0 + monthly_return
            if index >= warmup_months:
                balance -= withdrawal
                withdrawn += withdrawal
            minimum_balance = min(minimum_balance, balance)
        valid = (
            balance >= initial_capital
            and minimum_balance
            >= initial_capital * minimum_capital_fraction
        )
        return valid, balance, minimum_balance, withdrawn

    lower = 0.0
    upper = initial_capital * 0.05
    baseline_valid, baseline_final, baseline_minimum, _ = simulate(0.0)
    if not baseline_valid:
        return {
            "warmup_months": warmup_months,
            "withdrawal_months": max(
                0, len(monthly_returns) - warmup_months
            ),
            "feasible_without_withdrawals": False,
            "maximum_fixed_monthly_amount": 0.0,
            "total_withdrawn": 0.0,
            "final_balance": baseline_final,
            "minimum_balance": baseline_minimum,
        }
    for _ in range(60):
        midpoint = (lower + upper) / 2.0
        if simulate(midpoint)[0]:
            lower = midpoint
        else:
            upper = midpoint
    _, final_balance, minimum_balance, withdrawn = simulate(lower)
    return {
        "warmup_months": warmup_months,
        "withdrawal_months": max(0, len(monthly_returns) - warmup_months),
        "feasible_without_withdrawals": True,
        "maximum_fixed_monthly_amount": lower,
        "total_withdrawn": withdrawn,
        "final_balance": final_balance,
        "minimum_balance": minimum_balance,
    }
