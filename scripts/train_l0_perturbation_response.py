#!/usr/bin/env python
"""ADR-0037 training segment: perturbation identity -> six-node response.

Runs ONLY in the independent training venv (``.venv-train``) with torch; the
core package never imports torch. Everything is frozen by ADR-0037 before any
training: feature encoding, model sizes, hyperparameters, CPU single-thread
determinism, and the same digest split as Stage 1. Holdout units never touch
training, model selection, or early stopping (there is none).

Outputs ``mgba-l0-response-predictions-0.1`` (all three predictors' vectors
for every unit, plus training provenance); the frozen verdict is computed by
the core module, not here. Weights land in ``models/`` (never committed).
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import torch

from mgba.layers.l0 import ABSTRACT_GENE_NAMES
from mgba.perturbation_anchors import assign_splits

PREDICTIONS_SCHEMA_VERSION = "mgba-l0-response-predictions-0.1"

SEED = 42
HIDDEN = 32
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 3000
RIDGE_LAMBDA = 1.0
CENTROID_TOLERANCE = 1e-12


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


def train(profile_path: Path, weights_out: Path) -> dict:
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

    # Baseline 1: train-only centroid, with the frozen cross-check.
    centroid = y_train.mean(axis=0)
    profile_centroid = np.array(
        [profile["centroid_train_only"][node] for node in ABSTRACT_GENE_NAMES]
    )
    centroid_diff = float(np.abs(centroid - profile_centroid).max())
    if centroid_diff >= CENTROID_TOLERANCE:
        raise ValueError(f"centroid cross-check failed: {centroid_diff}")

    # Baseline 2: closed-form ridge, lambda frozen, no intercept.
    gram = x_train.T @ x_train + RIDGE_LAMBDA * np.eye(x_train.shape[1])
    ridge_weights = np.linalg.solve(gram, x_train.T @ y_train)
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
    y_t = torch.tensor(y_train, dtype=torch.float32)
    model.train()
    for _epoch in range(EPOCHS):
        optimizer.zero_grad()
        loss = torch.nn.functional.mse_loss(model(x_t), y_t)
        loss.backward()
        optimizer.step()
    final_loss = float(loss.detach())
    model.eval()
    with torch.no_grad():
        mlp_pred = model(torch.tensor(features, dtype=torch.float32)).numpy().astype(np.float64)

    weights_out.parent.mkdir(parents=True, exist_ok=True)
    if weights_out.exists():
        raise ValueError(f"refusing to overwrite existing weights: {weights_out}")
    # np.savez writes a fixed (1980-01-01) zip timestamp, so identical seeds
    # produce byte-identical weights; torch.save embeds wall-clock metadata.
    np.savez(
        weights_out,
        **{
            name: tensor.detach().numpy()
            for name, tensor in model.state_dict().items()
        },
    )

    centroid_pred = np.broadcast_to(centroid, targets.shape)
    units = []
    for row, unit in enumerate(profile_units):
        units.append(
            {
                "unit": unit["unit"],
                "role": roles[unit["unit"]],
                "target": [float(v) for v in targets[row]],
                "centroid_pred": [float(v) for v in centroid_pred[row]],
                "ridge_pred": [float(v) for v in ridge_pred[row]],
                "mlp_pred": [float(v) for v in mlp_pred[row]],
            }
        )
    return {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "profile_id": profile["profile_id"],
        "profile_sha256": _sha256_file(profile_path),
        "training": {
            "seed": SEED,
            "hidden": HIDDEN,
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "epochs": EPOCHS,
            "ridge_lambda": RIDGE_LAMBDA,
            "device": "cpu-single-thread",
            "torch_version": torch.__version__,
            "final_train_loss_mse": final_loss,
            "component_vocab_size": len(components),
            "combo_units": combo_units,
        },
        "weights": {
            "path": weights_out.name,
            "sha256": _sha256_file(weights_out),
            "bytes": weights_out.stat().st_size,
        },
        "split": {
            "salt": profile["split"]["salt"],
            "train_units": int(train_mask.sum()),
            "holdout_units": int((~train_mask).sum()),
        },
        "centroid_crosscheck_max_abs_diff": centroid_diff,
        "units": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Stage 1 perturbation profile JSON")
    parser.add_argument("--output", required=True, help="predictions JSON output")
    parser.add_argument(
        "--weights-out",
        default="models/l0_response_mlp.pt",
        help="MLP weights output (models/, never committed)",
    )
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing predictions: {output}")
    result = train(Path(args.profile), Path(args.weights_out))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "units": len(result["units"]),
                "component_vocab_size": result["training"]["component_vocab_size"],
                "final_train_loss_mse": result["training"]["final_train_loss_mse"],
                "centroid_crosscheck_max_abs_diff": result[
                    "centroid_crosscheck_max_abs_diff"
                ],
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
