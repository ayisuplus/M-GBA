#!/usr/bin/env python
"""Screen the locked simple baselines across all 20 development OOD folds."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge

from mgba.context_pathway import DEVELOPMENT_CONTEXTS, load_context_bundle, load_ood_split_manifest
from mgba.context_pathway_evaluation import FROZEN_MODEL_PROTOCOL
from mgba.experiment import write_json_once
from mgba.validation import file_sha256

SCHEMA_VERSION = "mgba-context-pathway-baseline-screen-0.1"
JOINT_BASELINES = (
    "zero_response",
    "training_perturbed_mean",
    "gene_only_ridge",
    "context_only_ridge",
    "additive_ridge",
)


def _standardizer(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = values.mean(axis=0)
    scale = values.std(axis=0)
    scale[scale <= 1e-12] = 1.0
    return mean, scale


def _rows(contexts, genes, perturbation, context, target):
    pairs = [(cell_context, gene) for cell_context in contexts for gene in genes]
    return (
        np.stack([perturbation[gene] for _, gene in pairs]).astype(np.float32),
        np.stack([context[cell_context] for cell_context, _ in pairs]).astype(np.float32),
        np.stack([target[pair] for pair in pairs]).astype(np.float64),
    )


def _summary(losses: dict[str, dict[str, list[float]]]) -> dict:
    return {
        scenario: {
            predictor: {
                "standardized_macro_mae": float(np.mean(values)),
                "unit_count": len(values),
            }
            for predictor, values in sorted(predictors.items())
        }
        for scenario, predictors in sorted(losses.items())
    }


def screen(
    bundle_paths: list[Path], split_path: Path, embeddings_path: Path
) -> dict:
    split = load_ood_split_manifest(split_path)
    split_digest = split.pop("_file_sha256")
    bundles = {bundle.context_id: bundle for bundle in map(load_context_bundle, bundle_paths)}
    if set(bundles) != set(DEVELOPMENT_CONTEXTS):
        raise ValueError("baseline screen requires exactly the four development bundles")
    for context_id, identity in split["bundles"].items():
        if bundles[context_id].file_sha256 != identity["sha256"]:
            raise ValueError(f"bundle SHA-256 mismatch: {context_id}")

    embedding_digest = file_sha256(embeddings_path)
    if embedding_digest != split["feature_eligibility"]["embedding_table_sha256"]:
        raise ValueError("Geneformer embedding table SHA-256 does not match the locked split")
    table = json.loads(embeddings_path.read_text(encoding="utf-8"))
    if (
        table.get("schema_version") != "mgba-gene-embedding-table-0.1"
        or table.get("embedding_dim") != 768
    ):
        raise ValueError("expected a 768-dimensional Geneformer embedding table")
    genes = split["shared_genes"]
    missing = [gene for gene in genes if gene not in table.get("embeddings", {})]
    if missing:
        raise ValueError(f"Geneformer embeddings missing for {len(missing)} shared genes")
    raw_embeddings = {
        gene: np.asarray(table["embeddings"][gene], dtype=np.float64) for gene in genes
    }
    if any(vector.shape != (768,) or not np.isfinite(vector).all() for vector in raw_embeddings.values()):
        raise ValueError("Geneformer embeddings must be finite 768-element vectors")

    controls = {
        context_id: np.asarray(bundle.control, dtype=np.float64)
        for context_id, bundle in bundles.items()
    }
    targets = {
        (context_id, unit.gene): np.asarray(unit.target, dtype=np.float64)
        for context_id, bundle in bundles.items()
        for unit in bundle.units
        if unit.gene in set(genes)
    }
    all_losses: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    context_joint: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    fold_results = []
    for fold in split["folds"]:
        train_genes = fold["train_genes"]
        validation_genes = fold["validation_genes"]
        test_genes = fold["test_genes"]
        if (
            set(train_genes) & set(validation_genes)
            or set(train_genes) & set(test_genes)
            or set(validation_genes) & set(test_genes)
            or fold["outer_context"] in fold["training_contexts"]
        ):
            raise ValueError(f"split leakage detected: {fold['fold_id']}")

        pca = PCA(n_components=FROZEN_MODEL_PROTOCOL["pca_dim"], svd_solver="full")
        pca.fit(np.stack([raw_embeddings[gene] for gene in train_genes]))
        perturbation = {
            gene: pca.transform(raw_embeddings[gene][None, :])[0] for gene in genes
        }
        context_mean, context_scale = _standardizer(
            np.stack([controls[name] for name in fold["training_contexts"]])
        )
        context = {
            name: (vector - context_mean) / context_scale
            for name, vector in controls.items()
        }
        train_p, train_c, train_y = _rows(
            fold["training_contexts"], train_genes, perturbation, context, targets
        )
        _, target_scale = _standardizer(train_y)
        alpha = FROZEN_MODEL_PROTOCOL["ridge_alpha"]
        gene_ridge = Ridge(alpha=alpha).fit(train_p, train_y)
        context_ridge = Ridge(alpha=alpha).fit(train_c, train_y)
        additive_ridge = Ridge(alpha=alpha).fit(
            np.concatenate((train_p, train_c), axis=1), train_y
        )
        training_mean = train_y.mean(axis=0)
        context_means = {
            name: np.stack([targets[(name, gene)] for gene in train_genes]).mean(axis=0)
            for name in fold["training_contexts"]
        }
        gene_means = {
            gene: np.stack(
                [targets[(name, gene)] for name in fold["training_contexts"]]
            ).mean(axis=0)
            for gene in train_genes
        }
        outer = fold["outer_context"]
        specifications = (
            [("context_ood", outer, gene) for gene in train_genes]
            + [
                ("gene_ood", name, gene)
                for name in fold["training_contexts"]
                for gene in test_genes
            ]
            + [("joint_ood", outer, gene) for gene in test_genes]
        )
        fold_losses: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for scenario, context_id, gene in specifications:
            p = perturbation[gene][None, :]
            c = context[context_id][None, :]
            prediction = {
                "zero_response": np.zeros(50),
                "training_perturbed_mean": training_mean,
                "gene_only_ridge": gene_ridge.predict(p)[0],
                "context_only_ridge": context_ridge.predict(c)[0],
                "additive_ridge": additive_ridge.predict(np.concatenate((p, c), axis=1))[0],
            }
            if scenario == "context_ood":
                prediction["gene_mean"] = gene_means[gene]
            elif scenario == "gene_ood":
                prediction["context_perturbed_mean"] = context_means[context_id]
            target = targets[(context_id, gene)]
            for predictor, values in prediction.items():
                loss = float(np.mean(np.abs(values - target) / target_scale))
                fold_losses[scenario][predictor].append(loss)
                all_losses[scenario][predictor].append(loss)
                if scenario == "joint_ood":
                    context_joint[outer][predictor].append(loss)
        fold_results.append({"fold_id": fold["fold_id"], "metrics": _summary(fold_losses)})

    metrics = _summary(all_losses)
    best_joint = min(
        JOINT_BASELINES,
        key=lambda predictor: metrics["joint_ood"][predictor]["standardized_macro_mae"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": split["study_id"],
        "protocol_status": "simple-baselines-complete",
        "scientific_boundary": "Development-only screen; not a paper or external-test verdict.",
        "source": {
            "split_manifest_sha256": split_digest,
            "embedding_table_sha256": embedding_digest,
            "bundle_sha256": {
                context_id: bundles[context_id].file_sha256
                for context_id in DEVELOPMENT_CONTEXTS
            },
        },
        "coverage": {
            "folds": len(fold_results),
            "genes": len(genes),
            "outer_context_perturbations_used_for_training": 0,
            "test_genes_used_for_training": 0,
        },
        "metrics": metrics,
        "joint_ood_best_simple": {
            "predictor": best_joint,
            **metrics["joint_ood"][best_joint],
        },
        "joint_ood_by_context": {
            context_id: {
                predictor: float(np.mean(values))
                for predictor, values in sorted(predictors.items())
            }
            for context_id, predictors in sorted(context_joint.items())
        },
        "folds": fold_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", action="append", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--embeddings", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = screen(
        [Path(path) for path in args.bundle], Path(args.split), Path(args.embeddings)
    )
    write_json_once(args.output, result, artifact="context pathway baseline screen")
    print(json.dumps({
        "schema_version": result["schema_version"],
        "folds": result["coverage"]["folds"],
        "genes": result["coverage"]["genes"],
        "joint_ood_best_simple": result["joint_ood_best_simple"],
        "output": args.output,
    }, indent=2))


if __name__ == "__main__":
    main()
