"""Tests for the cross-context pathway OOD evidence boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from statistics import fmean
from unittest import mock

from mgba.cli import main as cli_main
from mgba.context_pathway import (
    CONTEXT_BUNDLE_SCHEMA_VERSION,
    DEVELOPMENT_CONTEXTS,
    EXTERNAL_CONTEXT_ID,
    HALLMARK_DIM_COUNT,
    PRE_REGISTERED_SALTS,
    SPLIT_MANIFEST_SCHEMA_VERSION,
    build_ood_split_manifest,
    load_context_bundle,
    load_ood_split_manifest,
    save_ood_split_manifest,
)
from mgba.context_pathway_evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
    FROZEN_MODEL_PROTOCOL,
    PREDICTIONS_SCHEMA_VERSION,
    _bootstrap_blocks,
    evaluate_external_context_pathway_predictions,
    evaluate_context_pathway_predictions,
    load_context_pathway_predictions,
    save_context_pathway_evaluation,
)
from mgba.ocellus_anchors import spearman
from mgba.hashing import digest_payload


_DIMS = tuple(f"HALLMARK_TEST_{index:02d}" for index in range(HALLMARK_DIM_COUNT))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _bundle_payload(context_id: str, genes: list[str] | None = None) -> dict:
    genes = sorted(genes or [f"GENE{index:04d}" for index in range(500)])
    offset = DEVELOPMENT_CONTEXTS.index(context_id) * 0.001
    return {
        "schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION,
        "dataset_id": f"dataset-{context_id}",
        "context_id": context_id,
        "perturbation_type": "crispri",
        "scientific_boundary": "pathway-level public-data research fixture",
        "source": {
            "path": f"{context_id}.h5ad",
            "sha256": "a" * 64,
            "bytes": 100,
            "license": "CC BY 4.0",
            "rights_verified": True,
        },
        "hallmark_source": {
            "path": "hallmark.gmt",
            "sha256": "b" * 64,
            "version": "fixture",
            "license": "MSigDB terms",
            "rights_verified": True,
        },
        "normalization": {
            "library_size_scale": 10000.0,
            "transform": "log2(1+x)",
            "aggregation": "per-cell-transform-then-mean",
            "effect": "perturbed-minus-matched-control",
        },
        "dims": list(_DIMS),
        "control": {
            "cells": 100,
            "vector": {dim: 0.1 + offset for dim in _DIMS},
        },
        "units": [
            {
                "gene": gene,
                "cells": 50,
                "target": {
                    dim: 0.01 * ((gene_index + dim_index) % 7) + offset
                    for dim_index, dim in enumerate(_DIMS)
                },
            }
            for gene_index, gene in enumerate(genes)
        ],
        "reliability": {
            "resamples": 20,
            "seed": 20260903,
            "median_split_half_spearman": 0.75,
        },
    }


def _write_bundles(root: Path, *, genes: list[str] | None = None) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for context_id in DEVELOPMENT_CONTEXTS:
        path = root / f"{context_id}.json"
        path.write_text(json.dumps(_bundle_payload(context_id, genes)), encoding="utf-8")
        paths.append(path)
    return paths


def _build_manifest(
    bundles, *, external_labels_sha256: str = "c" * 64,
    embedding_genes: list[str] | None = None,
) -> dict:
    if embedding_genes is None:
        embedding_genes = sorted(
            {unit.gene for bundle in bundles for unit in bundle.units}
        )
    return build_ood_split_manifest(
        bundles,
        embedding_genes=embedding_genes,
        embedding_table_sha256="e" * 64,
        external_labels_sha256=external_labels_sha256,
    )


def _mean_vectors(vectors: list[list[float]]) -> list[float]:
    return [sum(values) / len(values) for values in zip(*vectors)]


def _prediction_payload(
    root: Path, *, complete: bool = False, fold_index: int = 0
) -> tuple[dict, Path, list[Path]]:
    bundle_paths = _write_bundles(root)
    bundles = [load_context_bundle(path) for path in bundle_paths]
    split = _build_manifest(bundles)
    split_path = save_ood_split_manifest(split, root / "split.json")
    fold = split["folds"][fold_index]
    targets = {
        (bundle.context_id, unit.gene): list(unit.target)
        for bundle in bundles
        for unit in bundle.units
    }
    training_vectors = [
        targets[(context, gene)]
        for context in fold["training_contexts"]
        for gene in fold["train_genes"]
    ]
    training_mean = _mean_vectors(training_vectors)
    context_means = {
        context: _mean_vectors(
            [targets[(context, gene)] for gene in fold["train_genes"]]
        )
        for context in fold["training_contexts"]
    }
    gene_means = {
        gene: _mean_vectors(
            [targets[(context, gene)] for context in fold["training_contexts"]]
        )
        for gene in fold["train_genes"]
    }
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
    if complete:
        predictors |= {"gears": "learned", "scgpt": "learned", "biolord": "learned"}

    def _predictions(target: list[float], scenario: str, context: str, gene: str) -> dict:
        result = {
            "zero_response": [0.0] * len(_DIMS),
            "training_perturbed_mean": training_mean,
            "gene_only_ridge": [value + 0.06 for value in target],
            "context_only_ridge": [value + 0.08 for value in target],
            "additive_ridge": [value + 0.04 for value in target],
            "interaction_model": [value + 0.005 for value in target],
        }
        if scenario == "context_ood":
            result["gene_mean"] = gene_means[gene]
        if scenario == "gene_ood":
            result["context_perturbed_mean"] = context_means[context]
        if complete:
            result |= {
                "gears": [value + 0.03 for value in target],
                "scgpt": [value + 0.025 for value in target],
                "biolord": [value + 0.02 for value in target],
            }
        return result

    units = []
    outer = fold["outer_context"]
    for gene in fold["train_genes"]:
        target = targets[(outer, gene)]
        units.append(
            {
                "context_id": outer,
                "gene": gene,
                "scenario": "context_ood",
                "target": target,
                "predictions": _predictions(target, "context_ood", outer, gene),
            }
        )
    for context in fold["training_contexts"]:
        for gene in fold["test_genes"]:
            target = targets[(context, gene)]
            units.append(
                {
                    "context_id": context,
                    "gene": gene,
                    "scenario": "gene_ood",
                    "target": target,
                    "predictions": _predictions(target, "gene_ood", context, gene),
                }
            )
    for gene in fold["test_genes"]:
        target = targets[(outer, gene)]
        units.append(
            {
                "context_id": outer,
                "gene": gene,
                "scenario": "joint_ood",
                "target": target,
                "predictions": _predictions(target, "joint_ood", outer, gene),
            }
        )
    units.sort(key=lambda item: (item["scenario"], item["context_id"], item["gene"]))
    training = dict(FROZEN_MODEL_PROTOCOL)
    training["selected_hyperparameters"] = {
        "rank": 8,
        "learning_rate": 0.001,
        "weight_decay": 0.0001,
    }
    training["tuning"] = "inner-leave-one-context-out"
    payload = {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "study_id": split["study_id"],
        "fold_id": fold["fold_id"],
        "split_manifest_sha256": _sha256(split_path),
        "protocol_status": "complete" if complete else "development",
        "scientific_boundary": "pathway-level OOD prediction; not a biological or clinical validation",
        "feature_source": {
            "schema_version": "mgba-gene-embedding-table-0.1",
            "path": "gene-embedding-table.json",
            "sha256": "e" * 64,
            "dim": 768,
        },
        "training": training,
        "predictors": predictors,
        "learned_sources": (
            {
                predictor: {
                    "implementation": {
                        "repository": {
                            "gears": "https://github.com/snap-stanford/GEARS",
                            "scgpt": "https://github.com/bowang-lab/scGPT",
                            "biolord": "https://github.com/nitzanlab/biolord",
                        }[predictor],
                        "commit": "f" * 40,
                        "version": "fixture",
                    },
                    "mapping": {
                        "source_space": "full-expression",
                        "target_space": "hallmark-50-unweighted-log2fc-mean",
                        "hallmark_sha256": "b" * 64,
                    },
                    "artifact": {
                        "path": f"{predictor}.json",
                        "sha256": "f" * 64,
                    },
                }
                for predictor in ("gears", "scgpt", "biolord")
            }
            if complete
            else {}
        ),
        "weights": [
            {"seed": seed, "path": f"weights-{seed}.npz", "sha256": "d" * 64, "bytes": 100}
            for seed in FROZEN_MODEL_PROTOCOL["seeds"]
        ],
        "units": units,
    }
    return payload, split_path, bundle_paths


class ContextBundleTests(unittest.TestCase):
    def test_valid_bundle_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(_bundle_payload(DEVELOPMENT_CONTEXTS[0])), encoding="utf-8")
            bundle = load_context_bundle(path)
            self.assertEqual(DEVELOPMENT_CONTEXTS[0], bundle.context_id)
            self.assertEqual(HALLMARK_DIM_COUNT, len(bundle.dims))
            self.assertEqual(500, len(bundle.units))
            self.assertEqual(_sha256(path), bundle.file_sha256)

    def test_bundle_rejects_non_hallmark_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _bundle_payload(DEVELOPMENT_CONTEXTS[0])
            payload["dims"][0] = "NOT_A_HALLMARK"
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Hallmark"):
                load_context_bundle(path)

    def test_bundle_rejects_target_key_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _bundle_payload(DEVELOPMENT_CONTEXTS[0])
            del payload["units"][0]["target"][_DIMS[0]]
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target dimensions"):
                load_context_bundle(path)


class OodSplitTests(unittest.TestCase):
    def test_builds_disjoint_gene_and_context_folds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundles = [load_context_bundle(path) for path in _write_bundles(Path(tmp))]
            manifest = _build_manifest(bundles)
            self.assertEqual(SPLIT_MANIFEST_SCHEMA_VERSION, manifest["schema_version"])
            self.assertEqual(20, len(manifest["folds"]))
            self.assertEqual(list(PRE_REGISTERED_SALTS), manifest["salts"])
            self.assertEqual("sealed", manifest["external_test"]["status"])
            for fold in manifest["folds"]:
                train = set(fold["train_genes"])
                validation = set(fold["validation_genes"])
                test = set(fold["test_genes"])
                self.assertFalse(train & validation)
                self.assertFalse(train & test)
                self.assertFalse(validation & test)
                self.assertEqual(set(manifest["shared_genes"]), train | validation | test)
                self.assertNotIn(fold["outer_context"], fold["training_contexts"])
                self.assertEqual(3, len(fold["training_contexts"]))

    def test_freezes_embedding_eligibility_and_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            genes = [f"GENE{index:04d}" for index in range(501)]
            bundles = [
                load_context_bundle(path)
                for path in _write_bundles(Path(tmp), genes=genes)
            ]
            manifest = _build_manifest(bundles, embedding_genes=genes[:-1])
            self.assertEqual(500, len(manifest["shared_genes"]))
            self.assertEqual(genes, manifest["feature_eligibility"]["source_shared_genes"])
            self.assertEqual(
                [genes[-1]], manifest["feature_eligibility"]["excluded_genes"]
            )
            self.assertEqual(
                "e" * 64,
                manifest["feature_eligibility"]["embedding_table_sha256"],
            )

    def test_split_is_deterministic_and_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = [load_context_bundle(path) for path in _write_bundles(root)]
            first = _build_manifest(bundles)
            second = _build_manifest(tuple(reversed(bundles)))
            self.assertEqual(first, second)
            output = root / "split.json"
            save_ood_split_manifest(first, output)
            save_ood_split_manifest(second, output)
            loaded = load_ood_split_manifest(output)
            self.assertEqual(first["split_id"], loaded["split_id"])
            tampered = _build_manifest(bundles, external_labels_sha256="d" * 64)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_ood_split_manifest(tampered, output)

    def test_rejects_wrong_context_set_low_overlap_and_reliability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_bundles(root)
            bundles = [load_context_bundle(path) for path in paths]
            wrong = list(bundles[:-1]) + [bundles[0]]
            with self.assertRaisesRegex(ValueError, "development contexts"):
                _build_manifest(wrong)

            small_paths = _write_bundles(root / "small", genes=[f"G{i}" for i in range(499)])
            small = [load_context_bundle(path) for path in small_paths]
            with self.assertRaisesRegex(ValueError, "500"):
                _build_manifest(small)

            payload = _bundle_payload(DEVELOPMENT_CONTEXTS[0])
            payload["reliability"]["median_split_half_spearman"] = 0.29
            paths[0].write_text(json.dumps(payload), encoding="utf-8")
            unreliable = [load_context_bundle(path) for path in paths]
            with self.assertRaisesRegex(ValueError, "reliability"):
                _build_manifest(unreliable)

    def test_manifest_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = [load_context_bundle(path) for path in _write_bundles(root)]
            manifest = _build_manifest(bundles)
            manifest["folds"][0]["test_genes"].append(manifest["folds"][0]["train_genes"][0])
            path = root / "bad.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "split_id|disjoint"):
                load_ood_split_manifest(path)

            manifest = _build_manifest(bundles)
            manifest["bundles"][DEVELOPMENT_CONTEXTS[0]]["sha256"] = "invalid"
            identity = dict(manifest)
            identity.pop("split_id")
            manifest["split_id"] = f"ood-split-{digest_payload(identity)[:16]}"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bundles.*sha256"):
                load_ood_split_manifest(path)

            manifest = _build_manifest(bundles)
            manifest["dims"][1] = manifest["dims"][0]
            identity = dict(manifest)
            identity.pop("split_id")
            manifest["split_id"] = f"ood-split-{digest_payload(identity)[:16]}"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                load_ood_split_manifest(path)

    def test_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = _write_bundles(root)
            embeddings = root / "embeddings.json"
            embeddings.write_text(
                json.dumps(
                    {
                        "schema_version": "mgba-gene-embedding-table-0.1",
                        "embedding_dim": 768,
                        "embeddings": {
                            f"GENE{index:04d}": [0.0] * 768 for index in range(500)
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = root / "split.json"
            stdout = StringIO()
            argv = ["mgba", "ood-split-build"]
            for path in bundles:
                argv.extend(["--bundle", str(path)])
            argv.extend(
                [
                    "--external-labels-sha256",
                    "c" * 64,
                    "--embeddings",
                    str(embeddings),
                    "--output",
                    str(output),
                ]
            )
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual(SPLIT_MANIFEST_SCHEMA_VERSION, result["schema_version"])
            self.assertEqual(20, result["folds"])
            self.assertEqual(500, result["shared_genes"])
            self.assertEqual(result["split_id"], load_ood_split_manifest(output)["split_id"])


class ContextPathwayEvaluationTests(unittest.TestCase):
    def test_external_test_is_one_shot_and_applies_paper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(
                root / "development", complete=True
            )
            prediction_path = root / "development-predictions.json"
            prediction_path.write_text(json.dumps(payload), encoding="utf-8")
            development = evaluate_context_pathway_predictions(
                [load_context_pathway_predictions(prediction_path)],
                split_path,
                bundle_paths,
            )
            development["coverage"]["folds"] = 20
            development["coverage"]["protocol_complete"] = True
            development["pass_rule"]["development_verdict"] = "passed"
            development["pass_rule"]["reasons"] = []
            development["selection"]["locked_external_hyperparameters"] = {
                "rule": "modal-development-fold-selection-lexicographic-tie-break",
                "rank": 8,
                "learning_rate": 0.001,
                "weight_decay": 0.0001,
            }
            identity = dict(development)
            identity.pop("evaluation_id")
            development["evaluation_id"] = (
                f"context-pathway-eval-{digest_payload(identity)[:16]}"
            )
            development_path = root / "development-evaluation.json"
            development_path.write_text(json.dumps(development), encoding="utf-8")

            external_payload = _bundle_payload(DEVELOPMENT_CONTEXTS[0])
            external_payload["dataset_id"] = "arc-virtual-cell-challenge"
            external_payload["context_id"] = EXTERNAL_CONTEXT_ID
            external_payload["source"]["sha256"] = "c" * 64
            external_bundle_path = root / "arc.json"
            external_bundle_path.write_text(json.dumps(external_payload), encoding="utf-8")
            external_targets = {
                unit["gene"]: [unit["target"][dim] for dim in _DIMS]
                for unit in external_payload["units"]
            }
            dev_targets = {
                (bundle.context_id, unit.gene): list(unit.target)
                for bundle in map(load_context_bundle, bundle_paths)
                for unit in bundle.units
            }
            split = load_ood_split_manifest(split_path)
            units = []
            model_artifacts = {}
            for salt in PRE_REGISTERED_SALTS:
                fold = next(item for item in split["folds"] if item["salt"] == salt)
                training_mean = _mean_vectors([
                    dev_targets[(context, gene)]
                    for context in DEVELOPMENT_CONTEXTS
                    for gene in fold["train_genes"]
                ])
                model_artifacts[salt] = "d" * 64
                for gene in fold["test_genes"]:
                    target = external_targets[gene]
                    predictions = {
                        "zero_response": [0.0] * 50,
                        "training_perturbed_mean": training_mean,
                        "gene_only_ridge": [value + 0.03 for value in target],
                        "context_only_ridge": [value + 0.04 for value in target],
                        "additive_ridge": [value + 0.02 for value in target],
                        "interaction_model": [value + 0.001 for value in target],
                        "gears": [value + 0.015 for value in target],
                        "scgpt": [value + 0.012 for value in target],
                        "biolord": [value + 0.01 for value in target],
                    }
                    units.append({
                        "salt": salt,
                        "gene": gene,
                        "predictions": predictions,
                    })
            units.sort(key=lambda item: (item["salt"], item["gene"]))
            external_predictions = {
                "schema_version": EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
                "study_id": split["study_id"],
                "development_evaluation_id": development["evaluation_id"],
                "split_manifest_sha256": _sha256(split_path),
                "context_id": EXTERNAL_CONTEXT_ID,
                "protocol_status": "locked-after-development",
                "hyperparameters": {
                    "rule": "modal-development-fold-selection-lexicographic-tie-break",
                    "rank": 8,
                    "learning_rate": 0.001,
                    "weight_decay": 0.0001,
                },
                "model_artifacts": model_artifacts,
                "predictors": payload["predictors"],
                "units": units,
            }
            external_predictions_path = root / "external-predictions.json"
            external_predictions_path.write_text(
                json.dumps(external_predictions), encoding="utf-8"
            )
            lock = root / "arc-access-lock.json"
            with self.assertRaisesRegex(ValueError, "development evidence"):
                evaluate_external_context_pathway_predictions(
                    external_predictions_path,
                    external_bundle_path,
                    development_path,
                    split_path,
                    bundle_paths,
                    lock,
                    [prediction_path],
                )
            self.assertFalse(lock.exists())
            with mock.patch(
                "mgba.context_pathway_evaluation.evaluate_context_pathway_predictions",
                return_value=development,
            ):
                result = evaluate_external_context_pathway_predictions(
                    external_predictions_path,
                    external_bundle_path,
                    development_path,
                    split_path,
                    bundle_paths,
                    lock,
                    [prediction_path],
                )
            self.assertEqual("go", result["pass_rule"]["paper_verdict"])
            self.assertEqual("consumed", result["coverage"]["external_test_status"])
            self.assertTrue(lock.exists())
            lock_payload = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(
                _sha256(external_predictions_path),
                lock_payload["external_prediction_sha256"],
            )
            with mock.patch(
                "mgba.context_pathway_evaluation.evaluate_context_pathway_predictions",
                return_value=development,
            ), self.assertRaisesRegex(ValueError, "already consumed"):
                evaluate_external_context_pathway_predictions(
                    external_predictions_path,
                    external_bundle_path,
                    development_path,
                    split_path,
                    bundle_paths,
                    lock,
                    [prediction_path],
                )

    def test_bootstrap_keeps_the_unit_weighting_of_the_primary_metric(self) -> None:
        result = _bootstrap_blocks([[1.0], [3.0, 3.0, 3.0]])
        self.assertEqual(2.5, result["mean_difference"])

    def test_known_gate_failure_is_failed_even_when_protocol_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            for unit in payload["units"]:
                target = unit["target"]
                unit["predictions"]["interaction_model"] = [
                    value + 1.0 for value in target
                ]
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed_fixture_split = load_ood_split_manifest(split_path)
            completed_fixture_split["folds"] = completed_fixture_split["folds"][:1]
            with mock.patch(
                "mgba.context_pathway_evaluation.load_ood_split_manifest",
                return_value=completed_fixture_split,
            ):
                result = evaluate_context_pathway_predictions(
                    [load_context_pathway_predictions(path)], split_path, bundle_paths
                )
            self.assertFalse(result["coverage"]["protocol_complete"])
            self.assertEqual("failed", result["pass_rule"]["development_verdict"])

    def test_context_only_ridge_can_be_the_best_simple_joint_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            for unit in payload["units"]:
                if unit["scenario"] == "joint_ood":
                    unit["predictions"]["context_only_ridge"] = [
                        value + 0.001 for value in unit["target"]
                    ]
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = evaluate_context_pathway_predictions(
                [load_context_pathway_predictions(path)], split_path, bundle_paths
            )
            self.assertEqual("context_only_ridge", result["selection"]["best_simple"])

    def test_complete_folds_allow_distinct_learned_artifact_digests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, split_path, bundle_paths = _prediction_payload(
                root / "first", complete=True, fold_index=0
            )
            second, second_split, _ = _prediction_payload(
                root / "second", complete=True, fold_index=1
            )
            self.assertEqual(_sha256(split_path), _sha256(second_split))
            for predictor in ("gears", "scgpt", "biolord"):
                second["learned_sources"][predictor]["artifact"]["path"] = (
                    f"second-{predictor}.json"
                )
                second["learned_sources"][predictor]["artifact"]["sha256"] = "a" * 64
            paths = []
            for name, payload in (("first", first), ("second", second)):
                path = root / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)
            result = evaluate_context_pathway_predictions(
                [load_context_pathway_predictions(path) for path in paths],
                split_path,
                bundle_paths,
            )
            self.assertEqual(2, result["coverage"]["folds"])

    def test_load_and_evaluate_one_development_fold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            predictions = load_context_pathway_predictions(path)
            result = evaluate_context_pathway_predictions(
                [predictions], split_path, bundle_paths
            )
            self.assertEqual(EVALUATION_SCHEMA_VERSION, result["schema_version"])
            self.assertEqual("incomplete", result["pass_rule"]["development_verdict"])
            self.assertEqual("sealed", result["pass_rule"]["paper_verdict"])
            self.assertEqual(1, result["coverage"]["folds"])
            joint = result["metrics"]["joint_ood"]
            self.assertLess(
                joint["interaction_model"]["standardized_macro_mae"],
                joint["additive_ridge"]["standardized_macro_mae"],
            )
            self.assertEqual(75, joint["interaction_model"]["unit_count"])
            self.assertEqual(10000, result["statistics"]["bootstrap_resamples"])
            self.assertIn(
                "p_value_bh",
                result["statistics"]["secondary_comparisons"]
                ["mean_pathway_spearman"]["zero_response"],
            )
            self.assertIn(
                "best_simple_id",
                result["selection"]["per_context"][DEVELOPMENT_CONTEXTS[0]],
            )
            joint_units = [
                unit for unit in payload["units"] if unit["scenario"] == "joint_ood"
            ]
            expected_spearman = fmean(
                spearman(
                    [unit["target"][index] for unit in joint_units],
                    [
                        unit["predictions"]["training_perturbed_mean"][index]
                        for unit in joint_units
                    ],
                )
                for index in range(HALLMARK_DIM_COUNT)
            )
            self.assertAlmostEqual(
                expected_spearman,
                joint["training_perturbed_mean"]["mean_pathway_spearman"],
            )

    def test_target_and_simple_baseline_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            payload["units"][0]["target"][0] += 1e-6
            path = root / "target-tamper.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target tampered"):
                evaluate_context_pathway_predictions(
                    [load_context_pathway_predictions(path)], split_path, bundle_paths
                )

            payload, split_path, bundle_paths = _prediction_payload(root / "baseline")
            payload["units"][0]["predictions"]["zero_response"][0] = 0.1
            path = root / "baseline" / "baseline-tamper.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "zero_response"):
                evaluate_context_pathway_predictions(
                    [load_context_pathway_predictions(path)], split_path, bundle_paths
                )

    def test_scenario_leakage_and_premature_complete_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            payload["units"][0]["scenario"] = "gene_ood"
            path = root / "leak.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "coverage|scenario"):
                evaluate_context_pathway_predictions(
                    [load_context_pathway_predictions(path)], split_path, bundle_paths
                )

            payload, _, _ = _prediction_payload(root / "complete")
            payload["protocol_status"] = "complete"
            path = root / "complete" / "premature.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "learned predictors"):
                load_context_pathway_predictions(path)

    def test_prediction_manifest_digest_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            payload["split_manifest_sha256"] = "e" * 64
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "split manifest SHA-256"):
                evaluate_context_pathway_predictions(
                    [load_context_pathway_predictions(path)], split_path, bundle_paths
                )

    def test_prediction_embedding_digest_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            payload["feature_source"]["sha256"] = "f" * 64
            path = root / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "feature source"):
                evaluate_context_pathway_predictions(
                    [load_context_pathway_predictions(path)], split_path, bundle_paths
                )

    def test_evaluation_is_write_once_and_cli_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, split_path, bundle_paths = _prediction_payload(root)
            predictions_path = root / "predictions.json"
            predictions_path.write_text(json.dumps(payload), encoding="utf-8")
            output = root / "evaluation.json"
            stdout = StringIO()
            argv = [
                "mgba",
                "context-pathway-evaluate",
                "--predictions",
                str(predictions_path),
                "--split",
                str(split_path),
                "--output",
                str(output),
            ]
            for bundle in bundle_paths:
                argv.extend(["--bundle", str(bundle)])
            with mock.patch("sys.argv", argv), redirect_stdout(stdout):
                cli_main()
            result = json.loads(stdout.getvalue())
            self.assertEqual("incomplete", result["development_verdict"])
            self.assertEqual("sealed", result["paper_verdict"])
            saved = json.loads(output.read_text(encoding="utf-8"))
            save_context_pathway_evaluation(saved, output)
            self.assertEqual(result["evaluation_id"], saved["evaluation_id"])


if __name__ == "__main__":
    unittest.main()
