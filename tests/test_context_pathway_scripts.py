"""Small executable checks for the independent context-pathway scripts."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy import sparse
except ImportError:  # Core/dev installs intentionally omit training dependencies.
    ad = np = pd = sparse = None

from mgba.context_pathway import DEVELOPMENT_CONTEXTS, load_context_bundle


_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = _ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(ad is not None, "requires the independent training environment")
class ContextPathwayBundleScriptTests(unittest.TestCase):
    def test_builds_valid_bundle_from_h5ad(self) -> None:
        builder = _load_script("build_context_pathway_bundle.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            genes = [f"G{index:02d}" for index in range(50)]
            rng = np.random.default_rng(7)
            control = rng.poisson(4.0, size=(60, 50)).astype(np.float32) + 1.0
            perturbed = rng.poisson(4.0, size=(60, 50)).astype(np.float32) + 1.0
            perturbed += np.arange(50, dtype=np.float32) % 6
            data = ad.AnnData(
                X=sparse.csr_matrix(np.vstack((control, perturbed))),
                obs=pd.DataFrame(
                    {"perturbation": ["control"] * 60 + ["TP53"] * 60}
                ),
                var=pd.DataFrame({"gene_symbol": genes}, index=genes),
            )
            h5ad = root / "input.h5ad"
            data.write_h5ad(h5ad)
            hallmark = root / "hallmark.gmt"
            hallmark.write_text(
                "".join(
                    f"HALLMARK_TEST_{index:02d}\tdescription\t{gene}\n"
                    for index, gene in enumerate(genes)
                ),
                encoding="utf-8",
            )
            output = root / "bundle.json"
            payload = builder.build_bundle(
                h5ad,
                hallmark,
                output,
                dataset_id="fixture",
                context_id=DEVELOPMENT_CONTEXTS[0],
                perturbation_key="perturbation",
                gene_key="gene_symbol",
                control_label="control",
                source_license="fixture-license",
                hallmark_version="fixture",
                hallmark_license="fixture-terms",
            )
            loaded = load_context_bundle(output)
            self.assertEqual("fixture", loaded.dataset_id)
            self.assertEqual(60, loaded.control_cells)
            self.assertEqual("TP53", loaded.units[0].gene)
            self.assertEqual(50, len(loaded.units[0].target))
            self.assertEqual(payload["reliability"], {
                "resamples": 20,
                "seed": 20260903,
                "median_split_half_spearman": loaded.median_split_half_spearman,
            })

    def test_ignores_duplicate_symbols_outside_hallmark(self) -> None:
        builder = _load_script("build_context_pathway_bundle.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hallmark_genes = [f"G{index:02d}" for index in range(50)]
            genes = hallmark_genes + ["UNUSED", "UNUSED"]
            data = ad.AnnData(
                X=sparse.csr_matrix(np.ones((120, len(genes)), dtype=np.float32)),
                obs=pd.DataFrame(
                    {"perturbation": ["control"] * 60 + ["TP53"] * 60}
                ),
                var=pd.DataFrame({"gene_symbol": genes}),
            )
            h5ad = root / "input.h5ad"
            data.write_h5ad(h5ad)
            hallmark = root / "hallmark.gmt"
            hallmark.write_text(
                "".join(
                    f"HALLMARK_TEST_{index:02d}\tdescription\t{gene}\n"
                    for index, gene in enumerate(hallmark_genes)
                ),
                encoding="utf-8",
            )
            payload = builder.build_bundle(
                h5ad,
                hallmark,
                root / "bundle.json",
                dataset_id="fixture",
                context_id=DEVELOPMENT_CONTEXTS[0],
                perturbation_key="perturbation",
                gene_key="gene_symbol",
                control_label="control",
                source_license="fixture-license",
                hallmark_version="fixture",
                hallmark_license="fixture-terms",
            )
            self.assertEqual(1, len(payload["units"]))

    def test_rejects_non_raw_counts(self) -> None:
        builder = _load_script("build_context_pathway_bundle.py")
        for bad_value in (-1.0, 0.5, float("nan")):
            with self.subTest(bad_value=bad_value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                genes = [f"G{index:02d}" for index in range(50)]
                matrix = np.ones((120, 50), dtype=np.float32)
                matrix[0, 0] = bad_value
                data = ad.AnnData(
                    X=sparse.csr_matrix(matrix),
                    obs=pd.DataFrame(
                        {"perturbation": ["control"] * 60 + ["TP53"] * 60}
                    ),
                    var=pd.DataFrame({"gene_symbol": genes}, index=genes),
                )
                h5ad = root / "input.h5ad"
                data.write_h5ad(h5ad)
                hallmark = root / "hallmark.gmt"
                hallmark.write_text(
                    "".join(
                        f"HALLMARK_TEST_{index:02d}\tdescription\t{gene}\n"
                        for index, gene in enumerate(genes)
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "raw counts"):
                    builder.build_bundle(
                        h5ad,
                        hallmark,
                        root / "bundle.json",
                        dataset_id="fixture",
                        context_id=DEVELOPMENT_CONTEXTS[0],
                        perturbation_key="perturbation",
                        gene_key="gene_symbol",
                        control_label="control",
                        source_license="fixture-license",
                        hallmark_version="fixture",
                        hallmark_license="fixture-terms",
                    )


@unittest.skipUnless(ad is not None, "requires the independent training environment")
class ContextPathwayTrainingScriptTests(unittest.TestCase):
    def test_baseline_screen_summarizes_unit_losses(self) -> None:
        screener = _load_script("screen_context_pathway_baselines.py")
        result = screener._summary(
            {"joint_ood": {"zero_response": [1.0, 3.0]}}
        )
        self.assertEqual(
            {
                "standardized_macro_mae": 2.0,
                "unit_count": 2,
            },
            result["joint_ood"]["zero_response"],
        )

    def test_low_rank_fit_is_seed_replayable(self) -> None:
        trainer = _load_script("train_context_pathway.py")
        rng = np.random.default_rng(9)
        perturbation = rng.normal(size=(18, 4)).astype(np.float32)
        context = rng.normal(size=(18, 3)).astype(np.float32)
        target = rng.normal(size=(18, 2)).astype(np.float32)
        validation = (
            perturbation[:6],
            context[:6],
            target[:6],
        )
        first = trainer.fit_low_rank(
            perturbation,
            context,
            target,
            validation,
            rank=2,
            learning_rate=1e-3,
            weight_decay=1e-4,
            seed=17,
            max_epochs=12,
            patience=4,
            device="cpu",
        )
        second = trainer.fit_low_rank(
            perturbation,
            context,
            target,
            validation,
            rank=2,
            learning_rate=1e-3,
            weight_decay=1e-4,
            seed=17,
            max_epochs=12,
            patience=4,
            device="cpu",
        )
        self.assertTrue(np.array_equal(first[1], second[1]))
        self.assertEqual(first[2], second[2])

    def test_learned_import_rejects_duplicate_units(self) -> None:
        trainer = _load_script("train_context_pathway.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gears.json"
            unit = {
                "context_id": "replogle-k562",
                "gene": "TP53",
                "prediction": [0.0] * 50,
            }
            path.write_text(json.dumps({
                "schema_version": trainer.LEARNED_SCHEMA_VERSION,
                "predictor_id": "gears",
                "implementation": {
                    "repository": trainer.OFFICIAL_LEARNED_REPOSITORIES["gears"],
                    "commit": "f" * 40,
                    "version": "fixture",
                },
                "mapping": {
                    "source_space": "full-expression",
                    "target_space": "hallmark-50-unweighted-log2fc-mean",
                    "hallmark_sha256": "b" * 64,
                },
                "fold_id": "fold",
                "split_manifest_sha256": "a" * 64,
                "dims": [f"HALLMARK_TEST_{index:02d}" for index in range(50)],
                "units": [unit, unit],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                trainer._load_learned(
                    {"gears": path, "scgpt": path, "biolord": path},
                    fold_id="fold",
                    split_digest="a" * 64,
                    dims=[f"HALLMARK_TEST_{index:02d}" for index in range(50)],
                    expected={("replogle-k562", "TP53")},
                    hallmark_sha256="b" * 64,
                )


if __name__ == "__main__":
    unittest.main()
