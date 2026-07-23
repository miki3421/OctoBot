"""Offline, reproducible research tools for guarded trading strategies.

This package is deliberately independent from the live OctoBot runtime.  It
only reads historical collector files and writes research artifacts.  Nothing
in here can create an exchange order.
"""

from octobot.ai_strategy_lab.dataset import (
    BarrierConfig,
    DatasetBuildConfig,
    build_dataset,
    load_dataset,
    save_dataset,
)

__all__ = [
    "BarrierConfig",
    "DatasetBuildConfig",
    "build_dataset",
    "load_dataset",
    "save_dataset",
]
