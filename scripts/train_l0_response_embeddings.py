#!/usr/bin/env python
"""ADR-0040 training segment: gene-embedding features -> six-node response.

Runs ONLY in the independent training venv (``.venv-train``) with torch. Same
frozen protocol as ADR-0037 (optimizer/loss/epochs/seed/CPU single-thread);
the only frozen difference is the input encoding: 768-d Geneformer token
embeddings (mean-pooled over components for combos). Units whose components
are not all resolved are excluded (fail-closed, counted in the report).
Split: the profile's own digest salt via ``assign_splits``.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import torch

from mgba.layers.l0 import ABSTRACT_GENE_NAMES

PREDICTIONS_SCHEMA_VERSION = "mgba-l0-response-predictions-0.1"
FEATURE_ENCODING = "geneformer-embedding"

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


def train(profile_path: Path, embeddings_path: Path, weights_out: Path) -> dict:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    table = json.loads(embeddings_path.read_text(encoding="utf-8"))
    if table.get("schema_version") != "mgba-gene-embedding-table-0.1":
        raise ValueError("unsupported embedding table schema")
    embeddings = table["embeddings"]
    dim = int(table["embedding_dim"])

    covered: list[dict] = []
    excluded: list[str] = []
    for unit in profile["units"]:
        parts = unit["unit"].split("_")
        if all(part in embeddings for part in parts):
            covered.append(unit)
        else:
            excluded.append(unit["unit"])
    if not covered:
        raise ValueError("no unit has a fully resolved embedding")

    # Roles come from the profile's frozen split over ALL units (restricted to
    # covered units); re-splitting the covered subset would change the
    # partition and break comparability with the ADR-0039 run.
    roles = {unit["unit"]: unit["role"] for unit in profile["units"]}
    names = [unit["unit"] for unit in covered]

    def _feature(unit_name: str) -> np.ndarray:
        parts = unit_name.split("_")
        vectors = [np.asarray(embeddings[part], dtype=np.float64) for part in parts]
        return np.mean(vectors, axis=0)

    features = np.stack([_feature(name) for name in names])
    targets = np.array(
        [[unit["six_node_vector"][node] for node in ABSTRACT_GENE_NAMES] for unit in covered],
        dtype=np.float64,
    )
    train_mask = np.array([roles[name] == "train" for name in names])
    x_train = features[train_mask]
    y_train = targets[train_mask]

    centroid = y_train.mean(axis=0)
    profile_centroid = np.array(
        [profile["centroid_train_only"][node] for node in ABSTRACT_GENE_NAMES]
    )
    # Cross-check against the profile centroid over the COVERED train units only;
    # the profile centroid spans all units, so recompute is expected to differ
    # slightly — report the drift instead of asserting byte equality.
    centroid_drift = float(np.abs(centroid - profile_centroid).max())

    gram = x_train.T @ x_train + RIDGE_LAMBDA * np.eye(x_train.shape[1])
    ridge_weights = np.linalg.solve(gram, x_train.T @ y_train)
    ridge_pred = features @ ridge_weights

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
            "feature_encoding": FEATURE_ENCODING,
            "embedding_table_sha256": _sha256_file(embeddings_path),
            "embedding_dim": dim,
            "covered_units": len(covered),
            "excluded_units": len(excluded),
            "centroid_drift_vs_profile": centroid_drift,
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
        "units": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="perturbation profile JSON")
    parser.add_argument("--embeddings", required=True, help="gene embedding table JSON")
    parser.add_argument("--output", required=True, help="predictions JSON output")
    parser.add_argument("--weights-out", required=True, help="MLP weights .npz output")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing predictions: {output}")
    result = train(Path(args.profile), Path(args.embeddings), Path(args.weights_out))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "units": len(result["units"]),
                "covered_units": result["training"]["covered_units"],
                "excluded_units": result["training"]["excluded_units"],
                "final_train_loss_mse": result["training"]["final_train_loss_mse"],
                "centroid_drift_vs_profile": result["training"]["centroid_drift_vs_profile"],
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
