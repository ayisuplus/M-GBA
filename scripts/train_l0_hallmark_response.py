#!/usr/bin/env python
"""ADR-0046 training segment: gene-embedding features -> Hallmark 56-dim target.

Runs ONLY in the independent training venv (``.venv-train``) with torch. Same
frozen protocol as ADR-0037/0040 (optimizer/loss/epochs/seed/CPU single-thread,
Geneformer 768-d input token embeddings, mean-pooled over components for
combos); the only frozen difference is the supervision target: the
``mgba-hallmark-target-0.1`` artifact (covered Hallmark sets + frozen six-node
union head) instead of the six-node profile vector. Units whose components are
not all resolved are excluded (fail-closed, counted in the report). Roles are
inherited verbatim from the target artifact (which copied the profile split).
The centroid predictor is the target's embedded ``centroid_train_only``
(all-train rows), cross-checked at 1e-12 by recomputation. The verdict is NOT
computed here; the core evaluation segment re-derives everything.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import torch

PREDICTIONS_SCHEMA_VERSION = "mgba-l0-hallmark-predictions-0.1"
TARGET_SCHEMA_VERSION = "mgba-hallmark-target-0.1"

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


def train(target_path: Path, embeddings_path: Path, weights_out: Path) -> dict:
    target = json.loads(target_path.read_text(encoding="utf-8"))
    if target.get("schema_version") != TARGET_SCHEMA_VERSION:
        raise ValueError("unsupported hallmark target schema")
    table = json.loads(embeddings_path.read_text(encoding="utf-8"))
    if table.get("schema_version") != "mgba-gene-embedding-table-0.1":
        raise ValueError("unsupported embedding table schema")
    embeddings = table["embeddings"]
    dim = int(table["embedding_dim"])

    dims = list(target["dims"])
    output_dim = len(dims)
    roles = target["roles"]
    all_units = target["units"]

    covered: list[dict] = []
    excluded: list[str] = []
    for unit in all_units:
        parts = unit["unit"].split("_")
        if all(part in embeddings for part in parts):
            covered.append(unit)
        else:
            excluded.append(unit["unit"])
    if not covered:
        raise ValueError("no unit has a fully resolved embedding")

    names = [unit["unit"] for unit in covered]

    def _feature(unit_name: str) -> np.ndarray:
        parts = unit_name.split("_")
        vectors = [np.asarray(embeddings[part], dtype=np.float64) for part in parts]
        return np.mean(vectors, axis=0)

    features = np.stack([_feature(name) for name in names])
    targets = np.array(
        [[unit["target"][d] for d in dims] for unit in covered],
        dtype=np.float64,
    )
    train_mask = np.array([roles[name] == "train" for name in names])
    x_train = features[train_mask]
    y_train = targets[train_mask]

    # Centroid cross-check: the embedded centroid spans ALL train rows of the
    # target artifact (the builder does not know embedding coverage); recompute
    # from the artifact's own train rows and enforce the frozen 1e-12 identity.
    all_targets = np.array(
        [[unit["target"][d] for d in dims] for unit in all_units],
        dtype=np.float64,
    )
    all_train_mask = np.array([roles[unit["unit"]] == "train" for unit in all_units])
    centroid_recomputed = all_targets[all_train_mask].mean(axis=0)
    centroid = np.array([target["centroid_train_only"][d] for d in dims], dtype=np.float64)
    centroid_crosscheck = float(np.abs(centroid_recomputed - centroid).max())
    if centroid_crosscheck >= CENTROID_TOLERANCE:
        raise ValueError(
            f"centroid cross-check exceeded {CENTROID_TOLERANCE}: {centroid_crosscheck}"
        )

    gram = x_train.T @ x_train + RIDGE_LAMBDA * np.eye(x_train.shape[1])
    ridge_weights = np.linalg.solve(gram, x_train.T @ y_train)
    ridge_pred = features @ ridge_weights

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    torch.set_num_threads(1)
    model = torch.nn.Sequential(
        torch.nn.Linear(features.shape[1], HIDDEN),
        torch.nn.Tanh(),
        torch.nn.Linear(HIDDEN, output_dim),
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
        **{name: tensor.detach().numpy() for name, tensor in model.state_dict().items()},
    )

    centroid_pred = np.broadcast_to(centroid, targets.shape)
    units = []
    for row, unit in enumerate(covered):
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
        "target_id": target["target_id"],
        "target_sha256": _sha256_file(target_path),
        "training": {
            "seed": SEED,
            "hidden": HIDDEN,
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "epochs": EPOCHS,
            "ridge_lambda": RIDGE_LAMBDA,
            "device": "cpu-single-thread",
            "input_dim": dim,
            "output_dim": output_dim,
            "torch_version": torch.__version__,
            "final_train_loss_mse": final_loss,
            "embedding_table_sha256": _sha256_file(embeddings_path),
            "embedding_dim": dim,
            "covered_units": len(covered),
            "excluded_units": len(excluded),
            "centroid_crosscheck_max_abs_diff": centroid_crosscheck,
        },
        "weights": {
            "path": weights_out.name,
            "sha256": _sha256_file(weights_out),
            "bytes": weights_out.stat().st_size,
        },
        "split": {
            "salt": target["split"]["salt"],
            "train_units": int(train_mask.sum()),
            "holdout_units": int((~train_mask).sum()),
        },
        "dims": dims,
        "units": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="hallmark target JSON")
    parser.add_argument("--embeddings", required=True, help="gene embedding table JSON")
    parser.add_argument("--output", required=True, help="predictions JSON output")
    parser.add_argument("--weights-out", required=True, help="MLP weights .npz output")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing predictions: {output}")
    result = train(Path(args.target), Path(args.embeddings), Path(args.weights_out))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "target_id": result["target_id"],
                "units": len(result["units"]),
                "covered_units": result["training"]["covered_units"],
                "excluded_units": result["training"]["excluded_units"],
                "output_dim": result["training"]["output_dim"],
                "final_train_loss_mse": result["training"]["final_train_loss_mse"],
                "centroid_crosscheck_max_abs_diff": result["training"][
                    "centroid_crosscheck_max_abs_diff"
                ],
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
