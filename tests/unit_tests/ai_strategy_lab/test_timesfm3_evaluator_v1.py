import numpy

from octobot.ai_strategy_lab import timesfm3_evaluator_v1 as evaluator


def _paths(origins=20):
    assets = 4
    horizon = 24
    origin = numpy.zeros((origins, assets))
    actual_returns = numpy.linspace(-0.02, 0.03, origins * assets).reshape(
        origins, assets
    )
    actual = numpy.repeat(origin[:, :, None], horizon, axis=2)
    actual += actual_returns[:, :, None] * (
        numpy.arange(1, horizon + 1)[None, None, :] / horizon
    )
    model = actual.copy()
    unchanged = numpy.zeros_like(actual)
    seasonal = numpy.zeros_like(actual)
    ar1 = numpy.zeros_like(actual)
    quantiles = numpy.repeat(model[:, :, :, None], 9, axis=3)
    offsets = numpy.linspace(-0.01, 0.01, 9)
    quantiles += offsets[None, None, None, :]
    return origin, actual, model, quantiles, unchanged, seasonal, ar1


def test_ar1_path_uses_only_supplied_context():
    context = numpy.vstack(
        (
            numpy.linspace(1, 2, 100),
            numpy.linspace(3, 2, 100),
        )
    )
    forecast = evaluator.ar1_path(context, 24)

    assert forecast.shape == (2, 24)
    assert numpy.all(numpy.isfinite(forecast))
    assert forecast[0, -1] > context[0, -1]
    assert forecast[1, -1] < context[1, -1]


def test_perfect_paths_beat_unchanged_baseline():
    values = _paths()
    result = evaluator.predictive_metrics(
        origin_log_prices=values[0],
        actual_log_paths=values[1],
        model_paths=values[2],
        model_quantiles=values[3],
        unchanged_paths=values[4],
        seasonal_paths=values[5],
        ar1_paths=values[6],
    )

    assert result["pooled_terminal_mae_bps"] == 0
    assert result["pooled_mae_skill_vs_unchanged"] == 1
    assert result["q10_q90_coverage"] == 1


def test_economic_translation_is_cost_and_funding_aware():
    origins = 4
    origin = numpy.zeros((origins, 4))
    quantiles = numpy.zeros((origins, 4, 24, 9))
    quantiles[:, 0, -1, :] = 0.01
    quantiles[:, 1, -1, :] = -0.01
    entry = numpy.full((origins, 4), 100.0)
    exit_price = entry.copy()
    exit_price[:, 0] = 102.0
    exit_price[:, 1] = 98.0
    funding = numpy.zeros((origins, 4))
    funding[:, 0] = 0.001
    funding[:, 1] = 0.001

    result = evaluator.economic_metrics(
        origin_log_prices=origin,
        model_quantiles=quantiles,
        entry_prices=entry,
        exit_prices=exit_price,
        funding_sums=funding,
    )

    assert result["by_asset"]["BTC"]["longs"] == origins
    assert result["by_asset"]["ETH"]["shorts"] == origins
    assert result["by_asset"]["SOL"]["trades"] == 0
    assert numpy.all(result["base_trade_returns"][:, 0] > 0)
    assert numpy.all(result["base_trade_returns"][:, 1] > 0)
    assert result["base"]["trades"] == origins * 2
    assert result["stress_3x_cost"]["total_return"] < result["base"]["total_return"]


def test_gates_are_conjunctive():
    predictive = {
        "daily_origins": 1_130,
        "pooled_mae_skill_vs_unchanged": 0.03,
        "q10_q90_coverage": 0.80,
        "direction_accuracy": 0.53,
        "by_asset": {
            asset: {"mae_skill_vs_unchanged": 0.01}
            for asset in ("BTC", "ETH", "SOL", "XRP")
        },
    }
    economic = {
        "base": {
            "trades": 101,
            "sharpe": 0.51,
            "profit_factor": 1.06,
            "maximum_drawdown": 0.19,
        },
        "stress_3x_cost": {"total_return": 0.001},
    }

    passed = evaluator.evaluate_gates(predictive, economic)
    assert passed["all_passed"] is True
    predictive["by_asset"]["XRP"]["mae_skill_vs_unchanged"] = -0.001
    failed = evaluator.evaluate_gates(predictive, economic)
    assert failed["all_passed"] is False
    assert failed["checks"]["every_asset_mae_skill_strictly_positive"] is False
