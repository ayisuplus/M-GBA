"""Core verification segment for the ADR-0046 Hallmark structured-target run.

Pure stdlib. Loads the ``mgba-l0-hallmark-predictions-0.1`` file produced by
``scripts/train_l0_hallmark_response.py`` (independent venv only), verifies it
against the ``mgba-hallmark-target-0.1`` artifact and the frozen
hyperparameters, recomputes every metric, and applies the pre-registered pass
rule on the six-node head. The training script cannot influence the verdict:
it only supplies numbers; this module re-derives them. The Norman OE arm is
descriptive-only (ADR-0040 precedent): its ``verdict`` is the frozen literal
``descriptive`` and never a pass claim. ``l0_training_evaluation.py`` stays
untouched as the frozen validator of the historical artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from .experiment import write_json_once
from .hashing import digest_payload
from .hallmark_targets import (
    HallmarkTarget,
    load_hallmark_target,
    mean_metrics_d,
    vector_metrics_d,
)
from .layers.l0 import ABSTRACT_GENE_NAMES
from .validation import file_sha256, finite, required_text, sha256_text

PREDICTIONS_SCHEMA_VERSION = "mgba-l0-hallmark-predictions-0.1"
EVALUATION_SCHEMA_VERSION = "mgba-l0-hallmark-training-evaluation-0.1"
PASS_EPSILON = 1e-12

# Frozen by ADR-0046 before any training run (verbatim from ADR-0037).
FROZEN_HALLMARK_TRAINING = {
    "seed": 42,
    "hidden": 32,
    "learning_rate": 1e-3,
    "weight_decay": 1e-4,
    "epochs": 3000,
    "ridge_lambda": 1.0,
    "device": "cpu-single-thread",
    "input_dim": 768,
}
_TRAINING_EXTRA_KEYS = {
    "torch_version",
    "final_train_loss_mse",
    "output_dim",
    "embedding_table_sha256",
    "embedding_dim",
    "covered_units",
    "excluded_units",
    "centroid_crosscheck_max_abs_diff",
}
PREDICTOR_IDS = ("centroid", "ridge", "mlp")
TRAIN_ROLE = "train"
HOLDOUT_ROLE = "holdout"

# The pass rule gates only the primary (KD) arm; the OE arm is descriptive
# (ADR-0040 precedent). Unknown datasets fail closed.
ARM_BY_DATASET = {
    "replogle-2022-k562-essential-scperturb": "primary",
    "norman-weissman-2019-scperturb-filtered": "descriptive",
}

SCIENTIFIC_BOUNDARY = (
    "Offline evaluation of a small perturbation-response predictor against "
    "the ADR-0046 Hallmark structured target (covered Hallmark sets plus the "
    "frozen six-node union head). Predictions do not enter the runtime chain "
    "and are not a biological fit, a virtual-cell claim, or an efficacy "
    "predictor. Reference-model grade."
)








def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"{name} keys mismatch; missing={missing} extra={extra}")


@dataclass(frozen=True, slots=True)
class PredictedUnitD:
    unit: str
    role: str
    target: tuple[float, ...]
    predictions: tuple[tuple[float, ...], ...]  # centroid, ridge, mlp order

    def __post_init__(self) -> None:
        if self.role not in {TRAIN_ROLE, HOLDOUT_ROLE}:
            raise ValueError("predicted unit role must be train or holdout")
        if len(self.predictions) != len(PREDICTOR_IDS):
            raise ValueError("every predictor vector is required")


@dataclass(frozen=True, slots=True)
class HallmarkPredictions:
    target_id: str
    target_sha256: str
    training: dict[str, Any]
    weights: dict[str, Any]
    split: dict[str, Any]
    dims: tuple[str, ...]
    units: tuple[PredictedUnitD, ...]
    predictions_digest: str

    def __post_init__(self) -> None:
        names = [unit.unit for unit in self.units]
        if len(names) != len(set(names)):
            raise ValueError("predicted unit names must be unique")
        for unit in self.units:
            if len(unit.target) != len(self.dims):
                raise ValueError(f"unit {unit.unit} target length disagrees with dims")
            for vector in unit.predictions:
                if len(vector) != len(self.dims):
                    raise ValueError(
                        f"unit {unit.unit} prediction length disagrees with dims"
                    )


def _vector_d(value: Any, *, name: str, dim: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != dim:
        raise ValueError(f"{name} must be a {dim}-element list")
    return tuple(finite(item, name=name) for item in value)


def load_hallmark_predictions(path: str | Path) -> HallmarkPredictions:
    predictions_path = Path(path)
    try:
        raw = json.loads(predictions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid predictions JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("predictions file must be a JSON object")
    _exact_keys(
        raw,
        {
            "schema_version",
            "target_id",
            "target_sha256",
            "training",
            "weights",
            "split",
            "dims",
            "units",
        },
        name="predictions",
    )
    if raw["schema_version"] != PREDICTIONS_SCHEMA_VERSION:
        raise ValueError("unsupported predictions schema")
    training = raw["training"]
    if not isinstance(training, dict):
        raise ValueError("training must be an object")
    _exact_keys(training, set(FROZEN_HALLMARK_TRAINING) | _TRAINING_EXTRA_KEYS, name="training")
    for key, expected in FROZEN_HALLMARK_TRAINING.items():
        if training[key] != expected:
            raise ValueError(
                f"frozen training parameter {key} disagrees: {training[key]!r} != {expected!r}"
            )
    required_text(training["torch_version"], name="training.torch_version")
    finite(training["final_train_loss_mse"], name="training.final_train_loss_mse")
    sha256_text(training["embedding_table_sha256"], name="training.embedding_table_sha256")
    for key in ("output_dim", "embedding_dim", "covered_units"):
        value = training[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"training.{key} must be a positive integer")
    excluded_units = training["excluded_units"]
    if isinstance(excluded_units, bool) or not isinstance(excluded_units, int) or excluded_units < 0:
        raise ValueError("training.excluded_units must be a non-negative integer")
    crosscheck = finite(
        training["centroid_crosscheck_max_abs_diff"],
        name="training.centroid_crosscheck_max_abs_diff",
    )
    if crosscheck >= PASS_EPSILON:
        raise ValueError("centroid cross-check exceeded the frozen tolerance")
    weights = raw["weights"]
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object")
    _exact_keys(weights, {"path", "sha256", "bytes"}, name="weights")
    required_text(weights["path"], name="weights.path")
    sha256_text(weights["sha256"], name="weights.sha256")
    if isinstance(weights["bytes"], bool) or not isinstance(weights["bytes"], int) or weights["bytes"] < 1:
        raise ValueError("weights.bytes must be a positive integer")
    split = raw["split"]
    if not isinstance(split, dict):
        raise ValueError("split must be an object")
    _exact_keys(split, {"salt", "train_units", "holdout_units"}, name="split")
    required_text(split["salt"], name="split.salt")
    for key in ("train_units", "holdout_units"):
        value = split[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"split.{key} must be a positive integer")
    dims_raw = raw["dims"]
    if not isinstance(dims_raw, list) or not dims_raw:
        raise ValueError("dims must be a non-empty list")
    dims = tuple(required_text(item, name="dims entry") for item in dims_raw)
    if len(dims) != len(set(dims)):
        raise ValueError("dims entries must be unique")
    if dims[-len(ABSTRACT_GENE_NAMES):] != ABSTRACT_GENE_NAMES:
        raise ValueError("dims must end with the frozen six-node order")
    if len(dims) != training["output_dim"]:
        raise ValueError("dims length disagrees with training.output_dim")
    units_raw = raw["units"]
    if not isinstance(units_raw, list) or not units_raw:
        raise ValueError("units must be a non-empty list")
    units = []
    for index, item in enumerate(units_raw):
        if not isinstance(item, dict):
            raise ValueError(f"units[{index}] must be an object")
        _exact_keys(
            item,
            {"unit", "role", "target", "centroid_pred", "ridge_pred", "mlp_pred"},
            name=f"units[{index}]",
        )
        units.append(
            PredictedUnitD(
                unit=required_text(item["unit"], name=f"units[{index}].unit"),
                role=required_text(item["role"], name=f"units[{index}].role"),
                target=_vector_d(item["target"], name=f"units[{index}].target", dim=len(dims)),
                predictions=(
                    _vector_d(item["centroid_pred"], name=f"units[{index}].centroid_pred", dim=len(dims)),
                    _vector_d(item["ridge_pred"], name=f"units[{index}].ridge_pred", dim=len(dims)),
                    _vector_d(item["mlp_pred"], name=f"units[{index}].mlp_pred", dim=len(dims)),
                ),
            )
        )
    return HallmarkPredictions(
        target_id=required_text(raw["target_id"], name="target_id"),
        target_sha256=sha256_text(raw["target_sha256"], name="target_sha256"),
        training=dict(training),
        weights=dict(weights),
        split=dict(split),
        dims=dims,
        units=tuple(units),
        predictions_digest=file_sha256(predictions_path),
    )


def _role_metrics(
    units: Sequence[PredictedUnitD], role: str, head: int
) -> dict[str, dict[str, float]]:
    selected = [unit for unit in units if unit.role == role]
    if not selected:
        raise ValueError(f"no {role} units present")
    summary: dict[str, dict[str, float]] = {}
    for predictor_index, predictor_id in enumerate(PREDICTOR_IDS):
        metrics = [
            vector_metrics_d(unit.predictions[predictor_index][-head:], unit.target[-head:])
            for unit in selected
        ]
        mean = mean_metrics_d(metrics)
        summary[predictor_id] = {
            "mae": mean.mae,
            "sign_agreement": mean.sign_agreement,
            "spearman": mean.spearman,
            "unit_count": len(selected),
        }
    return summary


def _set_dim_metrics(
    units: Sequence[PredictedUnitD], role: str, set_dim_count: int
) -> dict[str, dict[str, float]]:
    """Descriptive set-dimension mean MAE; never part of the pass gate."""
    selected = [unit for unit in units if unit.role == role]
    if not selected:
        raise ValueError(f"no {role} units present")
    summary: dict[str, dict[str, float]] = {}
    for predictor_index, predictor_id in enumerate(PREDICTOR_IDS):
        per_unit = [
            fmean(
                abs(p - t)
                for p, t in zip(
                    unit.predictions[predictor_index][:set_dim_count],
                    unit.target[:set_dim_count],
                    strict=True,
                )
            )
            for unit in selected
        ]
        summary[predictor_id] = {
            "mean_mae": fmean(per_unit),
            "unit_count": len(selected),
        }
    return summary


def evaluate_hallmark_training(
    predictions: HallmarkPredictions, target_path: str | Path
) -> dict[str, Any]:
    """Recompute every metric and apply the frozen ADR-0046 pass rule."""
    path = Path(target_path)
    if file_sha256(path) != predictions.target_sha256:
        raise ValueError("target SHA-256 disagrees with the predictions identity")
    target: HallmarkTarget = load_hallmark_target(path)
    if target.target_id != predictions.target_id:
        raise ValueError("target_id disagrees with the predictions identity")
    if target.dims != predictions.dims:
        raise ValueError("dims disagree with the target artifact")
    arm = ARM_BY_DATASET.get(target.dataset_id)
    if arm is None:
        raise ValueError(f"no frozen arm for dataset_id: {target.dataset_id}")

    target_units = {unit.unit: unit for unit in target.units}
    prediction_names = {unit.unit for unit in predictions.units}
    if not prediction_names <= set(target_units):
        raise ValueError("predictions contain units outside the target artifact")
    if len(prediction_names) != predictions.training["covered_units"]:
        raise ValueError("covered_units count disagrees with the unit list")

    # Train-only centroid: recomputed over the artifact's train rows, enforced
    # against both the embedded value and every claimed centroid prediction.
    train_rows = [unit for unit in target.units if target.roles[unit.unit] == TRAIN_ROLE]
    if not train_rows:
        raise ValueError("no train units to recompute the centroid")
    centroid = tuple(
        fmean(unit.target[index] for unit in train_rows) for index in range(len(target.dims))
    )
    if any(
        abs(a - b) >= PASS_EPSILON for a, b in zip(centroid, target.centroid, strict=True)
    ):
        raise ValueError("centroid_train_only disagrees with the target units")
    for unit in predictions.units:
        expected = target_units[unit.unit].target
        if unit.target != expected:
            raise ValueError(f"target vector tampered for unit {unit.unit}")
        if target.roles[unit.unit] != unit.role:
            raise ValueError(f"role tampered for unit {unit.unit}")
        if any(
            abs(a - b) >= PASS_EPSILON
            for a, b in zip(unit.predictions[0], centroid, strict=True)
        ):
            raise ValueError(f"centroid prediction tampered for unit {unit.unit}")

    head = len(ABSTRACT_GENE_NAMES)
    set_dim_count = len(target.dims) - head
    holdout = _role_metrics(predictions.units, HOLDOUT_ROLE, head)
    train = _role_metrics(predictions.units, TRAIN_ROLE, head)
    mae = {predictor: holdout[predictor]["mae"] for predictor in PREDICTOR_IDS}
    margin_centroid = mae["centroid"] - mae["mlp"]
    margin_ridge = mae["ridge"] - mae["mlp"]
    passed = margin_centroid > PASS_EPSILON and margin_ridge > PASS_EPSILON
    reasons = []
    if margin_centroid <= PASS_EPSILON:
        reasons.append("mlp does not beat the train-only centroid on holdout")
    if margin_ridge <= PASS_EPSILON:
        reasons.append("mlp does not beat ridge on holdout")
    if passed:
        reasons.append("mlp beats centroid and ridge on holdout beyond 1e-12")
    if arm == "descriptive":
        verdict = "descriptive"
        reasons.append("descriptive arm; no pass claim (ADR-0040 precedent)")
    else:
        verdict = "passed" if passed else "failed"

    content: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "target_id": predictions.target_id,
        "dataset_id": target.dataset_id,
        "arm": arm,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "source": {
            "predictions_sha256": predictions.predictions_digest,
            "target_sha256": predictions.target_sha256,
            "weights": predictions.weights,
        },
        "training": predictions.training,
        "split": predictions.split,
        "dims": list(predictions.dims),
        "metrics": {
            "six_node_head": {"train": train, "holdout": holdout},
            "set_dims": {
                "train": _set_dim_metrics(predictions.units, TRAIN_ROLE, set_dim_count),
                "holdout": _set_dim_metrics(predictions.units, HOLDOUT_ROLE, set_dim_count),
                "set_dim_count": set_dim_count,
            },
        },
        "pass_rule": {
            "rule": "holdout mlp six-node-head MAE strictly below centroid AND ridge, margins > 1e-12",
            "margin_vs_centroid": margin_centroid,
            "margin_vs_ridge": margin_ridge,
            "verdict": verdict,
            "reasons": reasons,
        },
    }
    content["evaluation_id"] = f"hallmark-training-eval-{digest_payload(content)[:16]}"
    return content


def save_hallmark_training_evaluation(
    evaluation: Mapping[str, Any], output_path: str | Path
) -> Path:
    """Write-once canonical save; a different existing file is refused."""
    return write_json_once(output_path, evaluation, artifact="hallmark training evaluation")
