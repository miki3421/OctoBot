"""NumPy-only baselines and leakage-resistant evaluation for the AI lab."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import math
import pathlib
import typing

import numpy

from octobot.ai_strategy_lab import dataset as dataset_module


MODEL_SCHEMA_VERSION = 1


@dataclasses.dataclass(frozen=True)
class LogisticConfig:
    epochs: int = 12
    batch_size: int = 8192
    learning_rate: float = 0.01
    l2: float = 0.001
    seed: int = 42

    def validate(self) -> None:
        if self.epochs < 1 or self.batch_size < 1:
            raise ValueError("epochs and batch_size must be positive")
        if self.learning_rate <= 0 or self.l2 < 0:
            raise ValueError("invalid optimizer parameters")


@dataclasses.dataclass(frozen=True)
class ValidationConfig:
    folds: int = 4
    initial_train_fraction: float = 0.50
    locked_test_fraction: float = 0.20
    inner_validation_fraction: float = 0.20
    embargo_seconds: int = 4 * 3600
    probability_thresholds: tuple[float, ...] = (
        0.35,
        0.40,
        0.45,
        0.50,
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
    )
    probability_quantiles: tuple[float, ...] = (
        0.90,
        0.95,
        0.975,
        0.99,
        0.995,
    )
    minimum_validation_trades: int = 20
    position_fraction: float = 0.10
    training_stride: int = 4

    def validate(self) -> None:
        if self.folds < 2:
            raise ValueError("folds must be at least two")
        if not 0.2 <= self.initial_train_fraction < 0.9:
            raise ValueError("initial_train_fraction is invalid")
        if not 0.05 <= self.locked_test_fraction < 0.5:
            raise ValueError("locked_test_fraction is invalid")
        if not 0.1 <= self.inner_validation_fraction < 0.5:
            raise ValueError("inner_validation_fraction is invalid")
        if self.embargo_seconds < 0:
            raise ValueError("embargo_seconds cannot be negative")
        if not self.probability_thresholds or any(
            not 0 < threshold < 1
            for threshold in self.probability_thresholds
        ):
            raise ValueError("probability thresholds are invalid")
        if not self.probability_quantiles or any(
            not 0 < quantile < 1 for quantile in self.probability_quantiles
        ):
            raise ValueError("probability quantiles are invalid")
        if not 0 < self.position_fraction <= 1:
            raise ValueError("position_fraction must be in (0, 1]")
        if self.training_stride < 1:
            raise ValueError("training_stride must be at least one")


@dataclasses.dataclass(frozen=True)
class BoostingConfig:
    trees: int = 32
    max_depth: int = 2
    bins: int = 16
    learning_rate: float = 0.06
    l2: float = 2.0
    minimum_leaf_rows: int = 120
    minimum_gain: float = 0.001
    feature_fraction: float = 0.75
    seed: int = 42

    def validate(self) -> None:
        if self.trees < 1 or self.max_depth < 1:
            raise ValueError("trees and max_depth must be positive")
        if self.bins < 4 or self.bins > 255:
            raise ValueError("bins must be between 4 and 255")
        if self.learning_rate <= 0 or self.l2 < 0:
            raise ValueError("invalid boosting learning parameters")
        if self.minimum_leaf_rows < 2 or self.minimum_gain < 0:
            raise ValueError("invalid boosting split constraints")
        if not 0 < self.feature_fraction <= 1:
            raise ValueError("feature_fraction must be in (0, 1]")


@dataclasses.dataclass(frozen=True)
class TemporalSplit:
    train_indices: numpy.ndarray
    test_indices: numpy.ndarray
    train_end_timestamp: int
    test_start_timestamp: int
    test_end_timestamp: int


@dataclasses.dataclass
class NumpyLogisticModel:
    feature_names: tuple[str, ...]
    mean: numpy.ndarray
    scale: numpy.ndarray
    weights: numpy.ndarray
    intercept: float
    config: LogisticConfig

    @classmethod
    def fit(
        cls,
        features: numpy.ndarray,
        labels: numpy.ndarray,
        feature_names: tuple[str, ...],
        config: LogisticConfig,
    ) -> "NumpyLogisticModel":
        config.validate()
        if len(features) != len(labels) or not len(labels):
            raise ValueError("training data is empty or misaligned")
        labels = labels.astype(numpy.float64)
        if len(numpy.unique(labels)) < 2:
            raise ValueError("training labels require both classes")

        mean = numpy.mean(features, axis=0, dtype=numpy.float64)
        scale = numpy.std(features, axis=0, dtype=numpy.float64)
        scale[scale < 1e-9] = 1.0
        standardized = numpy.clip(
            (features.astype(numpy.float64) - mean) / scale,
            -12.0,
            12.0,
        ).astype(numpy.float32)

        weights = numpy.zeros(standardized.shape[1], dtype=numpy.float64)
        class_probability = min(1 - 1e-6, max(1e-6, float(numpy.mean(labels))))
        intercept = math.log(class_probability / (1.0 - class_probability))
        first_moment = numpy.zeros_like(weights)
        second_moment = numpy.zeros_like(weights)
        intercept_first_moment = 0.0
        intercept_second_moment = 0.0
        beta_one = 0.9
        beta_two = 0.999
        epsilon = 1e-8
        step = 0
        random = numpy.random.RandomState(config.seed)

        for _ in range(config.epochs):
            permutation = random.permutation(len(labels))
            for start in range(0, len(labels), config.batch_size):
                batch_indices = permutation[start : start + config.batch_size]
                batch_features = standardized[batch_indices].astype(
                    numpy.float64, copy=False
                )
                batch_labels = labels[batch_indices]
                logits = batch_features @ weights + intercept
                probabilities = _sigmoid(logits)
                residual = probabilities - batch_labels
                weight_gradient = (
                    batch_features.T @ residual / len(batch_indices)
                    + config.l2 * weights
                )
                intercept_gradient = float(numpy.mean(residual))

                step += 1
                first_moment = (
                    beta_one * first_moment
                    + (1.0 - beta_one) * weight_gradient
                )
                second_moment = (
                    beta_two * second_moment
                    + (1.0 - beta_two) * weight_gradient * weight_gradient
                )
                intercept_first_moment = (
                    beta_one * intercept_first_moment
                    + (1.0 - beta_one) * intercept_gradient
                )
                intercept_second_moment = (
                    beta_two * intercept_second_moment
                    + (1.0 - beta_two) * intercept_gradient * intercept_gradient
                )
                corrected_first = first_moment / (1.0 - beta_one**step)
                corrected_second = second_moment / (1.0 - beta_two**step)
                corrected_intercept_first = intercept_first_moment / (
                    1.0 - beta_one**step
                )
                corrected_intercept_second = intercept_second_moment / (
                    1.0 - beta_two**step
                )
                weights -= config.learning_rate * corrected_first / (
                    numpy.sqrt(corrected_second) + epsilon
                )
                intercept -= (
                    config.learning_rate
                    * corrected_intercept_first
                    / (math.sqrt(corrected_intercept_second) + epsilon)
                )

        return cls(
            feature_names=feature_names,
            mean=mean,
            scale=scale,
            weights=weights,
            intercept=intercept,
            config=config,
        )

    def predict_proba(self, features: numpy.ndarray) -> numpy.ndarray:
        if features.shape[1] != len(self.feature_names):
            raise ValueError("feature matrix does not match the model schema")
        standardized = numpy.clip(
            (features.astype(numpy.float64) - self.mean) / self.scale,
            -12.0,
            12.0,
        )
        return _sigmoid(standardized @ self.weights + self.intercept)

    def save(self, path_value: typing.Union[str, pathlib.Path]) -> dict:
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy.savez_compressed(
            path,
            schema_version=numpy.asarray([MODEL_SCHEMA_VERSION]),
            feature_names=numpy.asarray(self.feature_names),
            mean=self.mean,
            scale=self.scale,
            weights=self.weights,
            intercept=numpy.asarray([self.intercept]),
            config=numpy.asarray([json.dumps(dataclasses.asdict(self.config))]),
        )
        return {
            "path": str(path),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }

    @classmethod
    def load(cls, path_value: typing.Union[str, pathlib.Path]) -> "NumpyLogisticModel":
        path = pathlib.Path(path_value).resolve()
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != MODEL_SCHEMA_VERSION:
                raise ValueError("unsupported model schema")
            return cls(
                feature_names=tuple(str(value) for value in values["feature_names"]),
                mean=values["mean"],
                scale=values["scale"],
                weights=values["weights"],
                intercept=float(values["intercept"][0]),
                config=LogisticConfig(**json.loads(str(values["config"][0]))),
            )


@dataclasses.dataclass
class NumpyGradientBoostingModel:
    """Small histogram-boosted trees with portable NumPy inference."""

    feature_names: tuple[str, ...]
    initial_score: float
    trees: list[list[dict]]
    config: BoostingConfig

    @classmethod
    def fit(
        cls,
        features: numpy.ndarray,
        labels: numpy.ndarray,
        feature_names: tuple[str, ...],
        config: BoostingConfig,
    ) -> "NumpyGradientBoostingModel":
        config.validate()
        if len(features) != len(labels) or not len(labels):
            raise ValueError("training data is empty or misaligned")
        labels = labels.astype(numpy.float64)
        if len(numpy.unique(labels)) < 2:
            raise ValueError("training labels require both classes")
        features = features.astype(numpy.float32, copy=False)
        quantiles = numpy.linspace(0.0, 1.0, config.bins + 1)[1:-1]
        thresholds = [
            numpy.unique(numpy.quantile(features[:, index], quantiles))
            for index in range(features.shape[1])
        ]
        binned = numpy.empty(features.shape, dtype=numpy.uint8)
        for index, feature_thresholds in enumerate(thresholds):
            binned[:, index] = numpy.searchsorted(
                feature_thresholds,
                features[:, index],
                side="right",
            ).astype(numpy.uint8)

        class_probability = min(1 - 1e-6, max(1e-6, float(numpy.mean(labels))))
        initial_score = math.log(class_probability / (1.0 - class_probability))
        logits = numpy.full(len(labels), initial_score, dtype=numpy.float64)
        trees: list[list[dict]] = []
        random = numpy.random.RandomState(config.seed)
        feature_count = max(
            1, int(math.ceil(features.shape[1] * config.feature_fraction))
        )

        for _ in range(config.trees):
            probabilities = _sigmoid(logits)
            gradients = labels - probabilities
            hessians = numpy.maximum(
                probabilities * (1.0 - probabilities), 1e-6
            )
            selected_features = numpy.sort(
                random.choice(
                    features.shape[1],
                    size=feature_count,
                    replace=False,
                )
            )
            nodes: list[dict] = []
            leaf_assignments: list[tuple[numpy.ndarray, float]] = []
            _build_boosting_tree(
                binned,
                thresholds,
                gradients,
                hessians,
                numpy.arange(len(labels), dtype=numpy.int64),
                depth=0,
                selected_features=selected_features,
                config=config,
                nodes=nodes,
                leaf_assignments=leaf_assignments,
            )
            for indices, value in leaf_assignments:
                logits[indices] += config.learning_rate * value
            trees.append(nodes)
        return cls(
            feature_names=feature_names,
            initial_score=initial_score,
            trees=trees,
            config=config,
        )

    def predict_proba(self, features: numpy.ndarray) -> numpy.ndarray:
        if features.shape[1] != len(self.feature_names):
            raise ValueError("feature matrix does not match the model schema")
        logits = numpy.full(len(features), self.initial_score, dtype=numpy.float64)
        for tree in self.trees:
            logits += self.config.learning_rate * _predict_tree(tree, features)
        return _sigmoid(logits)

    def save(self, path_value: typing.Union[str, pathlib.Path]) -> dict:
        path = pathlib.Path(path_value).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy.savez_compressed(
            path,
            schema_version=numpy.asarray([MODEL_SCHEMA_VERSION]),
            model_type=numpy.asarray(["numpy_gradient_boosting"]),
            feature_names=numpy.asarray(self.feature_names),
            initial_score=numpy.asarray([self.initial_score]),
            trees=numpy.asarray([json.dumps(self.trees, sort_keys=True)]),
            config=numpy.asarray([json.dumps(dataclasses.asdict(self.config))]),
        )
        return {
            "path": str(path),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }

    @classmethod
    def load(
        cls, path_value: typing.Union[str, pathlib.Path]
    ) -> "NumpyGradientBoostingModel":
        path = pathlib.Path(path_value).resolve()
        with numpy.load(path, allow_pickle=False) as values:
            if int(values["schema_version"][0]) != MODEL_SCHEMA_VERSION:
                raise ValueError("unsupported model schema")
            return cls(
                feature_names=tuple(str(value) for value in values["feature_names"]),
                initial_score=float(values["initial_score"][0]),
                trees=json.loads(str(values["trees"][0])),
                config=BoostingConfig(**json.loads(str(values["config"][0]))),
            )


def _build_boosting_tree(
    binned: numpy.ndarray,
    thresholds: list[numpy.ndarray],
    gradients: numpy.ndarray,
    hessians: numpy.ndarray,
    indices: numpy.ndarray,
    *,
    depth: int,
    selected_features: numpy.ndarray,
    config: BoostingConfig,
    nodes: list[dict],
    leaf_assignments: list[tuple[numpy.ndarray, float]],
) -> int:
    gradient_sum = float(numpy.sum(gradients[indices]))
    hessian_sum = float(numpy.sum(hessians[indices]))
    leaf_value = gradient_sum / (hessian_sum + config.l2)
    node_index = len(nodes)
    nodes.append(
        {
            "feature": -1,
            "threshold": 0.0,
            "left": -1,
            "right": -1,
            "value": float(numpy.clip(leaf_value, -3.0, 3.0)),
        }
    )
    if (
        depth >= config.max_depth
        or len(indices) < 2 * config.minimum_leaf_rows
    ):
        leaf_assignments.append((indices, nodes[node_index]["value"]))
        return node_index

    best_gain = config.minimum_gain
    best_feature = -1
    best_bin = -1
    parent_score = gradient_sum * gradient_sum / (hessian_sum + config.l2)
    for feature in selected_features:
        feature_bins = binned[indices, feature]
        bin_count = len(thresholds[int(feature)]) + 1
        counts = numpy.bincount(feature_bins, minlength=bin_count)
        gradient_bins = numpy.bincount(
            feature_bins,
            weights=gradients[indices],
            minlength=bin_count,
        )
        hessian_bins = numpy.bincount(
            feature_bins,
            weights=hessians[indices],
            minlength=bin_count,
        )
        left_counts = numpy.cumsum(counts)[:-1]
        right_counts = len(indices) - left_counts
        valid = (
            (left_counts >= config.minimum_leaf_rows)
            & (right_counts >= config.minimum_leaf_rows)
        )
        if not numpy.any(valid):
            continue
        left_gradients = numpy.cumsum(gradient_bins)[:-1]
        left_hessians = numpy.cumsum(hessian_bins)[:-1]
        right_gradients = gradient_sum - left_gradients
        right_hessians = hessian_sum - left_hessians
        gains = 0.5 * (
            left_gradients * left_gradients / (left_hessians + config.l2)
            + right_gradients * right_gradients / (right_hessians + config.l2)
            - parent_score
        )
        gains[~valid] = -numpy.inf
        split_bin = int(numpy.argmax(gains))
        gain = float(gains[split_bin])
        if gain > best_gain:
            best_gain = gain
            best_feature = int(feature)
            best_bin = split_bin

    if best_feature < 0:
        leaf_assignments.append((indices, nodes[node_index]["value"]))
        return node_index

    left_mask = binned[indices, best_feature] <= best_bin
    left_indices = indices[left_mask]
    right_indices = indices[~left_mask]
    left_node = _build_boosting_tree(
        binned,
        thresholds,
        gradients,
        hessians,
        left_indices,
        depth=depth + 1,
        selected_features=selected_features,
        config=config,
        nodes=nodes,
        leaf_assignments=leaf_assignments,
    )
    right_node = _build_boosting_tree(
        binned,
        thresholds,
        gradients,
        hessians,
        right_indices,
        depth=depth + 1,
        selected_features=selected_features,
        config=config,
        nodes=nodes,
        leaf_assignments=leaf_assignments,
    )
    nodes[node_index].update(
        {
            "feature": best_feature,
            "threshold": float(thresholds[best_feature][best_bin]),
            "left": left_node,
            "right": right_node,
        }
    )
    return node_index


def _predict_tree(tree: list[dict], features: numpy.ndarray) -> numpy.ndarray:
    predictions = numpy.zeros(len(features), dtype=numpy.float64)
    pending = [(0, numpy.arange(len(features), dtype=numpy.int64))]
    while pending:
        node_index, indices = pending.pop()
        if not len(indices):
            continue
        node = tree[node_index]
        if node["feature"] < 0:
            predictions[indices] = node["value"]
            continue
        mask = (
            features[indices, node["feature"]] <= node["threshold"]
        )
        pending.append((node["left"], indices[mask]))
        pending.append((node["right"], indices[~mask]))
    return predictions


def purged_walk_forward_splits(
    dataset: dataset_module.ResearchDataset,
    config: ValidationConfig,
) -> list[TemporalSplit]:
    config.validate()
    unique_times = numpy.unique(dataset.timestamp)
    if len(unique_times) < 100:
        raise ValueError("not enough unique timestamps for walk-forward validation")
    first_test_index = int(len(unique_times) * config.initial_train_fraction)
    boundaries = numpy.linspace(
        first_test_index,
        len(unique_times),
        config.folds + 1,
        dtype=int,
    )
    splits = []
    for fold in range(config.folds):
        test_start = int(unique_times[boundaries[fold]])
        if boundaries[fold + 1] < len(unique_times):
            test_end = int(unique_times[boundaries[fold + 1]])
        else:
            test_end = int(unique_times[-1] + 1)
        train_cutoff = test_start - config.embargo_seconds
        train_indices = numpy.flatnonzero(
            (dataset.timestamp < train_cutoff)
            & (dataset.event_end_timestamp < test_start)
        )
        test_indices = numpy.flatnonzero(
            (dataset.timestamp >= test_start)
            & (dataset.timestamp < test_end)
        )
        if not len(train_indices) or not len(test_indices):
            raise ValueError(f"fold {fold} is empty after purge and embargo")
        splits.append(
            TemporalSplit(
                train_indices=train_indices,
                test_indices=test_indices,
                train_end_timestamp=int(numpy.max(dataset.timestamp[train_indices])),
                test_start_timestamp=test_start,
                test_end_timestamp=test_end,
            )
        )
    return splits


def run_experiment(
    dataset: dataset_module.ResearchDataset,
    *,
    logistic_config: LogisticConfig = LogisticConfig(),
    boosting_config: BoostingConfig = BoostingConfig(),
    validation_config: ValidationConfig = ValidationConfig(),
    prediction_target: str = "target",
    model_type: str = "logistic",
    locked_block_status: str = "diagnostic_reuse",
) -> dict:
    dataset.validate()
    logistic_config.validate()
    boosting_config.validate()
    validation_config.validate()
    if prediction_target == "target":
        target_labels = dataset.label
    elif prediction_target == "profitable":
        target_labels = dataset.profitable
    else:
        raise ValueError("prediction_target must be 'target' or 'profitable'")
    if model_type == "logistic":
        model_name = "numpy_logistic_regression"

        def fit_model(indices):
            return NumpyLogisticModel.fit(
                dataset.features[indices],
                target_labels[indices],
                dataset.feature_names,
                logistic_config,
            )

    elif model_type == "gradient_boosting":
        model_name = "numpy_gradient_boosting"

        def fit_model(indices):
            return NumpyGradientBoostingModel.fit(
                dataset.features[indices],
                target_labels[indices],
                dataset.feature_names,
                boosting_config,
            )

    else:
        raise ValueError("model_type must be 'logistic' or 'gradient_boosting'")
    if locked_block_status not in {"pristine", "diagnostic_reuse"}:
        raise ValueError("invalid locked_block_status")
    fold_reports = []
    all_selected_indices: list[int] = []
    all_test_indices: list[int] = []
    all_test_probabilities: list[float] = []

    for fold_number, split in enumerate(
        purged_walk_forward_splits(dataset, validation_config), start=1
    ):
        threshold, inner_report = _choose_threshold(
            dataset,
            split.train_indices,
            fit_model,
            validation_config,
        )
        model_train_indices = _training_subsample(
            dataset, split.train_indices, validation_config
        )
        model = fit_model(model_train_indices)
        probabilities = model.predict_proba(dataset.features[split.test_indices])
        selected = select_non_overlapping(
            dataset,
            split.test_indices,
            probabilities,
            threshold,
        )
        report = trading_metrics(
            dataset,
            selected,
            probabilities=_probabilities_for_indices(
                split.test_indices, probabilities, selected
            ),
            position_fraction=validation_config.position_fraction,
        )
        report.update(
            {
                "fold": fold_number,
                "threshold": threshold,
                "train_rows": int(len(split.train_indices)),
                "model_train_rows": int(len(model_train_indices)),
                "test_rows": int(len(split.test_indices)),
                "train_end_timestamp": split.train_end_timestamp,
                "test_start_timestamp": split.test_start_timestamp,
                "test_end_timestamp": split.test_end_timestamp,
                "inner_validation": inner_report,
                "brier_score": float(
                    numpy.mean(
                        (
                            probabilities
                            - target_labels[split.test_indices].astype(float)
                        )
                        ** 2
                    )
                ),
                "calibration_error": expected_calibration_error(
                    target_labels[split.test_indices], probabilities
                ),
            }
        )
        fold_reports.append(report)
        all_selected_indices.extend(int(index) for index in selected)
        all_test_indices.extend(int(index) for index in split.test_indices)
        all_test_probabilities.extend(float(value) for value in probabilities)

    aggregate_selected = remove_overlaps(
        dataset, numpy.asarray(all_selected_indices, dtype=numpy.int64)
    )
    probability_lookup = {
        int(index): probability
        for index, probability in zip(all_test_indices, all_test_probabilities)
    }
    aggregate_probabilities = numpy.asarray(
        [probability_lookup[int(index)] for index in aggregate_selected],
        dtype=float,
    )
    aggregate = trading_metrics(
        dataset,
        aggregate_selected,
        probabilities=aggregate_probabilities,
        position_fraction=validation_config.position_fraction,
    )
    aggregate["positive_folds"] = int(
        sum(report["total_return"] > 0 for report in fold_reports)
    )
    aggregate["folds"] = len(fold_reports)

    locked = _run_locked_test(
        dataset, target_labels, fit_model, validation_config
    )
    leave_one_asset_out = _run_leave_one_asset_out(
        dataset, target_labels, fit_model, validation_config
    )
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model": model_name,
        "prediction_target": prediction_target,
        "locked_block_status": locked_block_status,
        "logistic_config": dataclasses.asdict(logistic_config),
        "boosting_config": dataclasses.asdict(boosting_config),
        "validation_config": dataclasses.asdict(validation_config),
        "walk_forward_folds": fold_reports,
        "walk_forward_aggregate": aggregate,
        "locked_test": locked["report"],
        "leave_one_asset_out": leave_one_asset_out,
        "_locked_model": locked["model"],
        "_locked_selected_indices": locked["selected_indices"],
        "_locked_probabilities": locked["probabilities"],
    }


def select_non_overlapping(
    dataset: dataset_module.ResearchDataset,
    candidate_indices: numpy.ndarray,
    probabilities: numpy.ndarray,
    threshold: float,
) -> numpy.ndarray:
    if len(candidate_indices) != len(probabilities):
        raise ValueError("candidate indices and probabilities are misaligned")
    eligible = [
        (int(index), float(probability))
        for index, probability in zip(candidate_indices, probabilities)
        if probability >= threshold
    ]
    best_by_event: dict[tuple[str, int], tuple[int, float]] = {}
    for index, probability in eligible:
        key = (str(dataset.symbol[index]), int(dataset.timestamp[index]))
        previous = best_by_event.get(key)
        if previous is None or probability > previous[1]:
            best_by_event[key] = (index, probability)
    ordered = sorted(
        best_by_event.values(),
        key=lambda value: (
            int(dataset.timestamp[value[0]]),
            str(dataset.symbol[value[0]]),
            -value[1],
        ),
    )
    next_available: dict[str, int] = {}
    selected = []
    for index, _ in ordered:
        symbol = str(dataset.symbol[index])
        timestamp = int(dataset.timestamp[index])
        if timestamp < next_available.get(symbol, -1):
            continue
        selected.append(index)
        next_available[symbol] = int(dataset.exit_timestamp[index])
    return numpy.asarray(selected, dtype=numpy.int64)


def remove_overlaps(
    dataset: dataset_module.ResearchDataset,
    candidate_indices: numpy.ndarray,
) -> numpy.ndarray:
    unique = sorted(
        set(int(index) for index in candidate_indices),
        key=lambda index: (
            int(dataset.timestamp[index]),
            str(dataset.symbol[index]),
        ),
    )
    next_available: dict[str, int] = {}
    selected = []
    for index in unique:
        symbol = str(dataset.symbol[index])
        if int(dataset.timestamp[index]) < next_available.get(symbol, -1):
            continue
        selected.append(index)
        next_available[symbol] = int(dataset.exit_timestamp[index])
    return numpy.asarray(selected, dtype=numpy.int64)


def trading_metrics(
    dataset: dataset_module.ResearchDataset,
    selected_indices: numpy.ndarray,
    *,
    probabilities: typing.Optional[numpy.ndarray] = None,
    position_fraction: float = 0.10,
) -> dict:
    if not len(selected_indices):
        return _empty_metrics()
    order = numpy.argsort(dataset.timestamp[selected_indices], kind="stable")
    indices = selected_indices[order]
    trade_returns = dataset.net_return[indices] * position_fraction
    equity = numpy.cumprod(1.0 + trade_returns)
    peaks = numpy.maximum.accumulate(numpy.concatenate((numpy.ones(1), equity)))[1:]
    drawdowns = 1.0 - equity / peaks
    profits = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns < 0]
    gross_profit = float(numpy.sum(profits))
    gross_loss = float(-numpy.sum(losses))
    months = {}
    for index, trade_return in zip(indices, trade_returns):
        month = datetime.datetime.fromtimestamp(
            int(dataset.exit_timestamp[index]), datetime.timezone.utc
        ).strftime("%Y-%m")
        months.setdefault(month, []).append(float(trade_return))
    monthly_returns = {
        month: float(numpy.prod(1.0 + numpy.asarray(values)) - 1.0)
        for month, values in sorted(months.items())
    }
    by_symbol = {}
    for symbol in sorted(str(value) for value in numpy.unique(dataset.symbol[indices])):
        symbol_returns = trade_returns[dataset.symbol[indices] == symbol]
        by_symbol[symbol] = {
            "trades": int(len(symbol_returns)),
            "total_return": float(numpy.prod(1.0 + symbol_returns) - 1.0),
            "win_rate": float(numpy.mean(symbol_returns > 0)),
        }
    by_direction = {}
    for direction, name in ((1, "long"), (-1, "short")):
        direction_returns = trade_returns[dataset.direction[indices] == direction]
        by_direction[name] = {
            "trades": int(len(direction_returns)),
            "total_return": (
                float(numpy.prod(1.0 + direction_returns) - 1.0)
                if len(direction_returns)
                else 0.0
            ),
            "win_rate": (
                float(numpy.mean(direction_returns > 0))
                if len(direction_returns)
                else 0.0
            ),
        }
    return {
        "trades": int(len(indices)),
        "wins": int(numpy.sum(trade_returns > 0)),
        "win_rate": float(numpy.mean(trade_returns > 0)),
        "total_return": float(equity[-1] - 1.0),
        "average_trade_return": float(numpy.mean(trade_returns)),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else (float("inf") if gross_profit > 0 else 0.0)
        ),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "max_drawdown": float(numpy.max(drawdowns)),
        "positive_months": int(sum(value > 0 for value in monthly_returns.values())),
        "negative_months": int(sum(value < 0 for value in monthly_returns.values())),
        "monthly_returns": monthly_returns,
        "by_symbol": by_symbol,
        "by_direction": by_direction,
        "average_probability": (
            float(numpy.mean(probabilities)) if probabilities is not None and len(probabilities) else None
        ),
    }


def expected_calibration_error(
    labels: numpy.ndarray,
    probabilities: numpy.ndarray,
    bins: int = 10,
) -> float:
    error = 0.0
    boundaries = numpy.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        if index == bins - 1:
            mask = (probabilities >= boundaries[index]) & (
                probabilities <= boundaries[index + 1]
            )
        else:
            mask = (probabilities >= boundaries[index]) & (
                probabilities < boundaries[index + 1]
            )
        if not numpy.any(mask):
            continue
        error += float(numpy.mean(mask)) * abs(
            float(numpy.mean(labels[mask]))
            - float(numpy.mean(probabilities[mask]))
        )
    return error


def clean_report(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if not key.startswith("_")
    }


def _choose_threshold(
    dataset: dataset_module.ResearchDataset,
    outer_train_indices: numpy.ndarray,
    fit_model: typing.Callable[[numpy.ndarray], typing.Any],
    validation_config: ValidationConfig,
) -> tuple[float, dict]:
    train_times = numpy.unique(dataset.timestamp[outer_train_indices])
    split_at = int(
        len(train_times) * (1.0 - validation_config.inner_validation_fraction)
    )
    validation_start = int(train_times[split_at])
    fit_cutoff = validation_start - validation_config.embargo_seconds
    fit_indices = outer_train_indices[
        (dataset.timestamp[outer_train_indices] < fit_cutoff)
        & (dataset.event_end_timestamp[outer_train_indices] < validation_start)
    ]
    validation_indices = outer_train_indices[
        dataset.timestamp[outer_train_indices] >= validation_start
    ]
    if len(fit_indices) < 100 or len(validation_indices) < 20:
        raise ValueError("inner validation is too small after purge and embargo")
    model_fit_indices = _training_subsample(
        dataset, fit_indices, validation_config
    )
    model = fit_model(model_fit_indices)
    probabilities = model.predict_proba(dataset.features[validation_indices])
    candidates = []
    quantile_thresholds = tuple(
        float(value)
        for value in numpy.quantile(
            probabilities,
            validation_config.probability_quantiles,
        )
    )
    thresholds = sorted(
        set(validation_config.probability_thresholds + quantile_thresholds)
    )
    for threshold in thresholds:
        selected = select_non_overlapping(
            dataset, validation_indices, probabilities, threshold
        )
        metrics = trading_metrics(
            dataset,
            selected,
            probabilities=_probabilities_for_indices(
                validation_indices, probabilities, selected
            ),
            position_fraction=validation_config.position_fraction,
        )
        shortfall = max(
            0, validation_config.minimum_validation_trades - metrics["trades"]
        )
        score = (
            metrics["total_return"]
            - 2.0 * metrics["max_drawdown"]
            - shortfall * 0.001
        )
        candidates.append(
            {
                "threshold": threshold,
                "selection_basis": (
                    "fixed"
                    if threshold in validation_config.probability_thresholds
                    else "validation_probability_quantile"
                ),
                "score": score,
                "metrics": metrics,
            }
        )
    best = max(
        candidates,
        key=lambda value: (
            value["score"],
            value["metrics"]["profit_factor"],
            -value["threshold"],
        ),
    )
    return float(best["threshold"]), {
        "fit_rows": int(len(fit_indices)),
        "model_fit_rows": int(len(model_fit_indices)),
        "validation_rows": int(len(validation_indices)),
        "selected_threshold": float(best["threshold"]),
        "candidates": candidates,
    }


def _run_locked_test(
    dataset: dataset_module.ResearchDataset,
    target_labels: numpy.ndarray,
    fit_model: typing.Callable[[numpy.ndarray], typing.Any],
    validation_config: ValidationConfig,
) -> dict:
    unique_times = numpy.unique(dataset.timestamp)
    test_start_index = int(
        len(unique_times) * (1.0 - validation_config.locked_test_fraction)
    )
    test_start = int(unique_times[test_start_index])
    train_indices = numpy.flatnonzero(
        (dataset.timestamp < test_start - validation_config.embargo_seconds)
        & (dataset.event_end_timestamp < test_start)
    )
    test_indices = numpy.flatnonzero(dataset.timestamp >= test_start)
    threshold, inner_report = _choose_threshold(
        dataset,
        train_indices,
        fit_model,
        validation_config,
    )
    model_train_indices = _training_subsample(
        dataset, train_indices, validation_config
    )
    model = fit_model(model_train_indices)
    probabilities = model.predict_proba(dataset.features[test_indices])
    selected = select_non_overlapping(
        dataset, test_indices, probabilities, threshold
    )
    report = trading_metrics(
        dataset,
        selected,
        probabilities=_probabilities_for_indices(
            test_indices, probabilities, selected
        ),
        position_fraction=validation_config.position_fraction,
    )
    report.update(
        {
            "threshold": threshold,
            "train_rows": int(len(train_indices)),
            "model_train_rows": int(len(model_train_indices)),
            "test_rows": int(len(test_indices)),
            "test_start_timestamp": test_start,
            "inner_validation": inner_report,
            "brier_score": float(
                numpy.mean(
                    (
                        probabilities
                        - target_labels[test_indices].astype(float)
                    )
                    ** 2
                )
            ),
            "calibration_error": expected_calibration_error(
                target_labels[test_indices], probabilities
            ),
        }
    )
    return {
        "report": report,
        "model": model,
        "selected_indices": selected,
        "probabilities": _probabilities_for_indices(
            test_indices, probabilities, selected
        ),
    }


def _run_leave_one_asset_out(
    dataset: dataset_module.ResearchDataset,
    target_labels: numpy.ndarray,
    fit_model: typing.Callable[[numpy.ndarray], typing.Any],
    validation_config: ValidationConfig,
) -> list[dict]:
    unique_times = numpy.unique(dataset.timestamp)
    test_start = int(
        unique_times[
            int(len(unique_times) * (1.0 - validation_config.locked_test_fraction))
        ]
    )
    reports = []
    for symbol in sorted(str(value) for value in numpy.unique(dataset.symbol)):
        train_indices = numpy.flatnonzero(
            (dataset.symbol != symbol)
            & (dataset.timestamp < test_start - validation_config.embargo_seconds)
            & (dataset.event_end_timestamp < test_start)
        )
        test_indices = numpy.flatnonzero(
            (dataset.symbol == symbol) & (dataset.timestamp >= test_start)
        )
        if len(numpy.unique(target_labels[train_indices])) < 2 or not len(test_indices):
            continue
        threshold, _ = _choose_threshold(
            dataset,
            train_indices,
            fit_model,
            validation_config,
        )
        model_train_indices = _training_subsample(
            dataset, train_indices, validation_config
        )
        model = fit_model(model_train_indices)
        probabilities = model.predict_proba(dataset.features[test_indices])
        selected = select_non_overlapping(
            dataset, test_indices, probabilities, threshold
        )
        metrics = trading_metrics(
            dataset,
            selected,
            probabilities=_probabilities_for_indices(
                test_indices, probabilities, selected
            ),
            position_fraction=validation_config.position_fraction,
        )
        metrics.update(
            {
                "held_out_symbol": symbol,
                "threshold": threshold,
                "train_rows": int(len(train_indices)),
                "model_train_rows": int(len(model_train_indices)),
                "test_rows": int(len(test_indices)),
                "test_start_timestamp": test_start,
            }
        )
        reports.append(metrics)
    return reports


def _probabilities_for_indices(
    source_indices: numpy.ndarray,
    probabilities: numpy.ndarray,
    selected_indices: numpy.ndarray,
) -> numpy.ndarray:
    lookup = {
        int(index): float(probability)
        for index, probability in zip(source_indices, probabilities)
    }
    return numpy.asarray(
        [lookup[int(index)] for index in selected_indices],
        dtype=float,
    )


def _training_subsample(
    dataset: dataset_module.ResearchDataset,
    indices: numpy.ndarray,
    validation_config: ValidationConfig,
) -> numpy.ndarray:
    if validation_config.training_stride == 1:
        return indices
    base_interval = dataset_module.TIME_FRAME_SECONDS["15m"]
    slots = dataset.timestamp[indices] // base_interval
    return indices[slots % validation_config.training_stride == 0]


def _sigmoid(values: numpy.ndarray) -> numpy.ndarray:
    clipped = numpy.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + numpy.exp(-clipped))


def _empty_metrics() -> dict:
    return {
        "trades": 0,
        "wins": 0,
        "win_rate": 0.0,
        "total_return": 0.0,
        "average_trade_return": 0.0,
        "profit_factor": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "max_drawdown": 0.0,
        "positive_months": 0,
        "negative_months": 0,
        "monthly_returns": {},
        "by_symbol": {},
        "by_direction": {},
        "average_probability": None,
    }


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
