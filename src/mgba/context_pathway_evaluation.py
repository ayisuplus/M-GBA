"""Fail-closed evaluation for cross-context pathway prediction artifacts."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Mapping, Sequence

from .context_pathway import (
    DEVELOPMENT_CONTEXTS,
    HALLMARK_DIM_COUNT,
    ContextBundle,
    load_context_bundle,
    load_ood_split_manifest,
)
from .experiment import write_json_once
from .hashing import digest_payload
from .ocellus_anchors import sign, spearman
from .validation import file_sha256, finite, required_text, sha256_text

PREDICTIONS_SCHEMA_VERSION = "mgba-context-pathway-predictions-0.1"
EVALUATION_SCHEMA_VERSION = "mgba-context-pathway-evaluation-0.1"
EXTERNAL_PREDICTIONS_SCHEMA_VERSION = (
    "mgba-context-pathway-external-predictions-0.1"
)
BOOTSTRAP_RESAMPLES = 10_000
MODEL_ID = "context-pathway-low-rank-0.1"
OFFICIAL_LEARNED_REPOSITORIES = {
    "gears": "https://github.com/snap-stanford/GEARS",
    "scgpt": "https://github.com/bowang-lab/scGPT",
    "biolord": "https://github.com/nitzanlab/biolord",
}
FROZEN_MODEL_PROTOCOL: dict[str, Any] = {
    "model_id": MODEL_ID,
    "seeds": [17, 42, 73, 101, 211],
    "pca_dim": 64,
    "ranks": [8, 16, 32],
    "learning_rates": [0.0001, 0.0003, 0.001],
    "weight_decays": [0.00001, 0.0001, 0.001],
    "max_epochs": 1000,
    "patience": 50,
    "ridge_alpha": 1.0,
    "target_standardization": "training-pairs-only",
}

_BASE_PREDICTORS = {
    "zero_response": "simple",
    "training_perturbed_mean": "simple",
    "gene_mean": "simple_context_ood_only",
    "context_perturbed_mean": "simple_gene_ood_only",
    "gene_only_ridge": "simple_ablation",
    "context_only_ridge": "ablation",
    "additive_ridge": "simple_ablation",
    "interaction_model": "proposed",
}
_LEARNED_PREDICTORS = {"gears": "learned", "scgpt": "learned", "biolord": "learned"}
_COMMON_UNIT_PREDICTORS = {
    "zero_response",
    "training_perturbed_mean",
    "gene_only_ridge",
    "context_only_ridge",
    "additive_ridge",
    "interaction_model",
}
_SCENARIOS = {"gene_ood", "context_ood", "joint_ood"}
_SIMPLE_JOINT = (
    "zero_response",
    "training_perturbed_mean",
    "gene_only_ridge",
    "context_only_ridge",
    "additive_ridge",
)
_TOLERANCE = 1e-12


def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        raise ValueError(
            f"{name} keys mismatch; missing={sorted(expected - keys)} "
            f"extra={sorted(keys - expected)}"
        )


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _vector(raw: Any, *, name: str) -> tuple[float, ...]:
    if not isinstance(raw, list) or len(raw) != HALLMARK_DIM_COUNT:
        raise ValueError(f"{name} must be a {HALLMARK_DIM_COUNT}-element list")
    return tuple(finite(value, name=name) for value in raw)


def _expected_predictors(scenario: str, available: set[str]) -> set[str]:
    expected = set(_COMMON_UNIT_PREDICTORS)
    expected.update(available & set(_LEARNED_PREDICTORS))
    if scenario == "context_ood":
        expected.add("gene_mean")
    elif scenario == "gene_ood":
        expected.add("context_perturbed_mean")
    return expected


@dataclass(frozen=True, slots=True)
class PredictionUnit:
    context_id: str
    gene: str
    scenario: str
    target: tuple[float, ...]
    predictions: dict[str, tuple[float, ...]]


@dataclass(frozen=True, slots=True)
class ContextPathwayPredictions:
    study_id: str
    fold_id: str
    split_manifest_sha256: str
    protocol_status: str
    scientific_boundary: str
    feature_source: dict[str, Any]
    training: dict[str, Any]
    predictors: dict[str, str]
    learned_sources: dict[str, dict[str, Any]]
    weights: tuple[dict[str, Any], ...]
    units: tuple[PredictionUnit, ...]
    file_sha256: str


def load_context_pathway_predictions(path: str | Path) -> ContextPathwayPredictions:
    predictions_path = Path(path)
    try:
        raw = json.loads(predictions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid context pathway predictions: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("context pathway predictions must be an object")
    _exact_keys(
        raw,
        {
            "schema_version",
            "study_id",
            "fold_id",
            "split_manifest_sha256",
            "protocol_status",
            "scientific_boundary",
            "feature_source",
            "training",
            "predictors",
            "learned_sources",
            "weights",
            "units",
        },
        name="context pathway predictions",
    )
    if raw["schema_version"] != PREDICTIONS_SCHEMA_VERSION:
        raise ValueError("unsupported context pathway predictions schema")
    status = raw["protocol_status"]
    if status not in {"development", "complete"}:
        raise ValueError("protocol_status must be development or complete")

    training = raw["training"]
    if not isinstance(training, dict):
        raise ValueError("training must be an object")
    _exact_keys(
        training,
        set(FROZEN_MODEL_PROTOCOL) | {"selected_hyperparameters", "tuning"},
        name="training",
    )
    for key, expected in FROZEN_MODEL_PROTOCOL.items():
        if training[key] != expected:
            raise ValueError(f"frozen model protocol changed: {key}")
    if training["tuning"] != "inner-leave-one-context-out":
        raise ValueError("training.tuning changed after protocol lock")
    selected = training["selected_hyperparameters"]
    if not isinstance(selected, dict):
        raise ValueError("selected_hyperparameters must be an object")
    _exact_keys(
        selected,
        {"rank", "learning_rate", "weight_decay"},
        name="selected_hyperparameters",
    )
    if selected["rank"] not in FROZEN_MODEL_PROTOCOL["ranks"]:
        raise ValueError("selected rank is outside the frozen grid")
    if selected["learning_rate"] not in FROZEN_MODEL_PROTOCOL["learning_rates"]:
        raise ValueError("selected learning_rate is outside the frozen grid")
    if selected["weight_decay"] not in FROZEN_MODEL_PROTOCOL["weight_decays"]:
        raise ValueError("selected weight_decay is outside the frozen grid")

    predictors = raw["predictors"]
    if not isinstance(predictors, dict):
        raise ValueError("predictors must be an object")
    expected_predictors = dict(_BASE_PREDICTORS)
    if status == "complete":
        expected_predictors.update(_LEARNED_PREDICTORS)
        if not set(_LEARNED_PREDICTORS) <= set(predictors):
            raise ValueError("complete predictions require all learned predictors")
    if predictors != expected_predictors:
        if status == "complete":
            raise ValueError("complete predictions require all learned predictors")
        raise ValueError("development predictor registry must match the frozen set")

    feature_source = raw["feature_source"]
    if not isinstance(feature_source, dict):
        raise ValueError("feature_source must be an object")
    _exact_keys(
        feature_source,
        {"schema_version", "path", "sha256", "dim"},
        name="feature_source",
    )
    if feature_source["schema_version"] != "mgba-gene-embedding-table-0.1":
        raise ValueError("unsupported feature source schema")
    if feature_source["dim"] != 768:
        raise ValueError("Geneformer feature source must be 768-dimensional")
    feature_source = {
        "schema_version": feature_source["schema_version"],
        "path": required_text(feature_source["path"], name="feature_source.path"),
        "sha256": sha256_text(feature_source["sha256"], name="feature_source.sha256"),
        "dim": 768,
    }

    learned_raw = raw["learned_sources"]
    if not isinstance(learned_raw, dict):
        raise ValueError("learned_sources must be an object")
    expected_learned = set(_LEARNED_PREDICTORS) if status == "complete" else set()
    if set(learned_raw) != expected_learned:
        raise ValueError("learned_sources must match the protocol status")
    learned_sources = {}
    for predictor, identity in learned_raw.items():
        if not isinstance(identity, dict):
            raise ValueError(f"learned_sources.{predictor} must be an object")
        _exact_keys(
            identity,
            {"implementation", "mapping", "artifact"},
            name=f"learned_sources.{predictor}",
        )
        implementation = identity["implementation"]
        mapping = identity["mapping"]
        artifact = identity["artifact"]
        if not all(isinstance(item, dict) for item in (implementation, mapping, artifact)):
            raise ValueError(f"learned_sources.{predictor} identities must be objects")
        _exact_keys(
            implementation,
            {"repository", "commit", "version"},
            name=f"learned_sources.{predictor}.implementation",
        )
        _exact_keys(
            mapping,
            {"source_space", "target_space", "hallmark_sha256"},
            name=f"learned_sources.{predictor}.mapping",
        )
        _exact_keys(
            artifact,
            {"path", "sha256"},
            name=f"learned_sources.{predictor}.artifact",
        )
        commit = required_text(
            implementation["commit"], name=f"{predictor}.implementation.commit"
        )
        if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
            raise ValueError(f"{predictor}.implementation.commit must be a full Git SHA")
        if implementation["repository"] != OFFICIAL_LEARNED_REPOSITORIES[predictor]:
            raise ValueError(f"{predictor} repository is not the frozen official repository")
        if (
            mapping["source_space"] != "full-expression"
            or mapping["target_space"] != "hallmark-50-unweighted-log2fc-mean"
        ):
            raise ValueError(f"{predictor} Hallmark mapping protocol changed")
        learned_sources[predictor] = {
            "implementation": {
                "repository": implementation["repository"],
                "commit": commit,
                "version": required_text(
                    implementation["version"], name=f"{predictor}.implementation.version"
                ),
            },
            "mapping": {
                "source_space": mapping["source_space"],
                "target_space": mapping["target_space"],
                "hallmark_sha256": sha256_text(
                    mapping["hallmark_sha256"], name=f"{predictor}.mapping.hallmark_sha256"
                ),
            },
            "artifact": {
                "path": required_text(artifact["path"], name=f"{predictor}.artifact.path"),
                "sha256": sha256_text(
                    artifact["sha256"], name=f"{predictor}.artifact.sha256"
                ),
            },
        }

    weights_raw = raw["weights"]
    if not isinstance(weights_raw, list) or len(weights_raw) != len(FROZEN_MODEL_PROTOCOL["seeds"]):
        raise ValueError("weights must contain one identity per frozen seed")
    weights = []
    for index, item in enumerate(weights_raw):
        if not isinstance(item, dict):
            raise ValueError(f"weights[{index}] must be an object")
        _exact_keys(item, {"seed", "path", "sha256", "bytes"}, name=f"weights[{index}]")
        if item["seed"] != FROZEN_MODEL_PROTOCOL["seeds"][index]:
            raise ValueError("weight seeds must follow the frozen order")
        weights.append(
            {
                "seed": item["seed"],
                "path": required_text(item["path"], name=f"weights[{index}].path"),
                "sha256": sha256_text(item["sha256"], name=f"weights[{index}].sha256"),
                "bytes": _positive_int(item["bytes"], name=f"weights[{index}].bytes"),
            }
        )

    units_raw = raw["units"]
    if not isinstance(units_raw, list) or not units_raw:
        raise ValueError("prediction units must be a non-empty list")
    units = []
    available = set(predictors)
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"units[{index}] must be an object")
        _exact_keys(
            item,
            {"context_id", "gene", "scenario", "target", "predictions"},
            name=f"units[{index}]",
        )
        scenario = required_text(item["scenario"], name=f"units[{index}].scenario")
        if scenario not in _SCENARIOS:
            raise ValueError(f"units[{index}].scenario is unsupported")
        prediction_map = item["predictions"]
        if not isinstance(prediction_map, dict):
            raise ValueError(f"units[{index}].predictions must be an object")
        expected = _expected_predictors(scenario, available)
        if set(prediction_map) != expected:
            raise ValueError(
                f"units[{index}] predictors disagree with scenario {scenario}"
            )
        units.append(
            PredictionUnit(
                context_id=required_text(
                    item["context_id"], name=f"units[{index}].context_id"
                ),
                gene=required_text(item["gene"], name=f"units[{index}].gene"),
                scenario=scenario,
                target=_vector(item["target"], name=f"units[{index}].target"),
                predictions={
                    predictor: _vector(values, name=f"units[{index}].{predictor}")
                    for predictor, values in prediction_map.items()
                },
            )
        )
    identities = [(unit.scenario, unit.context_id, unit.gene) for unit in units]
    if identities != sorted(identities) or len(set(identities)) != len(identities):
        raise ValueError("prediction units must be unique and sorted")

    return ContextPathwayPredictions(
        study_id=required_text(raw["study_id"], name="study_id"),
        fold_id=required_text(raw["fold_id"], name="fold_id"),
        split_manifest_sha256=sha256_text(
            raw["split_manifest_sha256"], name="split_manifest_sha256"
        ),
        protocol_status=status,
        scientific_boundary=required_text(
            raw["scientific_boundary"], name="scientific_boundary"
        ),
        feature_source=feature_source,
        training=dict(training),
        predictors=dict(predictors),
        learned_sources=learned_sources,
        weights=tuple(weights),
        units=tuple(units),
        file_sha256=file_sha256(predictions_path),
    )


def _mean(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    if not vectors:
        raise ValueError("cannot average an empty vector collection")
    return tuple(fmean(values) for values in zip(*vectors))


def _close(left: Sequence[float], right: Sequence[float]) -> bool:
    return all(abs(a - b) <= _TOLERANCE for a, b in zip(left, right))


def _unit_loss(
    unit: PredictionUnit, predictor: str, scales: Sequence[float]
) -> float:
    return fmean(
        abs(predicted - target) / scale
        for predicted, target, scale in zip(
            unit.predictions[predictor], unit.target, scales
        )
    )


def _top_recall(target: Sequence[float], predicted: Sequence[float], k: int = 5) -> float:
    target_top = {
        index for index, _ in sorted(enumerate(target), key=lambda item: (-abs(item[1]), item[0]))[:k]
    }
    predicted_top = {
        index
        for index, _ in sorted(
            enumerate(predicted), key=lambda item: (-abs(item[1]), item[0])
        )[:k]
    }
    return len(target_top & predicted_top) / k


def _mean_pathway_spearman(
    units: Sequence[PredictionUnit], predictor: str
) -> float:
    return fmean(
        spearman(
            [unit.target[index] for unit in units],
            [unit.predictions[predictor][index] for unit in units],
        )
        for index in range(HALLMARK_DIM_COUNT)
    )


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + end - 1) / 2.0
        for position in order[start:end]:
            result[position] = rank
        start = end
    return result


def _pathway_spearman_contributions(
    units: Sequence[PredictionUnit], predictor: str
) -> list[float]:
    contributions = [0.0] * len(units)
    for index in range(HALLMARK_DIM_COUNT):
        target = _ranks([unit.target[index] for unit in units])
        predicted = _ranks([unit.predictions[predictor][index] for unit in units])
        target_mean = fmean(target)
        predicted_mean = fmean(predicted)
        target_centered = [value - target_mean for value in target]
        predicted_centered = [value - predicted_mean for value in predicted]
        denominator = (
            sum(value * value for value in target_centered)
            * sum(value * value for value in predicted_centered)
        ) ** 0.5
        if denominator == 0.0:
            continue
        for row, (left, right) in enumerate(
            zip(target_centered, predicted_centered)
        ):
            contributions[row] += len(units) * left * right / denominator
    return [value / HALLMARK_DIM_COUNT for value in contributions]


def _bootstrap_blocks(blocks: Sequence[Sequence[float]]) -> dict[str, float]:
    generator = random.Random(20260903)

    def sampled_mean() -> float:
        sampled = [blocks[generator.randrange(len(blocks))] for _ in blocks]
        return sum(sum(block) for block in sampled) / sum(len(block) for block in sampled)

    samples = sorted(
        sampled_mean()
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    observed = [value for block in blocks for value in block]
    nonpositive = sum(value <= 0.0 for value in samples) / len(samples)
    nonnegative = sum(value >= 0.0 for value in samples) / len(samples)
    return {
        "mean_difference": fmean(observed),
        "ci95_lower": samples[int(0.025 * (len(samples) - 1))],
        "ci95_upper": samples[int(0.975 * (len(samples) - 1))],
        "p_value_two_sided": min(1.0, 2.0 * min(nonpositive, nonnegative)),
    }


def _benjamini_hochberg(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 1.0
    count = len(ordered)
    for rank in range(count, 0, -1):
        name, value = ordered[rank - 1]
        running = min(running, value * count / rank)
        adjusted[name] = min(1.0, running)
    return {name: adjusted[name] for name in sorted(adjusted)}


def _bundle_index(bundles: Sequence[ContextBundle]) -> dict[str, ContextBundle]:
    by_context = {bundle.context_id: bundle for bundle in bundles}
    if len(by_context) != len(bundles) or set(by_context) != set(DEVELOPMENT_CONTEXTS):
        raise ValueError("evaluation requires exactly the four development contexts")
    return by_context


def evaluate_context_pathway_predictions(
    predictions: Sequence[ContextPathwayPredictions],
    split_path: str | Path,
    bundle_paths: Sequence[str | Path],
) -> dict[str, Any]:
    if not predictions:
        raise ValueError("at least one predictions artifact is required")
    split = load_ood_split_manifest(split_path)
    split_digest = split.pop("_file_sha256")
    bundles = [load_context_bundle(path) for path in bundle_paths]
    by_context = _bundle_index(bundles)
    for context, identity in split["bundles"].items():
        bundle = by_context[context]
        if identity["sha256"] != bundle.file_sha256:
            raise ValueError(f"bundle SHA-256 mismatch for {context}")
        if identity["dataset_id"] != bundle.dataset_id:
            raise ValueError(f"bundle dataset_id mismatch for {context}")
    hallmark_sha256 = by_context[DEVELOPMENT_CONTEXTS[0]].hallmark_source["sha256"]
    folds = {fold["fold_id"]: fold for fold in split["folds"]}
    if len({item.fold_id for item in predictions}) != len(predictions):
        raise ValueError("prediction fold ids must be unique")
    if len({digest_payload(item.feature_source) for item in predictions}) != 1:
        raise ValueError("prediction folds must use the same Geneformer feature source")
    locked_feature = split["feature_eligibility"]
    observed_feature = predictions[0].feature_source
    if (
        observed_feature["schema_version"] != locked_feature["schema_version"]
        or observed_feature["dim"] != locked_feature["embedding_dim"]
        or observed_feature["sha256"] != locked_feature["embedding_table_sha256"]
    ):
        raise ValueError("prediction Geneformer feature source does not match the locked split")
    learned_protocols = [
        {
            predictor: {
                "implementation": identity["implementation"],
                "mapping": identity["mapping"],
            }
            for predictor, identity in item.learned_sources.items()
        }
        for item in predictions
    ]
    if len({digest_payload(item) for item in learned_protocols}) != 1:
        raise ValueError("prediction folds must use the same frozen learned baselines")
    if any(
        identity["mapping"]["hallmark_sha256"] != hallmark_sha256
        for protocol in learned_protocols
        for identity in protocol.values()
    ):
        raise ValueError("learned baseline Hallmark mapping digest mismatch")

    scenario_items: dict[str, list[tuple[str, PredictionUnit]]] = {
        scenario: [] for scenario in _SCENARIOS
    }
    scale_by_fold: dict[str, tuple[float, ...]] = {}
    for artifact in predictions:
        if artifact.split_manifest_sha256 != split_digest:
            raise ValueError("predictions do not match the split manifest SHA-256")
        if artifact.study_id != split["study_id"] or artifact.fold_id not in folds:
            raise ValueError("predictions reference an unknown study or fold")
        fold = folds[artifact.fold_id]
        targets = {
            (context, unit.gene): unit.target
            for context, bundle in by_context.items()
            for unit in bundle.units
        }
        train_vectors = [
            targets[(context, gene)]
            for context in fold["training_contexts"]
            for gene in fold["train_genes"]
        ]
        train_means = _mean(train_vectors)
        scales = tuple(pstdev(values) for values in zip(*train_vectors))
        if any(scale <= _TOLERANCE for scale in scales):
            raise ValueError("a Hallmark target dimension has zero training variance")
        scale_by_fold[artifact.fold_id] = scales
        context_means = {
            context: _mean([targets[(context, gene)] for gene in fold["train_genes"]])
            for context in fold["training_contexts"]
        }
        gene_means = {
            gene: _mean([targets[(context, gene)] for context in fold["training_contexts"]])
            for gene in fold["train_genes"]
        }
        expected: dict[tuple[str, str, str], tuple[float, ...]] = {}
        outer = fold["outer_context"]
        for gene in fold["train_genes"]:
            expected[("context_ood", outer, gene)] = targets[(outer, gene)]
        for context in fold["training_contexts"]:
            for gene in fold["test_genes"]:
                expected[("gene_ood", context, gene)] = targets[(context, gene)]
        for gene in fold["test_genes"]:
            expected[("joint_ood", outer, gene)] = targets[(outer, gene)]
        observed = {
            (unit.scenario, unit.context_id, unit.gene): unit for unit in artifact.units
        }
        if set(observed) != set(expected):
            raise ValueError("prediction coverage or scenario assignment violates the OOD fold")
        zeros = (0.0,) * HALLMARK_DIM_COUNT
        for identity, expected_target in expected.items():
            unit = observed[identity]
            if unit.target != expected_target:
                raise ValueError(f"target tampered for {unit.context_id}/{unit.gene}")
            if not _close(unit.predictions["zero_response"], zeros):
                raise ValueError("zero_response baseline was not recomputed correctly")
            if not _close(unit.predictions["training_perturbed_mean"], train_means):
                raise ValueError("training_perturbed_mean baseline was not recomputed correctly")
            if unit.scenario == "context_ood" and not _close(
                unit.predictions["gene_mean"], gene_means[unit.gene]
            ):
                raise ValueError("gene_mean baseline was not recomputed correctly")
            if unit.scenario == "gene_ood" and not _close(
                unit.predictions["context_perturbed_mean"], context_means[unit.context_id]
            ):
                raise ValueError("context_perturbed_mean baseline was not recomputed correctly")
            scenario_items[unit.scenario].append((artifact.fold_id, unit))

    metrics: dict[str, dict[str, Any]] = {}
    for scenario in sorted(_SCENARIOS):
        items = scenario_items[scenario]
        common = set.intersection(*(set(unit.predictions) for _, unit in items))
        metrics[scenario] = {
            predictor: {
                "standardized_macro_mae": fmean(
                    _unit_loss(unit, predictor, scale_by_fold[fold_id])
                    for fold_id, unit in items
                ),
                "mean_pathway_spearman": _mean_pathway_spearman(
                    [unit for _, unit in items], predictor
                ),
                "direction_agreement": fmean(
                    fmean(
                        1.0 if sign(target) == sign(predicted) else 0.0
                        for target, predicted in zip(unit.target, unit.predictions[predictor])
                    )
                    for _, unit in items
                ),
                "strong_response_top5_recall": fmean(
                    _top_recall(unit.target, unit.predictions[predictor])
                    for _, unit in items
                ),
                "unit_count": len(items),
            }
            for predictor in sorted(common)
        }

    simple_scores = {
        predictor: metrics["joint_ood"][predictor]["standardized_macro_mae"]
        for predictor in _SIMPLE_JOINT
    }
    best_simple = min(simple_scores, key=lambda predictor: simple_scores[predictor])
    learned_available = set(_LEARNED_PREDICTORS) <= set(metrics["joint_ood"])
    best_learned = (
        min(
            _LEARNED_PREDICTORS,
            key=lambda predictor: metrics["joint_ood"][predictor]["standardized_macro_mae"],
        )
        if learned_available
        else None
    )
    comparisons = {}
    for baseline in sorted(set(_SIMPLE_JOINT) | (set(_LEARNED_PREDICTORS) if learned_available else set())):
        differences_by_fold: list[tuple[PredictionUnit, float]] = []
        for artifact in predictions:
            fold_units = [unit for unit in artifact.units if unit.scenario == "joint_ood"]
            differences_by_fold.extend(
                (
                    unit,
                    _unit_loss(unit, "interaction_model", scale_by_fold[artifact.fold_id])
                    - _unit_loss(unit, baseline, scale_by_fold[artifact.fold_id]),
                )
                for unit in fold_units
            )
        grouped: dict[str, list[float]] = {}
        for unit, difference in differences_by_fold:
            grouped.setdefault(unit.gene, []).append(difference)
        blocks = [values for _, values in sorted(grouped.items())]
        comparisons[baseline] = _bootstrap_blocks(blocks)
    adjusted = _benjamini_hochberg(
        {name: item["p_value_two_sided"] for name, item in comparisons.items()}
    )
    for name, value in adjusted.items():
        comparisons[name]["p_value_bh"] = value

    joint_units = [unit for _, unit in scenario_items["joint_ood"]]
    secondary_values = {
        "mean_pathway_spearman": {
            predictor: _pathway_spearman_contributions(joint_units, predictor)
            for predictor in {"interaction_model"} | set(comparisons)
        },
        "direction_agreement": {
            predictor: [
                fmean(
                    1.0 if sign(target) == sign(predicted) else 0.0
                    for target, predicted in zip(
                        unit.target, unit.predictions[predictor]
                    )
                )
                for unit in joint_units
            ]
            for predictor in {"interaction_model"} | set(comparisons)
        },
        "strong_response_top5_recall": {
            predictor: [
                _top_recall(unit.target, unit.predictions[predictor])
                for unit in joint_units
            ]
            for predictor in {"interaction_model"} | set(comparisons)
        },
    }
    secondary_comparisons: dict[str, dict[str, dict[str, float]]] = {}
    secondary_p_values = {}
    for metric, predictor_values in secondary_values.items():
        secondary_comparisons[metric] = {}
        for baseline in comparisons:
            grouped = {}
            for unit, model_value, baseline_value in zip(
                joint_units,
                predictor_values["interaction_model"],
                predictor_values[baseline],
            ):
                grouped.setdefault(unit.gene, []).append(model_value - baseline_value)
            blocks = [values for _, values in sorted(grouped.items())]
            result = _bootstrap_blocks(blocks)
            secondary_comparisons[metric][baseline] = result
            secondary_p_values[f"{metric}|{baseline}"] = result["p_value_two_sided"]
    secondary_adjusted = _benjamini_hochberg(secondary_p_values)
    for identity, value in secondary_adjusted.items():
        metric, baseline = identity.split("|", 1)
        secondary_comparisons[metric][baseline]["p_value_bh"] = value

    model_score = metrics["joint_ood"]["interaction_model"]["standardized_macro_mae"]
    simple_score = simple_scores[best_simple]
    relative_simple = (simple_score - model_score) / simple_score if simple_score else 0.0
    relative_learned: float | None = None
    if best_learned is not None:
        learned_score = metrics["joint_ood"][best_learned]["standardized_macro_mae"]
        relative_learned = (learned_score - model_score) / learned_score if learned_score else 0.0

    per_context: dict[str, dict[str, Any]] = {}
    for context in DEVELOPMENT_CONTEXTS:
        selected = [
            unit
            for artifact in predictions
            if folds[artifact.fold_id]["outer_context"] == context
            for unit in artifact.units
            if unit.scenario == "joint_ood"
        ]
        if not selected:
            continue
        model = fmean(
            _unit_loss(unit, "interaction_model", scale_by_fold[artifact.fold_id])
            for artifact in predictions
            if folds[artifact.fold_id]["outer_context"] == context
            for unit in artifact.units
            if unit.scenario == "joint_ood"
        )
        context_simple_scores = {
            predictor: fmean(
                _unit_loss(unit, predictor, scale_by_fold[artifact.fold_id])
                for artifact in predictions
                if folds[artifact.fold_id]["outer_context"] == context
                for unit in artifact.units
                if unit.scenario == "joint_ood"
            )
            for predictor in _SIMPLE_JOINT
        }
        context_best_simple = min(
            context_simple_scores,
            key=lambda predictor: context_simple_scores[predictor],
        )
        context_baseline = context_simple_scores[context_best_simple]
        per_context[context] = {
            "interaction_model": model,
            "best_simple_id": context_best_simple,
            "best_simple": context_baseline,
            "relative_improvement": (
                (context_baseline - model) / context_baseline
                if context_baseline
                else 0.0
            ),
            "won": model < context_baseline,
        }

    folds_complete = (
        len(predictions) == len(folds)
        and set(item.fold_id for item in predictions) == set(folds)
    )
    complete = (
        folds_complete
        and all(item.protocol_status == "complete" for item in predictions)
    )
    wins = sum(item["won"] for item in per_context.values())
    worst_regression = max(
        (-item["relative_improvement"] for item in per_context.values()), default=0.0
    )
    reasons = []
    if not complete:
        reasons.append("all 20 folds and all three learned baselines are required")
    known_failure = False
    if folds_complete and relative_simple < 0.05:
        known_failure = True
        reasons.append("joint OOD improvement versus the best simple baseline is below 5%")
    if folds_complete and comparisons[best_simple]["ci95_upper"] >= 0.0:
        known_failure = True
        reasons.append(
            "paired bootstrap 95% CI versus the best simple baseline is not entirely below zero"
        )
    if complete and relative_learned is not None and relative_learned < 0.02:
        known_failure = True
        reasons.append("joint OOD improvement versus the best learned baseline is below 2%")
    elif relative_learned is None:
        reasons.append("joint OOD improvement versus the best learned baseline is unavailable")
    if folds_complete and wins < 3:
        known_failure = True
        reasons.append("the interaction model wins in fewer than three development contexts")
    if folds_complete and worst_regression > 0.02:
        known_failure = True
        reasons.append("at least one development context regresses by more than 2%")
    development_passed = complete and not reasons
    hyperparameter_counts: dict[tuple[int, float, float], int] = {}
    for artifact in predictions:
        selected = artifact.training["selected_hyperparameters"]
        identity = (
            selected["rank"],
            selected["learning_rate"],
            selected["weight_decay"],
        )
        hyperparameter_counts[identity] = hyperparameter_counts.get(identity, 0) + 1
    locked_external = None
    if complete:
        chosen = min(
            hyperparameter_counts,
            key=lambda identity: (-hyperparameter_counts[identity], identity),
        )
        locked_external = {
            "rule": "modal-development-fold-selection-lexicographic-tie-break",
            "rank": chosen[0],
            "learning_rate": chosen[1],
            "weight_decay": chosen[2],
        }

    content: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "study_id": split["study_id"],
        "scientific_boundary": split["scientific_boundary"],
        "source": {
            "split_manifest_sha256": split_digest,
            "bundle_sha256": {
                context: by_context[context].file_sha256 for context in DEVELOPMENT_CONTEXTS
            },
            "prediction_sha256": sorted(item.file_sha256 for item in predictions),
            "feature_source": predictions[0].feature_source,
            "learned_sources": {
                predictor: {
                    **learned_protocols[0][predictor],
                    "artifacts": sorted(
                        (
                            item.learned_sources[predictor]["artifact"]
                            for item in predictions
                        ),
                        key=lambda artifact: (artifact["sha256"], artifact["path"]),
                    ),
                }
                for predictor in learned_protocols[0]
            },
        },
        "coverage": {
            "folds": len(predictions),
            "required_folds": len(folds),
            "protocol_complete": complete,
            "external_test_status": split["external_test"]["status"],
        },
        "metrics": metrics,
        "statistics": {
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "block": "perturbation-gene",
            "comparisons": comparisons,
            "secondary_comparisons": secondary_comparisons,
            "secondary_spearman_method": (
                "gene-block bootstrap of fixed full-sample pathway-rank contributions"
            ),
        },
        "selection": {
            "best_simple": best_simple,
            "best_learned": best_learned,
            "relative_improvement_vs_simple": relative_simple,
            "relative_improvement_vs_learned": relative_learned,
            "development_contexts_won": wins,
            "worst_context_regression": worst_regression,
            "per_context": per_context,
            "locked_external_hyperparameters": locked_external,
        },
        "pass_rule": {
            "development_verdict": (
                "passed"
                if development_passed
                else "failed"
                if known_failure or complete
                else "incomplete"
            ),
            "paper_verdict": "sealed",
            "reasons": reasons,
            "external_requirement": (
                "Arc H1 remains sealed; paper go additionally requires >=3% improvement "
                "over its best simple baseline in a separate one-shot evaluation."
            ),
        },
    }
    content["evaluation_id"] = f"context-pathway-eval-{digest_payload(content)[:16]}"
    return content


def _validate_evaluation(evaluation: Mapping[str, Any]) -> None:
    _exact_keys(
        evaluation,
        {
            "schema_version",
            "study_id",
            "scientific_boundary",
            "source",
            "coverage",
            "metrics",
            "statistics",
            "selection",
            "pass_rule",
            "evaluation_id",
        },
        name="context pathway evaluation",
    )
    if evaluation.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ValueError("unsupported context pathway evaluation schema")
    content = dict(evaluation)
    evaluation_id = content.pop("evaluation_id", None)
    expected = f"context-pathway-eval-{digest_payload(content)[:16]}"
    if evaluation_id != expected:
        raise ValueError("evaluation_id does not match evaluation content")


def load_context_pathway_evaluation(path: str | Path) -> dict[str, Any]:
    evaluation_path = Path(path)
    try:
        raw = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid context pathway evaluation: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("context pathway evaluation must be an object")
    _validate_evaluation(raw)
    raw["_file_sha256"] = file_sha256(evaluation_path)
    return raw


def _claim_external_access(
    path: str | Path,
    *,
    study_id: str,
    split_digest: str,
    evaluation_id: str,
    prediction_digest: str,
) -> Path:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    content = {
        "schema_version": "mgba-external-test-access-lock-0.1",
        "study_id": study_id,
        "split_manifest_sha256": split_digest,
        "development_evaluation_id": evaluation_id,
        "external_prediction_sha256": prediction_digest,
        "status": "consumed",
    }
    try:
        with lock_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(content, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as error:
        raise ValueError("Arc H1 external test was already consumed") from error
    return lock_path


def evaluate_external_context_pathway_predictions(
    predictions_path: str | Path,
    external_bundle_path: str | Path,
    development_evaluation_path: str | Path,
    split_path: str | Path,
    development_bundle_paths: Sequence[str | Path],
    access_lock_path: str | Path,
    development_prediction_paths: Sequence[str | Path],
) -> dict[str, Any]:
    split = load_ood_split_manifest(split_path)
    split_digest = split.pop("_file_sha256")
    development = load_context_pathway_evaluation(development_evaluation_path)
    development_digest = development.pop("_file_sha256")
    if (
        development["study_id"] != split["study_id"]
        or development["source"].get("split_manifest_sha256") != split_digest
        or development["coverage"].get("protocol_complete") is not True
        or development["pass_rule"].get("development_verdict") != "passed"
        or development["pass_rule"].get("paper_verdict") != "sealed"
    ):
        raise ValueError("external test requires a complete passed locked development evaluation")
    bundles = [load_context_bundle(path) for path in development_bundle_paths]
    by_context = _bundle_index(bundles)
    for context, identity in split["bundles"].items():
        if by_context[context].file_sha256 != identity["sha256"]:
            raise ValueError(f"bundle SHA-256 mismatch for {context}")
    recomputed = evaluate_context_pathway_predictions(
        [load_context_pathway_predictions(path) for path in development_prediction_paths],
        split_path,
        development_bundle_paths,
    )
    if recomputed != development:
        raise ValueError("saved development evidence does not match recomputed predictions")

    partitions = {
        salt: next(fold for fold in split["folds"] if fold["salt"] == salt)
        for salt in split["salts"]
    }
    all_expected = {
        (salt, gene)
        for salt, fold in partitions.items()
        for gene in fold["test_genes"]
    }

    prediction_file = Path(predictions_path)
    try:
        prediction_bytes = prediction_file.read_bytes()
        raw = json.loads(prediction_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid external predictions: {error}") from error
    prediction_digest = sha256(prediction_bytes).hexdigest()
    if not isinstance(raw, dict):
        raise ValueError("external predictions must be an object")
    _exact_keys(
        raw,
        {
            "schema_version",
            "study_id",
            "development_evaluation_id",
            "split_manifest_sha256",
            "context_id",
            "protocol_status",
            "hyperparameters",
            "model_artifacts",
            "predictors",
            "units",
        },
        name="external predictions",
    )
    if (
        raw["schema_version"] != EXTERNAL_PREDICTIONS_SCHEMA_VERSION
        or raw["study_id"] != split["study_id"]
        or raw["development_evaluation_id"] != development["evaluation_id"]
        or raw["split_manifest_sha256"] != split_digest
        or raw["context_id"] != split["external_test"]["context_id"]
        or raw["protocol_status"] != "locked-after-development"
    ):
        raise ValueError("external prediction provenance changed after lock")
    if raw["hyperparameters"] != development["selection"].get(
        "locked_external_hyperparameters"
    ):
        raise ValueError("external prediction hyperparameters differ from the development lock")
    expected_predictors = dict(_BASE_PREDICTORS) | _LEARNED_PREDICTORS
    if raw["predictors"] != expected_predictors:
        raise ValueError("external predictions require the complete frozen predictor registry")
    model_artifacts = raw["model_artifacts"]
    if not isinstance(model_artifacts, dict) or set(model_artifacts) != set(split["salts"]):
        raise ValueError("external model artifacts must cover all five salts")
    for salt, digest in model_artifacts.items():
        sha256_text(digest, name=f"model_artifacts.{salt}")
    units_raw = raw["units"]
    if not isinstance(units_raw, list):
        raise ValueError("external prediction units must be a list")
    prediction_units = {}
    available = set(raw["predictors"])
    expected_unit_predictors = _expected_predictors("joint_ood", available)
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"external units[{index}] must be an object")
        _exact_keys(
            item,
            {"salt", "gene", "predictions"},
            name=f"external units[{index}]",
        )
        salt = required_text(item["salt"], name=f"external units[{index}].salt")
        gene = required_text(item["gene"], name=f"external units[{index}].gene")
        if salt not in partitions:
            raise ValueError(f"external units[{index}].salt is not pre-registered")
        identity = (salt, gene)
        if identity in prediction_units:
            raise ValueError("external prediction units must be unique")
        if not isinstance(item["predictions"], dict) or set(item["predictions"]) != expected_unit_predictors:
            raise ValueError("external prediction unit has the wrong predictors")
        prediction_units[identity] = {
            predictor: _vector(values, name=f"external units[{index}].{predictor}")
            for predictor, values in item["predictions"].items()
        }
    if set(prediction_units) != all_expected or list(prediction_units) != sorted(prediction_units):
        raise ValueError("external predictions must cover every locked test gene before label access")

    _claim_external_access(
        access_lock_path,
        study_id=split["study_id"],
        split_digest=split_digest,
        evaluation_id=development["evaluation_id"],
        prediction_digest=prediction_digest,
    )
    external = load_context_bundle(external_bundle_path)
    if external.context_id != split["external_test"]["context_id"]:
        raise ValueError("external bundle must be the locked Arc H1 context")
    if external.source["sha256"] != split["external_test"]["labels_sha256"]:
        raise ValueError("Arc H1 label digest does not match the sealed manifest")
    if external.dims != tuple(split["dims"]):
        raise ValueError("Arc H1 Hallmark dimensions changed after protocol lock")
    external_targets = {unit.gene: unit.target for unit in external.units}
    expected = {
        identity for identity in all_expected if identity[1] in external_targets
    }
    if any(
        not any(salt == identity[0] for identity in expected)
        for salt in split["salts"]
    ):
        raise ValueError("Arc H1 has no locked test genes for at least one salt")
    units = {
        identity: PredictionUnit(
            context_id=external.context_id,
            gene=identity[1],
            scenario="joint_ood",
            target=external_targets[identity[1]],
            predictions=prediction_units[identity],
        )
        for identity in expected
    }

    scales = {}
    target_index = {
        (context, unit.gene): unit.target
        for context, bundle in by_context.items()
        for unit in bundle.units
    }
    zeros = (0.0,) * HALLMARK_DIM_COUNT
    for salt, fold in partitions.items():
        train_vectors = [
            target_index[(context, gene)]
            for context in DEVELOPMENT_CONTEXTS
            for gene in fold["train_genes"]
        ]
        training_mean = _mean(train_vectors)
        scale = tuple(pstdev(values) for values in zip(*train_vectors))
        if any(value <= _TOLERANCE for value in scale):
            raise ValueError("an external training target dimension has zero variance")
        scales[salt] = scale
        for gene in fold["test_genes"]:
            if gene not in external_targets:
                continue
            unit = units[(salt, gene)]
            if not _close(unit.predictions["zero_response"], zeros):
                raise ValueError("external zero_response baseline was not recomputed correctly")
            if not _close(unit.predictions["training_perturbed_mean"], training_mean):
                raise ValueError("external training_perturbed_mean baseline was not recomputed correctly")

    ordered_units = [units[identity] for identity in sorted(units)]
    metrics = {
        predictor: {
            "standardized_macro_mae": fmean(
                _unit_loss(unit, predictor, scales[salt])
                for (salt, _), unit in sorted(units.items())
            ),
            "mean_pathway_spearman": _mean_pathway_spearman(ordered_units, predictor),
            "direction_agreement": fmean(
                fmean(
                    1.0 if sign(target) == sign(predicted) else 0.0
                    for target, predicted in zip(unit.target, unit.predictions[predictor])
                )
                for unit in ordered_units
            ),
            "strong_response_top5_recall": fmean(
                _top_recall(unit.target, unit.predictions[predictor])
                for unit in ordered_units
            ),
            "unit_count": len(ordered_units),
        }
        for predictor in sorted(expected_unit_predictors)
    }
    best_simple = min(
        _SIMPLE_JOINT,
        key=lambda predictor: metrics[predictor]["standardized_macro_mae"],
    )
    model_score = metrics["interaction_model"]["standardized_macro_mae"]
    simple_score = metrics[best_simple]["standardized_macro_mae"]
    improvement = (simple_score - model_score) / simple_score if simple_score else 0.0
    passed = improvement >= 0.03

    result = json.loads(json.dumps(development))
    result["source"]["external"] = {
        "development_evaluation_sha256": development_digest,
        "bundle_sha256": external.file_sha256,
        "prediction_sha256": prediction_digest,
        "access_lock": str(access_lock_path),
    }
    result["coverage"]["external_test_status"] = "consumed"
    result["metrics"]["external_joint_ood"] = metrics
    result["selection"]["external"] = {
        "best_simple": best_simple,
        "relative_improvement_vs_simple": improvement,
    }
    result["pass_rule"]["paper_verdict"] = "go" if passed else "no-go"
    result["pass_rule"]["external_requirement"] = (
        "passed: Arc H1 improvement is at least 3%"
        if passed
        else "failed: Arc H1 improvement is below 3%"
    )
    content = dict(result)
    content.pop("evaluation_id")
    result["evaluation_id"] = f"context-pathway-eval-{digest_payload(content)[:16]}"
    return result


def save_context_pathway_evaluation(
    evaluation: Mapping[str, Any], output_path: str | Path
) -> Path:
    _validate_evaluation(evaluation)
    return write_json_once(output_path, evaluation, artifact="context pathway evaluation")
