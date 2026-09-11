#!/usr/bin/env python
"""ADR-0049: component-disjoint restratification of the ADR-0037 OE result.

Runs ONLY in the independent training venv (``.venv-train``) with torch.
The training segment is line-for-line identical to ADR-0037's
``train_l0_perturbation_response.py`` (same frozen split, same feature
encoding, SEED=42, HIDDEN=32, lr=1e-3, weight_decay=1e-4, full-batch MSE,
EPOCHS=3000, ridge lambda=1.0, CPU single thread). The ONLY difference is
the evaluation: holdout units are restratified by whether every component
of the unit appeared among the 188 frozen TRAIN units (ADR-0049 section
3.1, deterministic, no hand-picking):

    train_vocab = union of parts(u) over the 188 train units
    component-seen  (interpolation): all parts(u) in train_vocab
    component-unseen (extrapolation): at least one part(u) not in train_vocab

Pre-registered criterion (ADR-0049 section 3.3): on the component-unseen
holdout subset (n >= 8), the MLP's six-node MAE must be strictly below BOTH
the centroid and ridge baselines with margins > 1e-12 -> ``passed``;
otherwise ``failed``; if n < 8 -> ``insufficient``.

Control anchor (section 3.4): the three models' MAE on the FULL 48-unit
holdout must match ADR-0037's historical values within 1e-6; any breach
means pipeline drift and the run must stop before registering results.
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

SCHEMA_VERSION = "mgba-extrapolation-boundary-0.1"

# Frozen ADR-0037 hyperparameters (verbatim; never adjusted).
SEED = 42
HIDDEN = 32
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 3000
RIDGE_LAMBDA = 1.0
CENTROID_TOLERANCE = 1e-12
PASS_EPSILON = 1e-12
ANCHOR_TOLERANCE = 1e-6
MIN_UNSEEN_UNITS = 8

# ADR-0037 historical full-holdout values (control anchor, NOT retrained here).
ADR0037_REFERENCE_HOLDOUT_MAE = {
    "centroid": 0.012872174640087454,
    "ridge": 0.012279782258477557,
    "mlp": 0.009494280866924337,
}

SCIENTIFIC_BOUNDARY = (
    "确认性边界判决：标定 ADR-0037 主张的外推证据边界；不构成任何生物主张，"
    "不撤销历史 verdict，passed 也仅登记为有限外推证据、不接链"
)

CRITERIA_TEXT = (
    "component-unseen holdout 子集（n ≥ 8）上 MLP 六节点 MAE 同时严格低于质心与 "
    "ridge（两处 margin 均 >1e-12）→ passed，否则 failed；若该子集 n < 8 单元，"
    "判据自动记 insufficient（证据不足）而非 failed"
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


def _stratify(names: list[str], train_mask: np.ndarray) -> dict:
    """ADR-0049 section 3.1 frozen rule; deterministic, no randomness."""
    train_vocab = sorted(
        {part for name, is_train in zip(names, train_mask) if is_train for part in name.split("_")}
    )
    train_vocab_set = set(train_vocab)
    per_unit = []
    for name, is_train in zip(names, train_mask):
        parts = name.split("_")
        seen_flags = [part in train_vocab_set for part in parts]
        per_unit.append(
            {
                "unit": name,
                "role": "train" if is_train else "holdout",
                "components": parts,
                "component_seen_in_train": seen_flags,
                "all_components_seen": all(seen_flags),
                "all_components_unseen": not any(seen_flags),
                "single_gene": len(parts) == 1,
                "stratum": (
                    "train"
                    if is_train
                    else ("component-seen" if all(seen_flags) else "component-unseen")
                ),
            }
        )
    return {"train_vocab": train_vocab, "per_unit": per_unit}


def _mae_stratum(
    pred: np.ndarray, targets: np.ndarray, unit_rows: list[int]
) -> float | None:
    if not unit_rows:
        return None
    return float(np.abs(pred[unit_rows] - targets[unit_rows]).mean())


def run(profile_path: Path, output_dir: Path) -> dict:
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

    output_dir.mkdir(parents=True, exist_ok=True)
    weights_path = output_dir / "weights.npz"
    if weights_path.exists():
        raise ValueError(f"refusing to overwrite existing weights: {weights_path}")
    np.savez(
        weights_path,
        **{name: tensor.detach().numpy() for name, tensor in model.state_dict().items()},
    )

    # --- ADR-0049 evaluation segment (the only difference from ADR-0037) ---
    strat = _stratify(names, train_mask)
    holdout_mask = ~train_mask
    centroid_pred = np.broadcast_to(centroid, targets.shape)
    predictions = {"centroid": centroid_pred, "ridge": ridge_pred, "mlp": mlp_pred}

    # Per-unit six-node MAE for every holdout unit, all three predictors.
    per_unit = []
    for row, entry in enumerate(strat["per_unit"]):
        if entry["role"] != "holdout":
            continue
        per_unit.append(
            {
                "unit": entry["unit"],
                "components": entry["components"],
                "stratum": entry["stratum"],
                "all_components_unseen": entry["all_components_unseen"],
                "single_gene": entry["single_gene"],
                "mae": {
                    name: float(np.abs(pred[row] - targets[row]).mean())
                    for name, pred in predictions.items()
                },
            }
        )

    def stratum_rows(predicate) -> list[int]:
        return [
            row
            for row, entry in enumerate(strat["per_unit"])
            if entry["role"] == "holdout" and predicate(entry)
        ]

    strata_keys = {
        "component-seen": stratum_rows(lambda e: e["stratum"] == "component-seen"),
        "component-unseen": stratum_rows(lambda e: e["stratum"] == "component-unseen"),
        "all-components-unseen": stratum_rows(lambda e: e["all_components_unseen"]),
        "holdout-all": stratum_rows(lambda e: True),
    }
    strata = {}
    for label, rows in strata_keys.items():
        mae = {name: _mae_stratum(pred, targets, rows) for name, pred in predictions.items()}
        entry = {
            "units": len(rows),
            "mae": mae,
            "margin_vs_centroid": (
                None if mae["centroid"] is None else mae["centroid"] - mae["mlp"]
            ),
            "margin_vs_ridge": None if mae["ridge"] is None else mae["ridge"] - mae["mlp"],
        }
        strata[label] = entry

    # Control anchor: full-holdout MAE must match ADR-0037 within 1e-6.
    anchor_recomputed = strata["holdout-all"]["mae"]
    anchor_deviations = {
        name: abs(anchor_recomputed[name] - ADR0037_REFERENCE_HOLDOUT_MAE[name])
        for name in predictions
    }
    anchor_ok = all(dev <= ANCHOR_TOLERANCE for dev in anchor_deviations.values())

    # Pre-registered criterion on the component-unseen stratum.
    unseen = strata["component-unseen"]
    if unseen["units"] < MIN_UNSEEN_UNITS:
        verdict = "insufficient"
    elif (
        unseen["margin_vs_centroid"] > PASS_EPSILON
        and unseen["margin_vs_ridge"] > PASS_EPSILON
    ):
        verdict = "passed"
    else:
        verdict = "failed"

    return {
        "schema_version": SCHEMA_VERSION,
        "adr": "ADR-0049",
        "created_date": "2026-09-11",
        "inputs": [
            {
                "path": "data/aivc/derived/norman-perturbation-profile.json",
                "sha256": profile_sha256,
                "role": "frozen ADR-0036 profile (236 units, train 188 / holdout 48)",
            },
            {
                "path": "scripts/train_l0_perturbation_response.py",
                "sha256": _sha256_file(Path("scripts/train_l0_perturbation_response.py")),
                "role": "ADR-0037 original training script (training segment reused verbatim)",
            },
        ],
        "stratification": {
            "rule": (
                "train_vocab = union of parts(u) over the 188 frozen train units "
                "(profile order); holdout unit is component-seen iff every component "
                "of parts(u)=unit.split('_') is in train_vocab, else component-unseen; "
                "all-components-unseen reported descriptively; no re-splitting, no "
                "randomness, no hand-picking"
            ),
            "train_vocab_size": len(strat["train_vocab"]),
            "train_vocab": strat["train_vocab"],
            "holdout_component_unseen_units": unseen["units"],
            "holdout_component_seen_units": strata["component-seen"]["units"],
            "holdout_all_components_unseen_units": strata["all-components-unseen"]["units"],
            "holdout_single_gene_component_unseen_units": sum(
                1 for e in per_unit if e["single_gene"] and e["stratum"] == "component-unseen"
            ),
            "units": strat["per_unit"],
        },
        "anchors": {
            "centroid_crosscheck_max_abs_diff": centroid_diff,
            "centroid_crosscheck_tolerance": CENTROID_TOLERANCE,
            "adr0037_reference_holdout_mae": ADR0037_REFERENCE_HOLDOUT_MAE,
            "recomputed_holdout_all_mae": anchor_recomputed,
            "abs_deviation_vs_reference": anchor_deviations,
            "anchor_tolerance": ANCHOR_TOLERANCE,
            "anchor_check_passed": anchor_ok,
        },
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
        "split": {
            "salt": profile["split"]["salt"],
            "train_units": int(train_mask.sum()),
            "holdout_units": int(holdout_mask.sum()),
        },
        "per_unit": per_unit,
        "strata": strata,
        "criteria": {
            "text": CRITERIA_TEXT,
            "pass_epsilon": PASS_EPSILON,
            "min_unseen_units": MIN_UNSEEN_UNITS,
        },
        "verdict": verdict,
        "weights": {
            "path": "weights.npz",
            "sha256": _sha256_file(weights_path),
            "bytes": weights_path.stat().st_size,
        },
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def write_manifest(output_dir: Path, profile_path: Path, second_dir: Path | None) -> None:
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
    entries.append(
        {
            "path": "data/aivc/derived/norman-perturbation-profile.json",
            "sha256": _sha256_file(profile_path),
            "bytes": profile_path.stat().st_size,
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
        "adr": "ADR-0049",
        "kind": "manifest",
        "entries": entries,
        "determinism": determinism,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="data/aivc/derived/norman-perturbation-profile.json")
    parser.add_argument("--output-dir", required=True, help="artifact directory")
    parser.add_argument(
        "--second-run-dir",
        default=None,
        help="directory of an independent second run for the byte-identity check",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    results_path = output_dir / "results.json"
    if results_path.exists():
        raise SystemExit(f"refusing to overwrite existing results: {results_path}")
    result = run(Path(args.profile), output_dir)
    if not result["anchors"]["anchor_check_passed"]:
        raise SystemExit(
            "control anchor check failed (pipeline drift); "
            "stopping before registering results per ADR-0049 section 3.4"
        )
    results_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_manifest(
        output_dir,
        Path(args.profile),
        Path(args.second_run_dir) if args.second_run_dir else None,
    )
    print(
        json.dumps(
            {
                "adr": result["adr"],
                "verdict": result["verdict"],
                "anchor_check_passed": result["anchors"]["anchor_check_passed"],
                "component_unseen_units": result["stratification"][
                    "holdout_component_unseen_units"
                ],
                "strata": result["strata"],
                "final_train_loss_mse": result["training"]["final_train_loss_mse"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
