#!/usr/bin/env python
"""ADR-0048 control 1 (label-shuffle): ADR-0037 retrained on shuffled labels.

Runs ONLY in the independent training venv (``.venv-train``) with torch.
Identical to ``train_l0_perturbation_response.py`` except that the TRAIN
split's perturbation->response labels are permuted before any fitting, via
the deterministic sha256 derivation frozen in ADR-0048 section 3.1:

    key_i = sha256("mgba-adr-0048-label-shuffle-v1|<profile_sha256>|<unit_i>")
    sigma = argsort(key_i ascending)   (a permutation of the 188 train rows)
    shuffled_target[i] = original_target[sigma[i]]

Features, split, roles, holdout, hyperparameters (SEED=42, HIDDEN=32,
lr=1e-3, weight_decay=1e-4, full-batch MSE, EPOCHS=3000, ridge lambda=1.0,
CPU single thread) are reused verbatim from ADR-0037. The centroid
cross-check must still pass because a permutation preserves the train mean.

Pre-registered criterion: on shuffled labels the MLP's holdout six-node MAE
must NO LONGER beat both the centroid and ridge baselines with margins
>1e-12; if it still does, ADR-0037's pass gate is vacuous and that negative
result is recorded as-is.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np
import torch

from mgba.layers.l0 import ABSTRACT_GENE_NAMES
from mgba.perturbation_anchors import assign_splits

SCHEMA_VERSION = "mgba-falsification-control-0.1"
CONTROL_ID = "label-shuffle"
SHUFFLE_SALT = "mgba-adr-0048-label-shuffle-v1"

# Frozen ADR-0037 hyperparameters (verbatim; never adjusted for this control).
SEED = 42
HIDDEN = 32
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 3000
RIDGE_LAMBDA = 1.0
CENTROID_TOLERANCE = 1e-12
PASS_EPSILON = 1e-12

SCIENTIFIC_BOUNDARY = (
    "阴性对照：检验评估管线在无信号输入下是否假阳性；不构成对任何生物主张的"
    "支持或否定，不撤销历史 verdict，仅标定其证据等级"
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encode(units: list[str]) -> tuple[np.ndarray, list[str], int]:
    components = sorted({part for unit in units for part in unit.split("_")})
    index = {name: position for position, name in enumerate(components)}
    features = np.zeros((len(units), len(components) + 1), dtype=np.float64)
    combo_units = 0
    for row, unit in enumerate(units):
        parts = unit.split("_")
        if len(parts) > 1:
            combo_units += 1
        for part in parts:
            features[row, index[part]] += 1.0 / len(parts)
        features[row, -1] = 1.0 if len(parts) > 1 else 0.0
    return features, components, combo_units


def _shuffle_permutation(train_names: list[str], profile_sha256: str) -> list[int]:
    """ADR-0048 frozen derivation: argsort of sha256 keys over train units."""
    keys = [
        sha256(f"{SHUFFLE_SALT}|{profile_sha256}|{name}".encode("utf-8")).hexdigest()
        for name in train_names
    ]
    return sorted(range(len(train_names)), key=lambda i: keys[i])


def run(profile_path: Path, output_dir: Path, epochs: int) -> dict:
    profile_sha256 = _sha256_file(profile_path)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_units = profile["units"]
    names = [unit["unit"] for unit in profile_units]
    roles = assign_splits(names, salt=profile["split"]["salt"])
    for unit in profile_units:
        if roles[unit["unit"]] != unit["role"]:
            raise ValueError(f"profile role disagrees with frozen split: {unit['unit']}")

    targets = np.array(
        [[unit["six_node_vector"][node] for node in ABSTRACT_GENE_NAMES] for unit in profile_units],
        dtype=np.float64,
    )
    features, components, combo_units = _encode(names)
    train_mask = np.array([roles[name] == "train" for name in names])
    x_train = features[train_mask]
    y_train = targets[train_mask]

    # The single difference from ADR-0037: deterministic label permutation
    # over the 188 train rows (features and holdout untouched).
    train_names = [name for name, is_train in zip(names, train_mask) if is_train]
    sigma = _shuffle_permutation(train_names, profile_sha256)
    if sorted(sigma) != list(range(len(train_names))):
        raise ValueError("shuffle derivation did not produce a permutation")
    if sigma == list(range(len(train_names))):
        raise ValueError("shuffle derivation produced the identity permutation")
    y_train_shuffled = y_train[np.array(sigma)]

    # Baseline 1: train-only centroid of the SHUFFLED labels (a permutation
    # preserves the mean, so the frozen 1e-12 cross-check must still pass).
    centroid = y_train_shuffled.mean(axis=0)
    profile_centroid = np.array(
        [profile["centroid_train_only"][node] for node in ABSTRACT_GENE_NAMES]
    )
    centroid_diff = float(np.abs(centroid - profile_centroid).max())
    if centroid_diff >= CENTROID_TOLERANCE:
        raise ValueError(f"centroid cross-check failed: {centroid_diff}")

    # Baseline 2: closed-form ridge on shuffled labels, lambda frozen.
    gram = x_train.T @ x_train + RIDGE_LAMBDA * np.eye(x_train.shape[1])
    ridge_weights = np.linalg.solve(gram, x_train.T @ y_train_shuffled)
    ridge_pred = features @ ridge_weights

    # Candidate: seeded MLP on single-thread CPU for bit determinism.
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    torch.set_num_threads(1)
    model = torch.nn.Sequential(
        torch.nn.Linear(features.shape[1], HIDDEN),
        torch.nn.Tanh(),
        torch.nn.Linear(HIDDEN, len(ABSTRACT_GENE_NAMES)),
    )
    optimizer = torch.optim.Adam(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    x_t = torch.tensor(x_train, dtype=torch.float32)
    y_t = torch.tensor(y_train_shuffled, dtype=torch.float32)
    model.train()
    for _epoch in range(epochs):
        optimizer.zero_grad()
        loss = torch.nn.functional.mse_loss(model(x_t), y_t)
        loss.backward()
        optimizer.step()
    final_loss = float(loss.detach())
    model.eval()
    with torch.no_grad():
        mlp_pred = model(torch.tensor(features, dtype=torch.float32)).numpy().astype(np.float64)

    output_dir.mkdir(parents=True, exist_ok=True)
    weights_path = output_dir / "weights.npz"
    if weights_path.exists():
        raise ValueError(f"refusing to overwrite existing weights: {weights_path}")
    np.savez(
        weights_path,
        **{name: tensor.detach().numpy() for name, tensor in model.state_dict().items()},
    )

    # In-script evaluation (identical MAE definition as the core evaluator):
    # six-node MAE over holdout units, margins against both baselines.
    holdout_mask = ~train_mask
    holdout_targets = targets[holdout_mask]
    centroid_pred = np.broadcast_to(centroid, targets.shape)
    mae = {
        "centroid": float(np.abs(centroid_pred[holdout_mask] - holdout_targets).mean()),
        "ridge": float(np.abs(ridge_pred[holdout_mask] - holdout_targets).mean()),
        "mlp": float(np.abs(mlp_pred[holdout_mask] - holdout_targets).mean()),
    }
    margin_vs_centroid = mae["centroid"] - mae["mlp"]
    margin_vs_ridge = mae["ridge"] - mae["mlp"]
    adr0037_rule_holds = (
        margin_vs_centroid > PASS_EPSILON and margin_vs_ridge > PASS_EPSILON
    )
    verdict = "criteria_not_met" if adr0037_rule_holds else "criteria_met"

    return {
        "schema_version": SCHEMA_VERSION,
        "control_id": CONTROL_ID,
        "adr": "ADR-0048",
        "created_date": "2026-09-11",
        "status": "completed" if epochs == EPOCHS else "incomplete",
        "inputs": [
            {
                "path": "data/aivc/derived/norman-perturbation-profile.json",
                "sha256": profile_sha256,
                "role": "frozen ADR-0036 profile (236 units, train 188 / holdout 48)",
            },
            {
                "path": "scripts/train_l0_perturbation_response.py",
                "sha256": _sha256_file(Path("scripts/train_l0_perturbation_response.py")),
                "role": "ADR-0037 original training script (structure reused verbatim)",
            },
        ],
        "derivation": {
            "rule": (
                "key_i = sha256('mgba-adr-0048-label-shuffle-v1|<profile_sha256>|<unit_i>'); "
                "sigma = argsort(key_i ascending) over the 188 train rows in profile order; "
                "shuffled_target[i] = original_target[sigma[i]]"
            ),
            "salt": SHUFFLE_SALT,
            "profile_sha256": profile_sha256,
            "permutation_first8": sigma[:8],
            "moved_rows": int(sum(1 for i, j in enumerate(sigma) if i != j)),
            "train_rows": len(train_names),
        },
        "criteria": {
            "text": (
                "打乱后 MLP 的 holdout 六节点 MAE 对质心与 ridge 的双胜 margin 必须不再"
                "同时 >1e-12（ADR-0037 通过规则在打乱数据上不成立）；若仍成立则 ADR-0037 "
                "passed 判为 vacuous 并如实记录"
            ),
            "pass_epsilon": PASS_EPSILON,
        },
        "anchors": {
            "centroid_crosscheck_max_abs_diff": centroid_diff,
            "centroid_crosscheck_tolerance": CENTROID_TOLERANCE,
            "adr0037_reference_holdout_mae": {
                "centroid": 0.012872174640087454,
                "ridge": 0.012279782258477557,
                "mlp": 0.009494280866924337,
            },
        },
        "results": {
            "training": {
                "seed": SEED,
                "hidden": HIDDEN,
                "learning_rate": LEARNING_RATE,
                "weight_decay": WEIGHT_DECAY,
                "epochs_requested": EPOCHS,
                "epochs_run": epochs,
                "ridge_lambda": RIDGE_LAMBDA,
                "device": "cpu-single-thread",
                "torch_version": torch.__version__,
                "final_train_loss_mse": final_loss,
                "component_vocab_size": len(components),
                "combo_units": combo_units,
            },
            "split": {
                "salt": profile["split"]["salt"],
                "train_units": int(train_mask.sum()),
                "holdout_units": int(holdout_mask.sum()),
            },
            "holdout_six_node_mae": mae,
            "margin_vs_centroid": margin_vs_centroid,
            "margin_vs_ridge": margin_vs_ridge,
            "adr0037_pass_rule_holds_on_shuffled": adr0037_rule_holds,
            "weights": {
                "path": "weights.npz",
                "sha256": _sha256_file(weights_path),
                "bytes": weights_path.stat().st_size,
            },
        },
        "verdict": verdict,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def write_manifest(output_dir: Path, second_dir: Path | None) -> None:
    entries = []
    for rel in ("results.json", "weights.npz"):
        path = output_dir / rel
        entries.append(
            {"path": rel, "sha256": _sha256_file(path), "bytes": path.stat().st_size}
        )
    script_path = Path(__file__).resolve()
    entries.append(
        {
            "path": f"scripts/{script_path.name}",
            "sha256": _sha256_file(script_path),
            "bytes": script_path.stat().st_size,
        }
    )
    determinism = None
    if second_dir is not None:
        determinism = {
            "run1_results_sha256": _sha256_file(output_dir / "results.json"),
            "run2_results_sha256": _sha256_file(second_dir / "results.json"),
            "run1_weights_sha256": _sha256_file(output_dir / "weights.npz"),
            "run2_weights_sha256": _sha256_file(second_dir / "weights.npz"),
            "byte_identical": (
                _sha256_file(output_dir / "results.json")
                == _sha256_file(second_dir / "results.json")
                and _sha256_file(output_dir / "weights.npz")
                == _sha256_file(second_dir / "weights.npz")
            ),
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "control_id": CONTROL_ID,
        "kind": "manifest",
        "entries": entries,
        "determinism": determinism,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="data/aivc/derived/norman-perturbation-profile.json")
    parser.add_argument("--output-dir", required=True, help="control artifact directory")
    parser.add_argument(
        "--second-run-dir",
        default=None,
        help="directory of an independent second run for the byte-identity check",
    )
    parser.add_argument(
        "--smoke-epochs",
        type=int,
        default=None,
        help="verification-only epoch override; the registered run always uses 3000",
    )
    args = parser.parse_args()
    epochs = args.smoke_epochs if args.smoke_epochs is not None else EPOCHS
    if args.smoke_epochs is not None and "falsification" in args.output_dir.replace("\\", "/"):
        raise SystemExit("smoke runs must not write into artifacts/falsification/")
    output_dir = Path(args.output_dir)
    results_path = output_dir / "results.json"
    if results_path.exists():
        raise SystemExit(f"refusing to overwrite existing results: {results_path}")
    result = run(Path(args.profile), output_dir, epochs)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_manifest(
        output_dir, Path(args.second_run_dir) if args.second_run_dir else None
    )
    print(
        json.dumps(
            {
                "control_id": result["control_id"],
                "verdict": result["verdict"],
                "holdout_six_node_mae": result["results"]["holdout_six_node_mae"],
                "margin_vs_centroid": result["results"]["margin_vs_centroid"],
                "margin_vs_ridge": result["results"]["margin_vs_ridge"],
                "epochs_run": result["results"]["training"]["epochs_run"],
                "final_train_loss_mse": result["results"]["training"]["final_train_loss_mse"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
