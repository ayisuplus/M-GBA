"""Core verification segment for the ADR-0037 L0 training experiment.

Pure stdlib. Loads the ``mgba-l0-response-predictions-0.1`` file produced by
``scripts/train_l0_perturbation_response.py`` (independent venv only), verifies
it against the Stage 1 profile and the frozen hyperparameters, recomputes every
metric, and applies the pre-registered pass rule. The training script cannot
influence the verdict: it only supplies numbers; this module re-derives them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from .hashing import digest_payload
from .layers.l0 import ABSTRACT_GENE_NAMES
from .ocellus_anchors import mean_metrics, vector_metrics
from .validation import file_sha256, finite, required_text, sha256_text

PREDICTIONS_SCHEMA_VERSION = "mgba-l0-response-predictions-0.1"
EVALUATION_SCHEMA_VERSION = "mgba-l0-training-evaluation-0.1"
PASS_EPSILON = 1e-12

# Frozen by ADR-0037 before any training run.
FROZEN_TRAINING = {
    "seed": 42,
    "hidden": 32,
    "learning_rate": 1e-3,
    "weight_decay": 1e-4,
    "epochs": 3000,
    "ridge_lambda": 1.0,
    "device": "cpu-single-thread",
}
PREDICTOR_IDS = ("centroid", "ridge", "mlp")
TRAIN_ROLE = "train"
HOLDOUT_ROLE = "holdout"

ENCODING_ONEHOT = "identity-onehot"
ENCODING_EMBEDDING = "geneformer-embedding"
_LEGACY_TRAINING_EXTRA_KEYS = {"torch_version", "final_train_loss_mse", "component_vocab_size", "combo_units"}
_EMBEDDING_TRAINING_EXTRA_KEYS = {
    "torch_version",
    "final_train_loss_mse",
    "feature_encoding",
    "embedding_table_sha256",
    "embedding_dim",
    "covered_units",
    "excluded_units",
    "centroid_drift_vs_profile",
}

SCIENTIFIC_BOUNDARY = (
    "Offline evaluation of a small perturbation-response predictor against "
    "the Stage 1 empirical profile (Norman 2019, K562 CRISPRa). Predictions "
    "do not enter the runtime chain and are not a biological fit, a "
    "virtual-cell claim, or an efficacy predictor. Reference-model grade."
)








def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    keys = set(raw)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"{name} keys mismatch; missing={missing} extra={extra}")




def _vector6(value: Any, *, name: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != 6:
        raise ValueError(f"{name} must be a six-element list")
    return tuple(finite(item, name=name) for item in value)


@dataclass(frozen=True, slots=True)
class PredictedUnit:
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
class ResponsePredictions:
    profile_id: str
    profile_sha256: str
    training: dict[str, Any]
    weights: dict[str, Any]
    split: dict[str, Any]
    centroid_crosscheck_max_abs_diff: float
    units: tuple[PredictedUnit, ...]
    predictions_digest: str

    def __post_init__(self) -> None:
        names = [unit.unit for unit in self.units]
        if len(names) != len(set(names)):
            raise ValueError("predicted unit names must be unique")


def load_response_predictions(path: str | Path) -> ResponsePredictions:
    predictions_path = Path(path)
    try:
        raw = json.loads(predictions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid predictions JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("predictions file must be a JSON object")
    training_raw = raw.get("training")
    encoding = (
        training_raw.get("feature_encoding", ENCODING_ONEHOT)
        if isinstance(training_raw, dict)
        else None
    )
    if encoding == ENCODING_ONEHOT:
        top_keys = {
            "schema_version",
            "profile_id",
            "profile_sha256",
            "training",
            "weights",
            "split",
            "centroid_crosscheck_max_abs_diff",
            "units",
        }
    elif encoding == ENCODING_EMBEDDING:
        top_keys = {
            "schema_version",
            "profile_id",
            "profile_sha256",
            "training",
            "weights",
            "split",
            "units",
        }
    else:
        raise ValueError(f"unknown feature encoding: {encoding!r}")
    _exact_keys(raw, top_keys, name="predictions")
    if raw["schema_version"] != PREDICTIONS_SCHEMA_VERSION:
        raise ValueError("unsupported predictions schema")
    training = raw["training"]
    if not isinstance(training, dict):
        raise ValueError("training must be an object")
    extra_keys = (
        _LEGACY_TRAINING_EXTRA_KEYS
        if encoding == ENCODING_ONEHOT
        else _EMBEDDING_TRAINING_EXTRA_KEYS
    )
    _exact_keys(training, set(FROZEN_TRAINING) | extra_keys, name="training")
    for key, expected in FROZEN_TRAINING.items():
        if training[key] != expected:
            raise ValueError(
                f"frozen training parameter {key} disagrees: {training[key]!r} != {expected!r}"
            )
    required_text(training["torch_version"], name="training.torch_version")
    finite(training["final_train_loss_mse"], name="training.final_train_loss_mse")
    if encoding == ENCODING_ONEHOT:
        for key in ("component_vocab_size", "combo_units"):
            value = training[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"training.{key} must be a non-negative integer")
    else:
        sha256_text(
            training["embedding_table_sha256"], name="training.embedding_table_sha256"
        )
        for key in ("embedding_dim", "covered_units", "excluded_units"):
            value = training[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"training.{key} must be a non-negative integer")
        finite(
            training["centroid_drift_vs_profile"],
            name="training.centroid_drift_vs_profile",
        )
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
    if encoding == ENCODING_ONEHOT:
        crosscheck = finite(
            raw["centroid_crosscheck_max_abs_diff"], name="centroid_crosscheck_max_abs_diff"
        )
        if crosscheck >= PASS_EPSILON:
            raise ValueError("centroid cross-check exceeded the frozen tolerance")
    else:
        # Embedding arms exclude unmapped units, so the all-units profile centroid
        # is not the right reference; the covered-train centroid is recomputed and
        # enforced inside evaluate_training. The reported drift is carried through.
        crosscheck = finite(
            training["centroid_drift_vs_profile"],
            name="training.centroid_drift_vs_profile",
        )
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
            PredictedUnit(
                unit=required_text(item["unit"], name=f"units[{index}].unit"),
                role=required_text(item["role"], name=f"units[{index}].role"),
                target=_vector6(item["target"], name=f"units[{index}].target"),
                predictions=(
                    _vector6(item["centroid_pred"], name=f"units[{index}].centroid_pred"),
                    _vector6(item["ridge_pred"], name=f"units[{index}].ridge_pred"),
                    _vector6(item["mlp_pred"], name=f"units[{index}].mlp_pred"),
                ),
            )
        )
    training = dict(training)
    training["feature_encoding"] = encoding
    return ResponsePredictions(
        profile_id=required_text(raw["profile_id"], name="profile_id"),
        profile_sha256=sha256_text(raw["profile_sha256"], name="profile_sha256"),
        training=dict(training),
        weights=dict(weights),
        split=dict(split),
        centroid_crosscheck_max_abs_diff=crosscheck,
        units=tuple(units),
        predictions_digest=file_sha256(predictions_path),
    )


def _named(vector: Sequence[float]) -> tuple[tuple[str, float], ...]:
    return tuple(zip(ABSTRACT_GENE_NAMES, vector, strict=True))


def _role_metrics(
    units: Sequence[PredictedUnit], role: str
) -> dict[str, dict[str, float]]:
    selected = [unit for unit in units if unit.role == role]
    if not selected:
        raise ValueError(f"no {role} units present")
    summary: dict[str, dict[str, float]] = {}
    for predictor_index, predictor_id in enumerate(PREDICTOR_IDS):
        metrics = [
            vector_metrics(_named(unit.predictions[predictor_index]), _named(unit.target))
            for unit in selected
        ]
        mean = mean_metrics(metrics)
        summary[predictor_id] = {
            "six_node_mae": mean.six_node_mae,
            "sign_agreement": mean.sign_agreement,
            "spearman": mean.spearman,
            "unit_count": len(selected),
        }
    return summary


def evaluate_training(
    predictions: ResponsePredictions, profile_path: str | Path
) -> dict[str, Any]:
    """Recompute every metric and apply the frozen ADR-0037 pass rule."""
    path = Path(profile_path)
    if file_sha256(path) != predictions.profile_sha256:
        raise ValueError("profile SHA-256 disagrees with the predictions identity")
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != predictions.profile_id:
        raise ValueError("profile_id disagrees with the predictions identity")
    profile_units = {unit["unit"]: unit for unit in profile["units"]}
    encoding = predictions.training["feature_encoding"]
    prediction_names = {unit.unit for unit in predictions.units}
    if encoding == ENCODING_ONEHOT:
        if set(profile_units) != prediction_names:
            raise ValueError("predictions and profile cover different units")
    else:
        if not prediction_names <= set(profile_units):
            raise ValueError("embedding predictions contain units outside the profile")
        if len(prediction_names) != predictions.training["covered_units"]:
            raise ValueError("covered_units count disagrees with the unit list")
    if encoding == ENCODING_ONEHOT:
        centroid_vector = tuple(
            finite(profile["centroid_train_only"][node], name="profile centroid")
            for node in ABSTRACT_GENE_NAMES
        )
    else:
        # Recompute the covered-train centroid from profile targets (fail-closed).
        covered_train = [
            name
            for name in prediction_names
            if profile_units[name]["role"] == TRAIN_ROLE
        ]
        if not covered_train:
            raise ValueError("no covered train units to recompute the centroid")
        centroid_vector = tuple(
            fmean(
                finite(profile_units[name]["six_node_vector"][node], name="target")
                for name in covered_train
            )
            for node in ABSTRACT_GENE_NAMES
        )
    for unit in predictions.units:
        expected = tuple(
            finite(profile_units[unit.unit]["six_node_vector"][node], name="target")
            for node in ABSTRACT_GENE_NAMES
        )
        if unit.target != expected:
            raise ValueError(f"target vector tampered for unit {unit.unit}")
        if profile_units[unit.unit]["role"] != unit.role:
            raise ValueError(f"role tampered for unit {unit.unit}")
        centroid_pred = unit.predictions[0]
        if any(
            abs(a - b) >= PASS_EPSILON for a, b in zip(centroid_pred, centroid_vector)
        ):
            raise ValueError(f"centroid prediction tampered for unit {unit.unit}")

    holdout = _role_metrics(predictions.units, HOLDOUT_ROLE)
    train = _role_metrics(predictions.units, TRAIN_ROLE)
    mae = {predictor: holdout[predictor]["six_node_mae"] for predictor in PREDICTOR_IDS}
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

    content: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "profile_id": predictions.profile_id,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "source": {
            "predictions_sha256": predictions.predictions_digest,
            "profile_sha256": predictions.profile_sha256,
            "weights": predictions.weights,
        },
        "training": predictions.training,
        "split": predictions.split,
        "metrics": {"train": train, "holdout": holdout},
        "pass_rule": {
            "rule": "holdout mlp MAE strictly below centroid AND ridge, margins > 1e-12",
            "margin_vs_centroid": margin_centroid,
            "margin_vs_ridge": margin_ridge,
            "verdict": "passed" if passed else "failed",
            "reasons": reasons,
        },
    }
    content["evaluation_id"] = f"l0-training-eval-{digest_payload(content)[:16]}"
    return content


def save_training_evaluation(evaluation: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write-once save; existing output is never overwritten."""
    output = Path(output_path)
    if output.exists():
        raise ValueError(f"refusing to overwrite existing evaluation: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(evaluation), indent=2), encoding="utf-8")
    return output
