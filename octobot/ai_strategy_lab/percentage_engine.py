"""Research-only percentage opportunity labels for candlestick charts.

The engine deliberately uses future candles to describe completed historical
opportunities.  Its output is a hindsight diagnostic for chart inspection, not
a live signal, strategy promotion decision, or order authorization.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import typing


LONG = "LONG"
SHORT = "SHORT"
_DIRECTIONS = (LONG, SHORT)


@dataclasses.dataclass(frozen=True)
class PercentageEngineConfig:
    """Frozen parameters for the first percentage-map diagnostic."""

    minimum_profit_pct: float = 1.0
    activation_pct: float = 1.2
    initial_stop_pct: float = 1.0
    horizon_candles: int = 24
    directions: tuple[str, ...] = _DIRECTIONS
    exclude_last_candle: bool = True

    def validate(self) -> None:
        if not math.isfinite(self.minimum_profit_pct) or self.minimum_profit_pct <= 0:
            raise ValueError("minimum profit percent must be finite and positive")
        if not math.isfinite(self.activation_pct) or (
            self.activation_pct <= self.minimum_profit_pct
        ):
            raise ValueError(
                "activation percent must be finite and above minimum profit percent"
            )
        if not math.isfinite(self.initial_stop_pct) or self.initial_stop_pct <= 0:
            raise ValueError("initial stop percent must be finite and positive")
        if self.horizon_candles < 1:
            raise ValueError("horizon candles must be at least one")
        if (
            not self.directions
            or len(set(self.directions)) != len(self.directions)
            or any(direction not in _DIRECTIONS for direction in self.directions)
        ):
            raise ValueError("directions must contain unique LONG and/or SHORT values")


def _as_finite_positive(values: typing.Iterable[typing.Any], name: str) -> list[float]:
    converted = [float(value) for value in values]
    if not converted:
        raise ValueError(f"{name} must not be empty")
    if any(not math.isfinite(value) or value <= 0 for value in converted):
        raise ValueError(f"{name} must contain only finite positive values")
    return converted


def _validate_inputs(
    times: typing.Iterable[typing.Any],
    opens: typing.Iterable[typing.Any],
    highs: typing.Iterable[typing.Any],
    lows: typing.Iterable[typing.Any],
    closes: typing.Iterable[typing.Any],
) -> tuple[list[typing.Any], list[float], list[float], list[float], list[float]]:
    time_values = list(times)
    open_values = _as_finite_positive(opens, "opens")
    high_values = _as_finite_positive(highs, "highs")
    low_values = _as_finite_positive(lows, "lows")
    close_values = _as_finite_positive(closes, "closes")
    lengths = {
        len(time_values),
        len(open_values),
        len(high_values),
        len(low_values),
        len(close_values),
    }
    if len(lengths) != 1:
        raise ValueError("candle arrays must have identical lengths")
    if any(
        low > min(open_, close) or high < max(open_, close) or low > high
        for open_, high, low, close in zip(
            open_values, high_values, low_values, close_values
        )
    ):
        raise ValueError("candle OHLC values are inconsistent")
    return time_values, open_values, high_values, low_values, close_values


def _levels(entry_price: float, direction: str, config: PercentageEngineConfig) -> dict:
    sign = 1 if direction == LONG else -1
    return {
        "initial_stop_price": entry_price
        * (1 - sign * config.initial_stop_pct / 100),
        "activation_price": entry_price * (1 + sign * config.activation_pct / 100),
        "locked_stop_price": entry_price
        * (1 + sign * config.minimum_profit_pct / 100),
    }


def _favorable_and_adverse_pct(
    entry_price: float, high: float, low: float, direction: str
) -> tuple[float, float]:
    if direction == LONG:
        return (
            (high / entry_price - 1) * 100,
            (low / entry_price - 1) * 100,
        )
    return (
        (1 - low / entry_price) * 100,
        (1 - high / entry_price) * 100,
    )


def _gross_return_pct(entry_price: float, exit_price: float, direction: str) -> float:
    if direction == LONG:
        return (exit_price / entry_price - 1) * 100
    return (1 - exit_price / entry_price) * 100


def simulate_trade(
    times: typing.Sequence[typing.Any],
    highs: typing.Sequence[float],
    lows: typing.Sequence[float],
    closes: typing.Sequence[float],
    entry_index: int,
    direction: str,
    last_closed_index: int,
    config: PercentageEngineConfig,
) -> dict:
    """Simulate one historical entry with conservative candle ordering.

    The entry occurs at ``entry_index`` close.  If initial stop and activation
    are both touched in the same candle, initial stop wins.  A newly protected
    stop becomes active from the following candle because OHLC data cannot
    establish the intrabar path after activation.
    """

    if direction not in _DIRECTIONS:
        raise ValueError("unsupported direction")
    if entry_index < 0 or entry_index >= last_closed_index:
        raise ValueError("entry index must precede the last closed candle")

    entry_price = float(closes[entry_index])
    levels = _levels(entry_price, direction, config)
    end_index = min(
        entry_index + config.horizon_candles,
        last_closed_index,
    )
    activation_index = None
    maximum_favorable_excursion = 0.0
    maximum_adverse_excursion = 0.0

    for candle_index in range(entry_index + 1, end_index + 1):
        high = float(highs[candle_index])
        low = float(lows[candle_index])
        favorable, adverse = _favorable_and_adverse_pct(
            entry_price, high, low, direction
        )
        maximum_favorable_excursion = max(maximum_favorable_excursion, favorable)
        maximum_adverse_excursion = min(maximum_adverse_excursion, adverse)

        if activation_index is None:
            initial_stop_touched = (
                low <= levels["initial_stop_price"]
                if direction == LONG
                else high >= levels["initial_stop_price"]
            )
            activation_touched = (
                high >= levels["activation_price"]
                if direction == LONG
                else low <= levels["activation_price"]
            )
            if initial_stop_touched:
                exit_price = levels["initial_stop_price"]
                return {
                    "direction": direction,
                    "entry_index": entry_index,
                    "entry_time": times[entry_index],
                    "entry_price": entry_price,
                    "activation_index": None,
                    "activation_time": None,
                    "activation_price": levels["activation_price"],
                    "exit_index": candle_index,
                    "exit_time": times[candle_index],
                    "exit_price": exit_price,
                    "exit_reason": "initial_stop",
                    "target_reached": False,
                    "gross_return_pct": _gross_return_pct(
                        entry_price, exit_price, direction
                    ),
                    "maximum_favorable_excursion_pct": maximum_favorable_excursion,
                    "maximum_adverse_excursion_pct": maximum_adverse_excursion,
                    **levels,
                }
            if activation_touched:
                activation_index = candle_index
                continue

        else:
            locked_stop_touched = (
                low <= levels["locked_stop_price"]
                if direction == LONG
                else high >= levels["locked_stop_price"]
            )
            if locked_stop_touched:
                exit_price = levels["locked_stop_price"]
                return {
                    "direction": direction,
                    "entry_index": entry_index,
                    "entry_time": times[entry_index],
                    "entry_price": entry_price,
                    "activation_index": activation_index,
                    "activation_time": times[activation_index],
                    "activation_price": levels["activation_price"],
                    "exit_index": candle_index,
                    "exit_time": times[candle_index],
                    "exit_price": exit_price,
                    "exit_reason": "profit_lock",
                    "target_reached": True,
                    "gross_return_pct": _gross_return_pct(
                        entry_price, exit_price, direction
                    ),
                    "maximum_favorable_excursion_pct": maximum_favorable_excursion,
                    "maximum_adverse_excursion_pct": maximum_adverse_excursion,
                    **levels,
                }

    exit_price = float(closes[end_index])
    return {
        "direction": direction,
        "entry_index": entry_index,
        "entry_time": times[entry_index],
        "entry_price": entry_price,
        "activation_index": activation_index,
        "activation_time": (
            times[activation_index] if activation_index is not None else None
        ),
        "activation_price": levels["activation_price"],
        "exit_index": end_index,
        "exit_time": times[end_index],
        "exit_price": exit_price,
        "exit_reason": (
            "horizon_after_lock" if activation_index is not None else "horizon"
        ),
        "target_reached": activation_index is not None,
        "gross_return_pct": _gross_return_pct(entry_price, exit_price, direction),
        "maximum_favorable_excursion_pct": maximum_favorable_excursion,
        "maximum_adverse_excursion_pct": maximum_adverse_excursion,
        **levels,
    }


def _select_non_overlapping_maximum_compound(candidates: list[dict]) -> list[dict]:
    """Select the maximum-compounded non-overlapping historical sequence."""

    if not candidates:
        return []
    ordered = sorted(
        candidates,
        key=lambda trade: (
            trade["exit_index"],
            trade["entry_index"],
            trade["direction"],
        ),
    )
    exit_indexes = [trade["exit_index"] for trade in ordered]
    previous = [
        bisect.bisect_left(exit_indexes, trade["entry_index"]) - 1
        for trade in ordered
    ]
    best_scores = [0.0] * (len(ordered) + 1)
    selected_current = [False] * len(ordered)

    for index, trade in enumerate(ordered, start=1):
        compound_score = math.log1p(trade["gross_return_pct"] / 100)
        include_score = compound_score + best_scores[previous[index - 1] + 1]
        exclude_score = best_scores[index - 1]
        if include_score > exclude_score + 1e-15:
            best_scores[index] = include_score
            selected_current[index - 1] = True
        else:
            best_scores[index] = exclude_score

    selected: list[dict] = []
    index = len(ordered)
    while index > 0:
        trade_index = index - 1
        compound_score = math.log1p(
            ordered[trade_index]["gross_return_pct"] / 100
        )
        include_score = (
            compound_score + best_scores[previous[trade_index] + 1]
        )
        if (
            selected_current[trade_index]
            and include_score > best_scores[index - 1] + 1e-15
        ):
            selected.append(ordered[trade_index])
            index = previous[trade_index] + 1
        else:
            index -= 1
    selected.reverse()
    return selected


def analyze_percentage_opportunities(
    *,
    times: typing.Iterable[typing.Any],
    opens: typing.Iterable[typing.Any],
    highs: typing.Iterable[typing.Any],
    lows: typing.Iterable[typing.Any],
    closes: typing.Iterable[typing.Any],
    config: PercentageEngineConfig | None = None,
) -> dict:
    """Create a hindsight percentage map from completed candle paths."""

    selected_config = config or PercentageEngineConfig()
    selected_config.validate()
    time_values, _, high_values, low_values, close_values = _validate_inputs(
        times, opens, highs, lows, closes
    )
    last_closed_index = len(time_values) - (
        2 if selected_config.exclude_last_candle else 1
    )
    if last_closed_index < 1:
        raise ValueError("at least two closed candles are required")

    outcomes: list[dict] = []
    for entry_index in range(last_closed_index):
        for direction in selected_config.directions:
            outcome = simulate_trade(
                time_values,
                high_values,
                low_values,
                close_values,
                entry_index,
                direction,
                last_closed_index,
                selected_config,
            )
            available_future_candles = last_closed_index - entry_index
            outcome.update(
                {
                    "maturity_status": (
                        "confirmed"
                        if available_future_candles
                        >= selected_config.horizon_candles
                        else "provisional"
                    ),
                    "available_future_candles": available_future_candles,
                    "required_future_candles": (
                        selected_config.horizon_candles
                    ),
                    "future_candles_missing": max(
                        0,
                        selected_config.horizon_candles
                        - available_future_candles,
                    ),
                }
            )
            outcomes.append(outcome)

    reached = [outcome for outcome in outcomes if outcome["target_reached"]]
    confirmed_outcomes = [
        outcome
        for outcome in outcomes
        if outcome["maturity_status"] == "confirmed"
    ]
    confirmed_reached = [
        outcome
        for outcome in confirmed_outcomes
        if outcome["target_reached"]
    ]
    profitable_candidates = [
        outcome
        for outcome in reached
        if outcome["gross_return_pct"]
        >= selected_config.minimum_profit_pct - 1e-12
    ]
    selected = _select_non_overlapping_maximum_compound(profitable_candidates)
    compound_multiplier = math.prod(
        1 + trade["gross_return_pct"] / 100 for trade in selected
    )
    long_count = sum(trade["direction"] == LONG for trade in selected)
    short_count = sum(trade["direction"] == SHORT for trade in selected)
    confirmed_selected_count = sum(
        trade["maturity_status"] == "confirmed" for trade in selected
    )
    provisional_selected_count = len(selected) - confirmed_selected_count
    last_mature_entry_index = (
        last_closed_index - selected_config.horizon_candles
    )
    provisional_start_index = max(0, last_mature_entry_index + 1)

    return {
        "schema_version": 2,
        "mode": "hindsight_percentage_research_only",
        "research_only": True,
        "uses_future_outcomes": True,
        "orders_authorized": False,
        "automatic_promotion": False,
        "config": dataclasses.asdict(selected_config),
        "summary": {
            "closed_candles": last_closed_index + 1,
            "evaluated_setups": len(outcomes),
            "confirmed_evaluated_setups": len(confirmed_outcomes),
            "provisional_evaluated_setups": (
                len(outcomes) - len(confirmed_outcomes)
            ),
            "target_before_stop": len(reached),
            "historical_hit_rate_pct": (
                len(confirmed_reached) * 100 / len(confirmed_outcomes)
                if confirmed_outcomes
                else 0
            ),
            "provisional_inclusive_hit_rate_pct": (
                len(reached) * 100 / len(outcomes) if outcomes else 0
            ),
            "profitable_candidates": len(profitable_candidates),
            "selected_non_overlapping_trades": len(selected),
            "confirmed_selected_trades": confirmed_selected_count,
            "provisional_selected_trades": provisional_selected_count,
            "selected_long_trades": long_count,
            "selected_short_trades": short_count,
            "maximum_hindsight_compounded_gross_return_pct": (
                compound_multiplier - 1
            )
            * 100,
        },
        "maturity": {
            "full_horizon_candles": selected_config.horizon_candles,
            "last_closed_index": last_closed_index,
            "last_closed_time": time_values[last_closed_index],
            "last_mature_entry_index": (
                last_mature_entry_index
                if last_mature_entry_index >= 0
                else None
            ),
            "last_mature_entry_time": (
                time_values[last_mature_entry_index]
                if last_mature_entry_index >= 0
                else None
            ),
            "provisional_start_index": provisional_start_index,
            "provisional_start_time": time_values[provisional_start_index],
            "provisional_entry_candles": (
                last_closed_index - provisional_start_index
            ),
        },
        "trades": selected,
        "warning": (
            "The map is optimized with future candles and is not a live signal, "
            "backtest result, profitability estimate, or order authorization. "
            "Entries in the right-edge maturity zone do not yet have the full "
            "future horizon and can change as new candles close."
        ),
    }
