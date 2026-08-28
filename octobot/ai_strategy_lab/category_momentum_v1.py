"""Frozen category-momentum V1 protocol.

This initial module only persists the result-free protocol.  It has no exchange
client, cannot read economic outcomes and cannot create shadow, paper or real
orders.  Source acquisition and evaluation are separate post-freeze changes.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import typing

from octobot.ai_strategy_lab import cointegration_pairs_v1 as common


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "crypto_perpetual_category_momentum_v1"
PREREGISTRATION_DATE = "2026-08-28"
PAPER_MANUSCRIPT_SHA256 = (
    "759a036f1f0c921d335e2e2567b2d8e5ce3088c5e16d4ed5bf98875983d74521"
)
COINGECKO_CATEGORY_IDS = (
    "artificial-intelligence",
    "arbitrum-ecosystem",
    "avalanche-ecosystem",
    "binance-launchpad",
    "binance-launchpool",
    "binance-smart-chain",
    "bitcoin-ecosystem",
    "cosmos-ecosystem",
    "decentralized-finance-defi",
    "depin",
    "ethereum-ecosystem",
    "gaming",
    "injective-ecosystem",
    "interoperability",
    "internet-of-things-iot",
    "layer-1",
    "layer-2",
    "media",
    "meme-token",
    "metaverse",
    "non-fungible-tokens-nft",
    "optimism-ecosystem",
    "dot-ecosystem",
    "polygon-ecosystem",
    "privacy-coins",
    "real-world-assets-rwa",
    "smart-contract-platform",
    "solana-ecosystem",
    "storage",
    "zero-knowledge-zk",
)
UNIVERSE_MAX_ASSETS = 120
MINIMUM_LISTING_AGE_DAYS = 180
LIQUIDITY_LOOKBACK_DAYS = 28
MINIMUM_CONTIGUOUS_HISTORY_DAYS = 90
FORMATION_DAYS = 7
HOLDING_DAYS = 1
MINIMUM_CATEGORY_ASSETS = 3
MAXIMUM_CATEGORY_OVERLAP = 0.70
MINIMUM_REPRESENTATIVE_CATEGORIES = 6
CATEGORY_SELECTION_DENOMINATOR = 6
MAXIMUM_ASSET_CATEGORY_WEIGHT = 0.30
SIDE_GROSS_EXPOSURE = 0.40
FEE_PER_TURNOVER = 0.0006
SLIPPAGE_PER_TURNOVER = 0.0002
STRESS_COST_MULTIPLIER = 3.0
UTC = datetime.timezone.utc
DEVELOPMENT_START = datetime.datetime(2022, 7, 1, tzinfo=UTC)
DEVELOPMENT_END = datetime.datetime(2025, 1, 1, tzinfo=UTC)
CONFIRMATION_START = DEVELOPMENT_END
CONFIRMATION_END = datetime.datetime(2026, 1, 1, tzinfo=UTC)
LOCKED_START = CONFIRMATION_END
LOCKED_END = datetime.datetime(2026, 7, 1, tzinfo=UTC)
DEVELOPMENT_FOLDS = (
    (
        datetime.datetime(2022, 7, 1, tzinfo=UTC),
        datetime.datetime(2023, 1, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2023, 1, 1, tzinfo=UTC),
        datetime.datetime(2023, 7, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2023, 7, 1, tzinfo=UTC),
        datetime.datetime(2024, 1, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2024, 1, 1, tzinfo=UTC),
        datetime.datetime(2024, 7, 1, tzinfo=UTC),
    ),
    (
        datetime.datetime(2024, 7, 1, tzinfo=UTC),
        datetime.datetime(2025, 1, 1, tzinfo=UTC),
    ),
)
FORWARD_START_UTC = "2026-09-01T00:00:00+00:00"


def frozen_protocol() -> dict:
    """Return the single immutable, result-free Category Momentum V1 plan."""

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "preregistered_on": PREREGISTRATION_DATE,
        "status": "result_free_protocol_before_new_price_outcomes",
        "research_only": True,
        "public_data_only": True,
        "credentials_used": False,
        "orders_authorized": False,
        "paper_orders_authorized": False,
        "automatic_promotion": False,
        "external_hypothesis": {
            "title": "Anatomy of Cryptocurrency Perpetual Futures Returns",
            "authors": ["Yi Cao", "Jia Zhai", "Pengfei Luo"],
            "institutional_repository": (
                "https://era.ed.ac.uk/bitstream/handle/1842/43608/"
                "Luo2025.pdf?isAllowed=y&sequence=1"
            ),
            "thesis_doi": "10.7488/era/6141",
            "manuscript_sha256": PAPER_MANUSCRIPT_SHA256,
            "chapter": 4,
            "tables": [42, 43],
            "source_formation_days": FORMATION_DAYS,
            "source_holding_days": HOLDING_DAYS,
            "source_mechanism": (
                "serial covariation among large liquid coins within categories"
            ),
        },
        "hypothesis": {
            "name": "liquid_category_return_continuation",
            "statement": (
                "categories with the highest completed seven-day return "
                "outperform categories with the lowest return over the next day"
            ),
            "economically_distinct_from": [
                "individual-asset dual momentum V13/V18",
                "basis and basis momentum",
                "signed price-volume flow",
                "funding carry",
                "directional order-book models",
            ],
            "one_configuration_only": True,
            "opposite_direction_tested": False,
            "long_only_variant_allowed": False,
        },
        "taxonomy_snapshot": {
            "provider": "CoinGecko public API",
            "category_list_endpoint": "/api/v3/coins/categories/list",
            "membership_endpoint": "/api/v3/coins/markets",
            "membership_order": "market_cap_desc",
            "membership_page": 1,
            "membership_maximum_coins": 250,
            "category_ids": list(COINGECKO_CATEGORY_IDS),
            "category_count": len(COINGECKO_CATEGORY_IDS),
            "membership_frozen_for_historical_and_forward": True,
            "mapping": (
                "normalized Binance base symbol; highest snapshot market cap "
                "wins collisions; all collisions and aliases are audited"
            ),
            "historical_taxonomy_is_point_in_time": False,
        },
        "universe_snapshot": {
            "venue": "Binance USD-M",
            "instrument": "USDT linear perpetual",
            "status": "TRADING at source freeze",
            "minimum_listing_age_days": MINIMUM_LISTING_AGE_DAYS,
            "liquidity_metric": (
                "median daily quote volume over 28 completed UTC days"
            ),
            "liquidity_lookback_days": LIQUIDITY_LOOKBACK_DAYS,
            "maximum_assets": UNIVERSE_MAX_ASSETS,
            "ranking_tie_break": "symbol ascending",
            "excluded": [
                "stablecoin bases",
                "BTCDOM index",
                "leveraged tokens",
                "ambiguous or unmapped bases",
            ],
            "universe_frozen_for_forward": True,
            "minimum_contiguous_history_days": (
                MINIMUM_CONTIGUOUS_HISTORY_DAYS
            ),
        },
        "signal": {
            "decision_boundary": "00:00 UTC after completed daily close",
            "formation_days": FORMATION_DAYS,
            "holding_days": HOLDING_DAYS,
            "future_data_used": False,
            "category_minimum_assets": MINIMUM_CATEGORY_ASSETS,
            "within_category_weight": (
                "previous 28 completed days quote volume proportional"
            ),
            "maximum_asset_category_weight": MAXIMUM_ASSET_CATEGORY_WEIGHT,
            "weight_cap_redistribution": "iterative deterministic water fill",
            "category_overlap_measure": (
                "intersection divided by smaller category membership"
            ),
            "maximum_category_overlap": MAXIMUM_CATEGORY_OVERLAP,
            "category_acceptance_order": (
                "member count descending then category id ascending"
            ),
            "minimum_representative_categories": (
                MINIMUM_REPRESENTATIVE_CATEGORIES
            ),
            "categories_per_side": (
                "max(1, floor(representative_category_count / 6))"
            ),
            "category_selection_denominator": CATEGORY_SELECTION_DENOMINATOR,
            "long": "highest seven-day category returns",
            "short": "lowest seven-day category returns",
            "category_weighting": "equal within each side",
            "coin_overlap": "aggregate and net before costs",
            "side_gross_exposure": SIDE_GROSS_EXPOSURE,
            "maximum_portfolio_gross": 2.0 * SIDE_GROSS_EXPOSURE,
            "rebalance": "daily",
            "overlapping_vintages": False,
            "stops_or_take_profit": False,
            "regime_filter": False,
            "volatility_target": False,
            "model_fitted": False,
            "book_or_basis_features": False,
        },
        "data_quality_policy": {
            "completed_utc_days_only": True,
            "interpolation_or_forward_fill": False,
            "return_across_gap": False,
            "signal_after_gap": (
                "flat until 90 contiguous daily closes and all lookbacks exist"
            ),
            "source_responses_content_addressed": True,
            "raw_inputs_unique_and_preserved": True,
            "daily_price_source": "Binance public USD-M klines",
            "funding_source": "Binance public funding history",
        },
        "economics": {
            "traded_instrument": "perpetual only",
            "price_pnl": "next completed daily close-to-close return",
            "funding_pnl": "actual signed settlements while target is active",
            "fee_per_turnover": FEE_PER_TURNOVER,
            "slippage_per_turnover": SLIPPAGE_PER_TURNOVER,
            "stress_cost_multiplier": STRESS_COST_MULTIPLIER,
            "cost_on_netted_weight_change": True,
            "period_opened_and_closed_flat": True,
            "maker_fill_assumptions": False,
            "execution_v2_cost_reduction_in_historical_gate": False,
        },
        "validation": {
            "all_historical_periods_status": (
                "diagnostic_reuse_current_taxonomy_and_survivor_universe"
            ),
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "development_folds": [
                [start.isoformat(), end.isoformat()]
                for start, end in DEVELOPMENT_FOLDS
            ],
            "confirmation": [
                CONFIRMATION_START.isoformat(),
                CONFIRMATION_END.isoformat(),
            ],
            "confirmation_status": "sealed_until_development_passes",
            "locked_final_test": [
                LOCKED_START.isoformat(),
                LOCKED_END.isoformat(),
            ],
            "locked_status": "sealed_until_confirmation_passes",
            "historical_pass_cannot_promote": True,
        },
        "development_gate": {
            "minimum_outcomes": 800,
            "minimum_invested_days": 300,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.08,
            "minimum_sharpe": 1.00,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.55,
            "minimum_positive_folds": 4,
            "required_folds": len(DEVELOPMENT_FOLDS),
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.30,
            "maximum_symbol_absolute_contribution_share": 0.35,
            "minimum_positive_leave_one_symbol_out_ratio": 0.80,
            "minimum_positive_leave_one_category_out_ratio": 0.80,
        },
        "confirmation_gate": {
            "minimum_outcomes": 300,
            "minimum_invested_days": 100,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.75,
            "minimum_profit_factor": 1.05,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "minimum_positive_quarters": 3,
            "required_quarters": 4,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.30,
        },
        "locked_gate": {
            "minimum_outcomes": 150,
            "minimum_invested_days": 50,
            "positive_total_return": True,
            "stress_total_return_positive": True,
            "minimum_annualized_return": 0.04,
            "minimum_sharpe": 0.50,
            "minimum_profit_factor": 1.05,
            "maximum_drawdown": 0.15,
            "minimum_positive_month_ratio": 0.50,
            "both_side_contributions_nonnegative": True,
            "maximum_absolute_market_beta": 0.30,
        },
        "forward_gate": {
            "start_utc": FORWARD_START_UTC,
            "minimum_calendar_days": 180,
            "minimum_observed_days": 165,
            "prediction_deadline_minutes": 15,
            "outcome_delay_days": 1,
            "append_only": True,
            "no_refit": True,
            "same_taxonomy_universe_signal_and_costs": True,
            "required_before_shadow_or_paper": True,
        },
        "multiple_testing_disclosure": (
            "one externally selected 7-day formation, 1-day holding and "
            "direction; no local lookback, threshold or side search"
        ),
        "promotion_consequence": (
            "three historical passes authorize only an orderless forward "
            "observer; no shadow target, paper or real order"
        ),
        "results": None,
    }


def write_or_verify_protocol(
    path_value: typing.Union[str, pathlib.Path],
) -> dict:
    """Create the protocol atomically, or verify an existing immutable copy."""

    path = pathlib.Path(path_value).resolve()
    protocol = frozen_protocol()
    payload = {**protocol, "protocol_sha256": common._json_hash(protocol)}
    if path.is_file():
        persisted = json.loads(path.read_text(encoding="utf-8"))
        if persisted != payload:
            raise ValueError("persisted Category Momentum V1 protocol differs")
        return persisted
    common._atomic_json(path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    protocol = write_or_verify_protocol(args.output)
    print(json.dumps(protocol, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
