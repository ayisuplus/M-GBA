"""Tests for the deterministic calibration core (ADR-0018).

Covers protocol fail-fast validation, seeded-sampler determinism and
box bounds, search-core behavior on a synthetic quadratic objective
(determinism, dedup, never-worse-than-incumbent, refinement
improvement), objective contract enforcement, write-once artifact
discipline, a tiny real-runner wiring smoke, and the frozen reference
L2 config guard.
"""

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mgba.calibration import (
    L2_SCALAR_PARAMETERS,
    CalibrationProtocol,
    CalibrationResult,
    run_search,
    sample_candidates,
    save_calibration_artifacts,
)
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"


def _protocol(**overrides) -> CalibrationProtocol:
    base = dict(
        model_version="test-calibration",
        search_seed=1234,
        candidate_count=16,
        max_evaluations=100,
        top_k=2,
        refinement_steps=(0.1, 0.05),
        max_sweeps=2,
        ticks=5,
        parameter_names=("a", "b", "c", "d"),
    )
    base.update(overrides)
    return CalibrationProtocol(**base)


class CalibrationProtocolValidationTests(unittest.TestCase):
    def test_illegal_protocols_fail_fast(self) -> None:
        cases = (
            {"model_version": " "},
            {"search_seed": -1},
            {"search_seed": True},
            {"search_seed": 1.5},
            {"candidate_count": 0},
            {"candidate_count": True},
            {"max_evaluations": 0},
            {"max_evaluations": True},
            {"max_evaluations": 15},
            {"top_k": 0},
            {"top_k": 99},
            {"refinement_steps": ()},
            {"refinement_steps": (0.0,)},
            {"refinement_steps": (math.nan,)},
            {"refinement_steps": (0.6,)},
            {"max_sweeps": 0},
            {"ticks": 0},
            {"parameter_names": ()},
            {"parameter_names": ("a", "a")},
            {"parameter_names": ("a", "  ")},
        )
        for overrides in cases:
            with self.assertRaises((ValueError, TypeError), msg=overrides):
                _protocol(**overrides)

    def test_shipped_parameter_names_match_cell_config(self) -> None:
        config = load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
        for name in L2_SCALAR_PARAMETERS:
            getattr(config, name)  # raises AttributeError if drifted
        self.assertEqual(19, len(L2_SCALAR_PARAMETERS))


class SeededSamplerTests(unittest.TestCase):
    def test_determinism_bounds_and_count(self) -> None:
        protocol = _protocol(candidate_count=64)
        first = sample_candidates(protocol)
        second = sample_candidates(protocol)
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))
        self.assertEqual(64, len(set(first)))
        for point in first:
            self.assertEqual(4, len(point))
            for value in point:
                self.assertGreaterEqual(value, 0.0)
                self.assertLess(value, 1.0)

    def test_seed_sensitivity(self) -> None:
        self.assertNotEqual(
            sample_candidates(_protocol(search_seed=1)),
            sample_candidates(_protocol(search_seed=2)),
        )


class SearchCoreTests(unittest.TestCase):
    TARGET = (0.8, 0.2, 0.6, 0.4)

    def _objective(self, point: tuple[float, ...]) -> float:
        return 1.0 - sum(
            (value - target) ** 2
            for value, target in zip(point, self.TARGET, strict=True)
        ) / len(point)

    def test_search_improves_over_incumbent_and_is_deterministic(self) -> None:
        protocol = _protocol(candidate_count=64, top_k=2, max_sweeps=3)
        incumbent = (0.5, 0.5, 0.5, 0.5)
        first = run_search(protocol, self._objective, incumbents=(incumbent,))
        second = run_search(protocol, self._objective, incumbents=(incumbent,))
        self.assertEqual(first.evaluations, second.evaluations)
        self.assertEqual(first.best_point, second.best_point)
        incumbent_score = self._objective(incumbent)
        self.assertGreater(first.best_score, incumbent_score)
        self.assertEqual("incumbent", first.evaluations[0].phase)
        self.assertEqual(incumbent, first.evaluations[0].point)

    def test_no_point_is_evaluated_twice(self) -> None:
        protocol = _protocol(candidate_count=32)
        result = run_search(protocol, self._objective, incumbents=((0.5,) * 4,))
        points = [item.point for item in result.evaluations]
        self.assertEqual(len(points), len(set(points)))

    def test_search_stops_at_explicit_evaluation_budget(self) -> None:
        protocol = _protocol(
            candidate_count=8,
            max_evaluations=12,
            top_k=2,
            max_sweeps=5,
        )
        result = run_search(protocol, self._objective, incumbents=((0.5,) * 4,))
        self.assertEqual(12, len(result.evaluations))
        self.assertEqual(12, result.summary_dict()["protocol"]["max_evaluations"])

    def test_budget_must_cover_incumbents_and_random_sweep(self) -> None:
        protocol = _protocol(candidate_count=8, max_evaluations=8)
        with self.assertRaisesRegex(ValueError, "incumbents and random candidates"):
            run_search(protocol, self._objective, incumbents=((0.5,) * 4,))

    def test_refinement_nearest_neighbor_of_best_random(self) -> None:
        protocol = _protocol(candidate_count=8, top_k=1, max_sweeps=2)
        result = run_search(protocol, self._objective)
        random_best = max(
            item.score for item in result.evaluations if item.phase == "random"
        )
        self.assertGreaterEqual(result.best_score, random_best)

    def test_objective_contract_enforced(self) -> None:
        protocol = _protocol(candidate_count=2)
        with self.assertRaises(ValueError):
            run_search(protocol, lambda point: math.nan)
        with self.assertRaises(ValueError):
            run_search(protocol, lambda point: math.inf)
        with self.assertRaises(TypeError):
            run_search(protocol, lambda point: True)

    def test_incumbent_validation(self) -> None:
        protocol = _protocol(candidate_count=2)
        with self.assertRaises(ValueError):
            run_search(protocol, self._objective, incumbents=((0.5, 0.5),))
        with self.assertRaises(ValueError):
            run_search(protocol, self._objective, incumbents=((1.5,) * 4,))

    def test_result_validation(self) -> None:
        protocol = _protocol()
        with self.assertRaises(ValueError):
            CalibrationResult(
                protocol=protocol,
                evaluations=(),
                best_point=(0.0,) * 4,
                best_score=0.0,
            )


class ArtifactDisciplineTests(unittest.TestCase):
    def test_write_once_and_conflict_refusal(self) -> None:
        protocol = _protocol(candidate_count=4, top_k=1, max_sweeps=1)
        result = run_search(protocol, lambda point: sum(point))
        with tempfile.TemporaryDirectory() as tmp:
            first = save_calibration_artifacts(tmp, result)
            # Re-writing the identical payload under the same digest is a no-op.
            second = save_calibration_artifacts(tmp, result)
            self.assertEqual(first, second)
            summary = json.loads(first["summary"].read_text(encoding="utf-8"))
            self.assertEqual(
                "mgba-calibration-artifact-0.1", summary["schema_version"]
            )
            # A tampered payload with the same search digest (same directory)
            # must be refused: the digest covers protocol+evaluations, while
            # the summary also carries best_score.
            tampered = replace(result, best_score=result.best_score + 0.25)
            self.assertEqual(result.search_digest, tampered.search_digest)
            with self.assertRaises(ValueError):
                save_calibration_artifacts(tmp, tampered)
            # A different protocol writes a separate digest directory.
            other = run_search(
                _protocol(candidate_count=4, top_k=1, max_sweeps=1, search_seed=9),
                lambda point: sum(point),
            )
            third = save_calibration_artifacts(tmp, other)
            self.assertNotEqual(first["root"], third["root"])


class WiringSmokeTests(unittest.TestCase):
    """Tiny real-runner pass proving the script's objective wiring works."""

    def test_tiny_budget_end_to_end(self) -> None:
        scenario = load_multiscale_scenario(ROOT / "configs" / "multiscale_demo.json")
        runner_config = load_runner_config(ROOT / "configs" / "runner_reference.json")
        reference_config = load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
        reference_point = tuple(
            getattr(reference_config, name) for name in L2_SCALAR_PARAMETERS
        )

        def models(cell_config):
            return {
                "genome_model": DiscreteGrnModel(
                    load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json")
                ),
                "molecular_model": CoarseMolecularModel(
                    load_molecular_config(
                        LAYER_CONFIGS / "l1_reference_molecular.json"
                    )
                ),
                "cell_model": CellStateMachineModel(cell_config),
                "tissue_model": TissueEnvironmentModel(
                    load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
                ),
                "phenotype_model": PhenotypeObserverModel(
                    load_phenotype_config(LAYER_CONFIGS / "l4_reference_phenotype.json")
                ),
            }

        def objective(point):
            candidate = replace(
                reference_config,
                model_version="calibrated-l2-cell-state-machine-0.1",
                **dict(zip(L2_SCALAR_PARAMETERS, point, strict=True)),
            )
            run = MultirateCrossScaleRunner(runner_config, **models(candidate)).run(
                scenario, ticks=5
            )
            return run.phenotype_window.mean_homeostasis

        protocol = _protocol(
            candidate_count=4, top_k=1, max_sweeps=1, parameter_names=L2_SCALAR_PARAMETERS
        )
        result = run_search(protocol, objective, incumbents=(reference_point,))
        self.assertEqual(19, len(result.best_point))
        for item in result.evaluations:
            self.assertGreaterEqual(item.score, 0.0)
            self.assertLessEqual(item.score, 1.0)
        self.assertEqual(result.evaluations[0].score, objective(reference_point))


class FrozenReferenceCellConfigGuardTests(unittest.TestCase):
    def test_reference_l2_config_unchanged(self) -> None:
        config = load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
        self.assertEqual("reference-l2-cell-state-machine-0.1", config.model_version)
        self.assertEqual(0.7, config.stress_environment_weight)
        self.assertEqual(0.45, config.stress_threshold)
        self.assertEqual(0.65, config.death_drive_threshold)


if __name__ == "__main__":
    unittest.main()
