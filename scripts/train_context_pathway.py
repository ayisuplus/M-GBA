#!/usr/bin/env python
"""Train one locked cross-context Hallmark OOD fold in ``.venv-train``.

The script fits train-fold PCA/standardizers, three ridge ablations, tunes the
low-rank interaction by inner leave-one-context-out, and ensembles five seeds.
GEARS, scGPT, and biolord predictions are imported only when all three frozen
official-run artifacts are supplied; this script does not impersonate them.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge

from mgba.context_pathway import DEVELOPMENT_CONTEXTS, load_context_bundle, load_ood_split_manifest
from mgba.context_pathway_evaluation import (
    FROZEN_MODEL_PROTOCOL,
    OFFICIAL_LEARNED_REPOSITORIES,
    PREDICTIONS_SCHEMA_VERSION,
)
from mgba.experiment import write_json_once
from mgba.validation import file_sha256

LEARNED_SCHEMA_VERSION = "mgba-context-pathway-learned-predictions-0.1"
LEARNED_IDS = ("gears", "scgpt", "biolord")
SCIENTIFIC_BOUNDARY = (
    "Pathway-level OOD CRISPRi response prediction; not a biological, clinical, "
    "CAR-M efficacy, or full virtual-cell validation."
)


class LowRankInteraction(torch.nn.Module):
    def __init__(self, perturbation_dim: int, context_dim: int, output_dim: int, rank: int):
        super().__init__()
        self.bias = torch.nn.Parameter(torch.zeros(output_dim))
        self.perturbation_main = torch.nn.Linear(perturbation_dim, output_dim, bias=False)
        self.context_main = torch.nn.Linear(context_dim, output_dim, bias=False)
        self.perturbation_interaction = torch.nn.Linear(perturbation_dim, rank, bias=False)
        self.context_interaction = torch.nn.Linear(context_dim, rank, bias=False)
        self.interaction_output = torch.nn.Linear(rank, output_dim, bias=False)

    def forward(self, perturbation, context):
        interaction = torch.tanh(self.perturbation_interaction(perturbation)) * torch.tanh(
            self.context_interaction(context)
        )
        return (
            self.bias
            + self.perturbation_main(perturbation)
            + self.context_main(context)
            + self.interaction_output(interaction)
        )


def fit_low_rank(
    perturbation: np.ndarray,
    context: np.ndarray,
    target: np.ndarray,
    validation: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    rank: int,
    learning_rate: float,
    weight_decay: float,
    seed: int,
    max_epochs: int,
    patience: int,
    device: str,
):
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    model = LowRankInteraction(
        perturbation.shape[1], context.shape[1], target.shape[1], rank
    ).to(device)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=learning_rate, weight_decay=weight_decay
    )
    train_tensors = tuple(
        torch.as_tensor(value, dtype=torch.float32, device=device)
        for value in (perturbation, context, target)
    )
    validation_tensors = tuple(
        torch.as_tensor(value, dtype=torch.float32, device=device)
        for value in validation
    )
    best_loss = float("inf")
    best_state = None
    stale = 0
    for _ in range(max_epochs):
        model.train()
        optimizer.zero_grad()
        prediction = model(train_tensors[0], train_tensors[1])
        loss = torch.nn.functional.mse_loss(prediction, train_tensors[2])
        loss.backward()
        optimizer.step()
        model.eval()
        with torch.no_grad():
            value = float(
                torch.mean(
                    torch.abs(
                        model(validation_tensors[0], validation_tensors[1])
                        - validation_tensors[2]
                    )
                )
            )
        if value < best_loss - 1e-12:
            best_loss = value
            best_state = deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise RuntimeError("low-rank training did not produce a finite validation loss")
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        validation_prediction = (
            model(validation_tensors[0], validation_tensors[1]).cpu().numpy()
        )
    return model.cpu(), validation_prediction, best_loss


def _standardizer(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = values.mean(axis=0)
    scale = values.std(axis=0)
    scale[scale <= 1e-12] = 1.0
    return mean, scale


def _rows(
    contexts: list[str],
    genes: list[str],
    perturbation: dict[str, np.ndarray],
    context: dict[str, np.ndarray],
    target: dict[tuple[str, str], np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pairs = [(cell_context, gene) for cell_context in contexts for gene in genes]
    return (
        np.stack([perturbation[gene] for _, gene in pairs]).astype(np.float32),
        np.stack([context[cell_context] for cell_context, _ in pairs]).astype(np.float32),
        np.stack([target[pair] for pair in pairs]).astype(np.float64),
    )


def _predict(model, perturbation: np.ndarray, context: np.ndarray, device: str) -> np.ndarray:
    model = model.to(device)
    with torch.no_grad():
        result = model(
            torch.as_tensor(perturbation, dtype=torch.float32, device=device),
            torch.as_tensor(context, dtype=torch.float32, device=device),
        ).cpu().numpy()
    return result


def _load_learned(
    paths: dict[str, Path],
    *,
    fold_id: str,
    split_digest: str,
    dims: list[str],
    expected: set[tuple[str, str]],
    hallmark_sha256: str,
) -> tuple[dict[str, dict[tuple[str, str], np.ndarray]], dict[str, dict]]:
    if paths and set(paths) != set(LEARNED_IDS):
        raise ValueError("provide all of gears, scgpt, and biolord or none")
    predictions = {}
    sources = {}
    for predictor, path in paths.items():
        raw = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "schema_version", "predictor_id", "implementation", "mapping",
            "fold_id", "split_manifest_sha256", "dims", "units",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError(f"invalid learned prediction artifact: {predictor}")
        if (
            raw["schema_version"] != LEARNED_SCHEMA_VERSION
            or raw["predictor_id"] != predictor
            or raw["fold_id"] != fold_id
            or raw["split_manifest_sha256"] != split_digest
            or raw["dims"] != dims
        ):
            raise ValueError(f"learned prediction provenance mismatch: {predictor}")
        implementation = raw["implementation"]
        mapping = raw["mapping"]
        if not isinstance(implementation, dict) or set(implementation) != {
            "repository", "commit", "version"
        }:
            raise ValueError(f"learned implementation identity is invalid: {predictor}")
        if (
            implementation["repository"] != OFFICIAL_LEARNED_REPOSITORIES[predictor]
            or not isinstance(implementation["commit"], str)
            or len(implementation["commit"]) != 40
            or any(character not in "0123456789abcdef" for character in implementation["commit"])
            or not isinstance(implementation["version"], str)
            or not implementation["version"].strip()
        ):
            raise ValueError(f"learned implementation identity is invalid: {predictor}")
        if not isinstance(mapping, dict) or mapping != {
            "source_space": "full-expression",
            "target_space": "hallmark-50-unweighted-log2fc-mean",
            "hallmark_sha256": hallmark_sha256,
        }:
            raise ValueError(f"learned Hallmark mapping provenance mismatch: {predictor}")
        if not isinstance(raw["units"], list):
            raise ValueError(f"learned prediction units must be a list: {predictor}")
        units = {}
        for item in raw["units"]:
            if not isinstance(item, dict) or set(item) != {
                "context_id", "gene", "prediction"
            }:
                raise ValueError(f"invalid learned prediction unit: {predictor}")
            identity = (item["context_id"], item["gene"])
            if identity in units:
                raise ValueError(f"duplicate learned prediction unit: {predictor}")
            value = np.asarray(item["prediction"], dtype=np.float64)
            if value.shape != (50,) or not np.isfinite(value).all():
                raise ValueError(f"invalid learned prediction vector: {predictor}")
            units[identity] = value
        if set(units) != expected:
            raise ValueError(f"learned prediction coverage mismatch: {predictor}")
        predictions[predictor] = units
        sources[predictor] = {
            "implementation": implementation,
            "mapping": mapping,
            "artifact": {"path": path.name, "sha256": file_sha256(path)},
        }
    return predictions, sources


def train_fold(
    bundle_paths: list[Path],
    split_path: Path,
    embeddings_path: Path,
    fold_id: str,
    weights_dir: Path,
    learned_paths: dict[str, Path],
    device: str,
) -> dict:
    split = load_ood_split_manifest(split_path)
    split_digest = split.pop("_file_sha256")
    folds = {fold["fold_id"]: fold for fold in split["folds"]}
    if fold_id not in folds:
        raise ValueError(f"unknown fold_id: {fold_id}")
    fold = folds[fold_id]
    bundles = {bundle.context_id: bundle for bundle in map(load_context_bundle, bundle_paths)}
    if set(bundles) != set(DEVELOPMENT_CONTEXTS):
        raise ValueError("training requires exactly the four development bundles")
    for context_id, identity in split["bundles"].items():
        if bundles[context_id].file_sha256 != identity["sha256"]:
            raise ValueError(f"bundle SHA-256 mismatch: {context_id}")

    embedding_digest = file_sha256(embeddings_path)
    expected_embedding_digest = split["feature_eligibility"][
        "embedding_table_sha256"
    ]
    if embedding_digest != expected_embedding_digest:
        raise ValueError("Geneformer embedding table SHA-256 does not match the locked split")
    table = json.loads(embeddings_path.read_text(encoding="utf-8"))
    if table.get("schema_version") != "mgba-gene-embedding-table-0.1" or table.get("embedding_dim") != 768:
        raise ValueError("expected a 768-dimensional Geneformer embedding table")
    genes = split["shared_genes"]
    missing = [gene for gene in genes if gene not in table.get("embeddings", {})]
    if missing:
        raise ValueError(f"Geneformer embeddings missing for {len(missing)} shared genes")
    raw_embeddings = {
        gene: np.asarray(table["embeddings"][gene], dtype=np.float64) for gene in genes
    }
    if any(value.shape != (768,) or not np.isfinite(value).all() for value in raw_embeddings.values()):
        raise ValueError("Geneformer embeddings must be finite 768-element vectors")

    train_genes = fold["train_genes"]
    validation_genes = fold["validation_genes"]
    test_genes = fold["test_genes"]
    pca = PCA(n_components=FROZEN_MODEL_PROTOCOL["pca_dim"], svd_solver="full")
    pca.fit(np.stack([raw_embeddings[gene] for gene in train_genes]))
    perturbation_features = {
        gene: pca.transform(raw_embeddings[gene][None, :])[0] for gene in genes
    }
    controls = {
        context_id: np.asarray(bundle.control, dtype=np.float64)
        for context_id, bundle in bundles.items()
    }
    context_train_raw = np.stack([controls[name] for name in fold["training_contexts"]])
    context_mean, context_scale = _standardizer(context_train_raw)
    context_features = {
        name: (values - context_mean) / context_scale for name, values in controls.items()
    }
    targets = {
        (context_id, unit.gene): np.asarray(unit.target, dtype=np.float64)
        for context_id, bundle in bundles.items()
        for unit in bundle.units
        if unit.gene in set(genes)
    }
    train_p, train_c, train_y_raw = _rows(
        fold["training_contexts"], train_genes, perturbation_features, context_features, targets
    )
    target_mean, target_scale = _standardizer(train_y_raw.astype(np.float64))
    train_y = ((train_y_raw - target_mean) / target_scale).astype(np.float32)
    validation_p, validation_c, validation_y_raw = _rows(
        fold["training_contexts"], validation_genes,
        perturbation_features, context_features, targets,
    )
    validation_y = ((validation_y_raw - target_mean) / target_scale).astype(np.float32)

    outer = fold["outer_context"]
    specifications = (
        [("context_ood", outer, gene) for gene in train_genes]
        + [
            ("gene_ood", context_id, gene)
            for context_id in fold["training_contexts"] for gene in test_genes
        ]
        + [("joint_ood", outer, gene) for gene in test_genes]
    )
    expected = {(context_id, gene) for _, context_id, gene in specifications}
    learned, learned_sources = _load_learned(
        learned_paths, fold_id=fold_id, split_digest=split_digest,
        dims=split["dims"], expected=expected,
        hallmark_sha256=bundles[DEVELOPMENT_CONTEXTS[0]].hallmark_source["sha256"],
    )
    weight_paths = [
        weights_dir / f"{fold_id}-seed-{seed}.npz"
        for seed in FROZEN_MODEL_PROTOCOL["seeds"]
    ]
    existing = [path for path in weight_paths if path.exists()]
    if existing:
        raise ValueError(f"refusing to overwrite existing weights: {existing[0]}")

    best = None
    for rank in FROZEN_MODEL_PROTOCOL["ranks"]:
        for learning_rate in FROZEN_MODEL_PROTOCOL["learning_rates"]:
            for weight_decay in FROZEN_MODEL_PROTOCOL["weight_decays"]:
                inner_scores = []
                for held_context in fold["training_contexts"]:
                    inner_contexts = [
                        name for name in fold["training_contexts"] if name != held_context
                    ]
                    inner_raw = np.stack([controls[name] for name in inner_contexts])
                    inner_context_mean, inner_context_scale = _standardizer(inner_raw)
                    inner_context_features = {
                        name: (values - inner_context_mean) / inner_context_scale
                        for name, values in controls.items()
                    }
                    inner_p, inner_c, inner_y_raw = _rows(
                        inner_contexts, train_genes,
                        perturbation_features, inner_context_features, targets,
                    )
                    inner_target_mean, inner_target_scale = _standardizer(inner_y_raw.astype(np.float64))
                    inner_y = ((inner_y_raw - inner_target_mean) / inner_target_scale).astype(np.float32)
                    held_p, held_c, held_y_raw = _rows(
                        [held_context], validation_genes,
                        perturbation_features, inner_context_features, targets,
                    )
                    held_y = ((held_y_raw - inner_target_mean) / inner_target_scale).astype(np.float32)
                    _, prediction, _ = fit_low_rank(
                        inner_p, inner_c, inner_y, (held_p, held_c, held_y),
                        rank=rank, learning_rate=learning_rate,
                        weight_decay=weight_decay, seed=42,
                        max_epochs=FROZEN_MODEL_PROTOCOL["max_epochs"],
                        patience=FROZEN_MODEL_PROTOCOL["patience"], device=device,
                    )
                    inner_scores.append(float(np.abs(prediction - held_y).mean()))
                candidate = (float(np.mean(inner_scores)), rank, learning_rate, weight_decay)
                if best is None or candidate < best:
                    best = candidate
    assert best is not None
    _, selected_rank, selected_learning_rate, selected_weight_decay = best

    ridge_alpha = FROZEN_MODEL_PROTOCOL["ridge_alpha"]
    gene_ridge = Ridge(alpha=ridge_alpha).fit(train_p, train_y_raw)
    context_ridge = Ridge(alpha=ridge_alpha).fit(train_c, train_y_raw)
    additive_ridge = Ridge(alpha=ridge_alpha).fit(
        np.concatenate((train_p, train_c), axis=1), train_y_raw
    )

    weights_dir.mkdir(parents=True, exist_ok=True)
    models = []
    weights = []
    for seed, weight_path in zip(FROZEN_MODEL_PROTOCOL["seeds"], weight_paths):
        model, _, _ = fit_low_rank(
            train_p, train_c, train_y,
            (validation_p, validation_c, validation_y),
            rank=selected_rank, learning_rate=selected_learning_rate,
            weight_decay=selected_weight_decay, seed=seed,
            max_epochs=FROZEN_MODEL_PROTOCOL["max_epochs"],
            patience=FROZEN_MODEL_PROTOCOL["patience"], device=device,
        )
        models.append(model)
        arrays = {
            f"model__{name}": tensor.detach().numpy()
            for name, tensor in model.state_dict().items()
        }
        arrays |= {
            "pca_components": pca.components_, "pca_mean": pca.mean_,
            "context_mean": context_mean, "context_scale": context_scale,
            "target_mean": target_mean, "target_scale": target_scale,
        }
        np.savez(weight_path, **arrays)
        weights.append({
            "seed": seed, "path": str(weight_path),
            "sha256": file_sha256(weight_path), "bytes": weight_path.stat().st_size,
        })

    training_mean = train_y_raw.mean(axis=0)
    context_means = {
        context_id: np.stack([targets[(context_id, gene)] for gene in train_genes]).mean(axis=0)
        for context_id in fold["training_contexts"]
    }
    gene_means = {
        gene: np.stack([targets[(context_id, gene)] for context_id in fold["training_contexts"]]).mean(axis=0)
        for gene in train_genes
    }
    units = []
    for scenario, context_id, gene in specifications:
        p = perturbation_features[gene][None, :].astype(np.float32)
        c = context_features[context_id][None, :].astype(np.float32)
        ensemble = np.mean(
            [_predict(model, p, c, device)[0] for model in models], axis=0
        ) * target_scale + target_mean
        predictions = {
            "zero_response": np.zeros(50),
            "training_perturbed_mean": training_mean,
            "gene_only_ridge": gene_ridge.predict(p)[0],
            "context_only_ridge": context_ridge.predict(c)[0],
            "additive_ridge": additive_ridge.predict(np.concatenate((p, c), axis=1))[0],
            "interaction_model": ensemble,
        }
        if scenario == "context_ood":
            predictions["gene_mean"] = gene_means[gene]
        if scenario == "gene_ood":
            predictions["context_perturbed_mean"] = context_means[context_id]
        predictions |= {
            predictor: values[(context_id, gene)] for predictor, values in learned.items()
        }
        units.append({
            "context_id": context_id, "gene": gene, "scenario": scenario,
            "target": targets[(context_id, gene)].tolist(),
            "predictions": {name: value.tolist() for name, value in predictions.items()},
        })
    units.sort(key=lambda item: (item["scenario"], item["context_id"], item["gene"]))
    predictors = {
        "zero_response": "simple",
        "training_perturbed_mean": "simple",
        "gene_mean": "simple_context_ood_only",
        "context_perturbed_mean": "simple_gene_ood_only",
        "gene_only_ridge": "simple_ablation",
        "context_only_ridge": "ablation",
        "additive_ridge": "simple_ablation",
        "interaction_model": "proposed",
    }
    predictors |= {name: "learned" for name in learned}
    training = dict(FROZEN_MODEL_PROTOCOL)
    training |= {
        "selected_hyperparameters": {
            "rank": selected_rank,
            "learning_rate": selected_learning_rate,
            "weight_decay": selected_weight_decay,
        },
        "tuning": "inner-leave-one-context-out",
    }
    return {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "study_id": split["study_id"],
        "fold_id": fold_id,
        "split_manifest_sha256": split_digest,
        "protocol_status": "complete" if learned else "development",
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "feature_source": {
            "schema_version": table["schema_version"],
            "path": embeddings_path.name,
            "sha256": embedding_digest,
            "dim": 768,
        },
        "training": training,
        "predictors": predictors,
        "learned_sources": learned_sources,
        "weights": weights,
        "units": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", action="append", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--embeddings", required=True)
    parser.add_argument("--fold-id", required=True)
    parser.add_argument("--weights-dir", required=True)
    parser.add_argument("--learned", action="append", default=[], metavar="ID=PATH")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise SystemExit(f"refusing to overwrite existing predictions: {args.output}")
    learned_paths = {}
    for item in args.learned:
        predictor, separator, path = item.partition("=")
        if not separator or predictor in learned_paths:
            raise SystemExit("--learned must be unique ID=PATH entries")
        learned_paths[predictor] = Path(path)
    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device == "auto":
        device = "cpu"
    result = train_fold(
        [Path(path) for path in args.bundle], Path(args.split), Path(args.embeddings),
        args.fold_id, Path(args.weights_dir), learned_paths, device,
    )
    write_json_once(args.output, result, artifact="context pathway predictions")
    print(json.dumps({
        "schema_version": result["schema_version"],
        "fold_id": result["fold_id"],
        "protocol_status": result["protocol_status"],
        "units": len(result["units"]),
        "selected_hyperparameters": result["training"]["selected_hyperparameters"],
        "output": args.output,
    }, indent=2))


if __name__ == "__main__":
    main()
