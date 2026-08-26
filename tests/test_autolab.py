"""Tests for the deterministic autolab experiment-scheduling meta-layer.

Covers registry/config fail-fast validation, the frozen screen-then-confirm
policy (adaptivity, determinism, budget enforcement), the fail-closed
proposal channel (never executes), and a real-runner smoke test that
rediscovers the WP8 leverage point on the demo scenario.
"""

import unittest
from dataclasses import replace
from pathlib import Path

from mgba.autolab import (
    AutolabConfig,
    AutolabSession,
    EvaluatorResult,
    Hypothesis,
    build_autolab_manifest,
    load_autolab_config,
    load_proposal_file,
    validate_proposals,
)
from mgba.autolab_planning import (
    compile_autolab_plan,
    verify_autolab_plan,
    verify_autolab_result,
)
from mgba.experiments import ConditionKind, CausalRunRecord, _compare_runs
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import (
    CoarseMolecularModel,
    StaticMolecularModel,
    load_molecular_config,
)
from mgba.layers.l2 import CellStateMachineModel, StaticCellModel, load_cell_config
from mgba.layers.l3 import (
    StaticTissueModel,
    TissueEnvironmentModel,
    load_tissue_config,
)
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"
_METRICS = (
    "damage_burden",
    "homeostasis",
    "inflammation",
    "recovery_capacity",
    "vitality",
)


def _hypothesis(
    hypothesis_id: str = "l2-static",
    layer: str = "L2",
    priority: float = 1.0,
    kind: str = "layer_static_swap",
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id, kind=kind, layer=layer, priority=priority
    )


def _registry() -> tuple[Hypothesis, ...]:
    return (
        _hypothesis("l1-static", "L1"),
        _hypothesis("l2-static", "L2"),
        _hypothesis("l3-static", "L3"),
    )


def _config(**overrides) -> AutolabConfig:
    values = {
        "model_version": "autolab-test-0.1",
        "seeds": (7, 42),
        "probe_ticks": 10,
        "confirm_ticks": 20,
        "confirm_top_k": 1,
        "budget": 8,
        "hypotheses": _registry(),
    }
    values.update(overrides)
    return AutolabConfig(**values)


def _scripted_evaluator(effects: dict[str, float]):
    """Evaluator stub: each metric carries the scripted signed value."""

    def evaluate(hypothesis, ticks, seeds) -> EvaluatorResult:
        value = effects[hypothesis.hypothesis_id]
        return EvaluatorResult(
            per_seed_metric_effects=tuple(
                (seed, tuple((metric, value) for metric in _METRICS))
                for seed in seeds
            ),
            history_digests=tuple(
                (seed, f"digest-{hypothesis.hypothesis_id}-{seed}")
                for seed in seeds
            ),
        )

    return evaluate


class AutolabConfigCrashPreventionTests(unittest.TestCase):
    def test_illegal_config_fields_fail_fast(self) -> None:
        cases = (
            ("seeds", (42, 7)),
            ("seeds", (7, 7)),
            ("seeds", (-1, 7)),
            ("seeds", (True, 7)),
            ("seeds", (7,)),
            ("probe_ticks", 0),
            ("confirm_ticks", True),
            ("confirm_top_k", 0),
            ("budget", 0),
            ("model_version", "  "),
            ("hypotheses", ()),
        )
        for field, value in cases:
            with self.assertRaises(ValueError, msg=f"{field}={value}"):
                _config(**{field: value})

    def test_duplicate_hypothesis_ids_fail_fast(self) -> None:
        with self.assertRaises(ValueError):
            _config(
                hypotheses=(
                    _hypothesis("dup", "L1"),
                    _hypothesis("dup", "L2"),
                )
            )

    def test_illegal_hypothesis_fields_fail_fast(self) -> None:
        with self.assertRaises(ValueError):
            _hypothesis(kind="read_l0_directly")
        with self.assertRaises(ValueError):
            _hypothesis(layer="L0")
        with self.assertRaises(ValueError):
            _hypothesis(layer="L4")
        with self.assertRaises(ValueError):
            _hypothesis(priority=float("nan"))
        with self.assertRaises(ValueError):
            _hypothesis(hypothesis_id="has space")

    def test_missing_config_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "experiments" / "autolab_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_autolab_config(missing)

    def test_screening_order_is_frozen(self) -> None:
        config = _config(
            hypotheses=(
                _hypothesis("b-late", "L1", priority=0.5),
                _hypothesis("a-first", "L2", priority=2.0),
                _hypothesis("c-mid", "L3", priority=2.0),
            )
        )
        order = [item.hypothesis_id for item in config.screening_order]
        self.assertEqual(["a-first", "c-mid", "b-late"], order)


class AutolabSessionTests(unittest.TestCase):
    def test_session_is_deterministic(self) -> None:
        effects = {"l1-static": 0.01, "l2-static": 0.5, "l3-static": 0.2}
        config = _config()
        first = AutolabSession(
            config, evaluate=_scripted_evaluator(effects)
        ).run()
        second = AutolabSession(
            config, evaluate=_scripted_evaluator(effects)
        ).run()
        self.assertEqual(first.session_id, second.session_id)
        self.assertEqual(first.decision_log, second.decision_log)
        self.assertEqual(first.evaluations, second.evaluations)

    def test_confirm_round_follows_probe_measurements(self) -> None:
        effects = {"l1-static": 0.01, "l2-static": 0.5, "l3-static": 0.2}
        result = AutolabSession(
            _config(), evaluate=_scripted_evaluator(effects)
        ).run()
        self.assertEqual("l2-static", result.leader)
        self.assertEqual(("l2-static",), result.confirmed)
        self.assertEqual((), result.pending)
        phases = [(item.phase, item.hypothesis_id) for item in result.evaluations]
        self.assertEqual(
            [
                ("probe", "l1-static"),
                ("probe", "l2-static"),
                ("probe", "l3-static"),
                ("confirm", "l2-static"),
            ],
            phases,
        )
        confirm = result.evaluations[-1]
        self.assertEqual(20, confirm.ticks)
        self.assertIn("0.5", result.decision_log[-1].rationale)

    def test_effect_scalar_uses_mean_absolute_metrics(self) -> None:
        effects = {"l1-static": -0.4, "l2-static": 0.1, "l3-static": 0.2}
        result = AutolabSession(
            _config(confirm_top_k=1), evaluate=_scripted_evaluator(effects)
        ).run()
        probe_effects = {
            item.hypothesis_id: item.effect
            for item in result.evaluations
            if item.phase == "probe"
        }
        self.assertAlmostEqual(0.4, probe_effects["l1-static"])
        self.assertEqual("l1-static", result.leader)

    def test_top_k_confirms_in_rank_order(self) -> None:
        effects = {"l1-static": 0.01, "l2-static": 0.5, "l3-static": 0.2}
        result = AutolabSession(
            _config(confirm_top_k=2), evaluate=_scripted_evaluator(effects)
        ).run()
        self.assertEqual(("l2-static", "l3-static"), result.confirmed)

    def test_budget_exhaustion_leaves_pending(self) -> None:
        effects = {"l1-static": 0.01, "l2-static": 0.5, "l3-static": 0.2}
        result = AutolabSession(
            _config(budget=2), evaluate=_scripted_evaluator(effects)
        ).run()
        self.assertEqual(2, len(result.evaluations))
        self.assertEqual(("l3-static",), result.pending)
        self.assertIsNone(result.leader)

    def test_evaluator_seed_mismatch_fails(self) -> None:
        def bad_evaluator(hypothesis, ticks, seeds) -> EvaluatorResult:
            return EvaluatorResult(
                per_seed_metric_effects=(
                    (seeds[0], tuple((metric, 0.1) for metric in _METRICS)),
                ),
                history_digests=((seeds[0], "d"),),
            )

        with self.assertRaises(ValueError):
            AutolabSession(_config(), evaluate=bad_evaluator).run()

    def test_incomplete_metric_vector_fails(self) -> None:
        def bad_evaluator(hypothesis, ticks, seeds) -> EvaluatorResult:
            return EvaluatorResult(
                per_seed_metric_effects=tuple(
                    (seed, (("homeostasis", 0.1),)) for seed in seeds
                ),
                history_digests=tuple((seed, "d") for seed in seeds),
            )

        with self.assertRaises(ValueError):
            AutolabSession(_config(), evaluate=bad_evaluator).run()


class AutolabProposalTests(unittest.TestCase):
    def _valid_proposal(self, hypothesis_id: str = "l2-variant") -> dict:
        return {
            "proposal_id": "p-1",
            "proposed_by": "llm",
            "rationale": "probe the L2 axis further",
            "hypothesis": {
                "hypothesis_id": hypothesis_id,
                "kind": "layer_static_swap",
                "layer": "L2",
                "priority": 0.5,
            },
        }

    def test_valid_proposal_is_accepted_but_never_executed(self) -> None:
        report = validate_proposals(
            [self._valid_proposal()], registry_ids=["l1-static"]
        )
        payload = report.summary_dict()
        self.assertFalse(payload["executed"])
        self.assertEqual(1, payload["counts"]["accepted"])
        self.assertEqual(0, payload["counts"]["rejected"])

    def test_unknown_kind_is_rejected_with_reason(self) -> None:
        proposal = self._valid_proposal()
        proposal["hypothesis"]["kind"] = "skip_l1_read_genes"
        report = validate_proposals([proposal], registry_ids=[])
        verdict = report.verdicts[0]
        self.assertEqual("rejected", verdict.status)
        self.assertTrue(any("kind" in reason for reason in verdict.reasons))

    def test_registry_collision_and_in_file_duplicate_are_rejected(self) -> None:
        report = validate_proposals(
            [self._valid_proposal("l1-static")], registry_ids=["l1-static"]
        )
        self.assertEqual("rejected", report.verdicts[0].status)
        duplicates = [self._valid_proposal(), self._valid_proposal()]
        report = validate_proposals(duplicates, registry_ids=[])
        self.assertEqual("accepted_for_registry_review", report.verdicts[0].status)
        self.assertEqual("rejected", report.verdicts[1].status)

    def test_malformed_proposals_never_raise(self) -> None:
        report = validate_proposals(
            ["not-an-object", {"hypothesis": {}}, {"proposal_id": 3}],
            registry_ids=[],
        )
        self.assertEqual(3, report.summary_dict()["counts"]["rejected"])

    def test_invalid_proposal_file_raises_value_error(self) -> None:
        missing = ROOT / "configs" / "experiments" / "proposals_missing.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            load_proposal_file(missing)


class AutolabRealRunnerTests(unittest.TestCase):
    """Real paired-run smoke: the loop must rediscover the WP8 leverage point."""

    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_demo.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )
        self.base_config = load_autolab_config(
            ROOT / "configs" / "experiments" / "autolab_screen.json"
        )

    def _layer_models(self, variant: str) -> dict:
        models = {
            "genome_model": DiscreteGrnModel(
                load_grn_config(LAYER_CONFIGS / "l0_reference_grn.json")
            ),
            "molecular_model": CoarseMolecularModel(
                load_molecular_config(LAYER_CONFIGS / "l1_reference_molecular.json")
            ),
            "cell_model": CellStateMachineModel(
                load_cell_config(LAYER_CONFIGS / "l2_reference_cell.json")
            ),
            "tissue_model": TissueEnvironmentModel(
                load_tissue_config(LAYER_CONFIGS / "l3_reference_tissue.json")
            ),
            "phenotype_model": PhenotypeObserverModel(
                load_phenotype_config(LAYER_CONFIGS / "l4_reference_phenotype.json")
            ),
        }
        if variant == "l1_static":
            models["molecular_model"] = StaticMolecularModel()
        elif variant == "l2_static":
            models["cell_model"] = StaticCellModel()
        elif variant == "l3_static":
            models["tissue_model"] = StaticTissueModel()
        return models

    def _evaluate(self, hypothesis, ticks, seeds) -> EvaluatorResult:
        variant_by_layer = {"L1": "l1_static", "L2": "l2_static", "L3": "l3_static"}
        baseline_runner = MultirateCrossScaleRunner(
            self.runner_config, **self._layer_models("baseline")
        )
        condition_runner = MultirateCrossScaleRunner(
            self.runner_config,
            **self._layer_models(variant_by_layer[hypothesis.layer]),
        )
        per_seed = []
        digests = []
        for seed in seeds:
            seeded = replace(self.scenario, seed=seed)
            baseline_run = baseline_runner.run(seeded, ticks=ticks)
            condition_run = condition_runner.run(seeded, ticks=ticks)
            comparison = _compare_runs(
                CausalRunRecord(
                    condition_id="baseline",
                    condition_kind=ConditionKind.BASELINE,
                    seed=seed,
                    run=baseline_run,
                ),
                CausalRunRecord(
                    condition_id=hypothesis.hypothesis_id,
                    condition_kind=ConditionKind.PERTURBATION,
                    seed=seed,
                    run=condition_run,
                ),
            )
            per_seed.append((seed, comparison.final_metric_effects))
            digests.append((seed, condition_run.history_digest))
        return EvaluatorResult(
            per_seed_metric_effects=tuple(per_seed),
            history_digests=tuple(digests),
        )

    def test_loop_rediscovers_l2_leverage_point_deterministically(self) -> None:
        config = replace(self.base_config, seeds=(41, 42), confirm_ticks=30)
        plan = compile_autolab_plan(config)
        self.assertTrue(verify_autolab_plan(plan, config).valid)
        first = AutolabSession(config, evaluate=self._evaluate).run()
        self.assertEqual("l2-static", first.leader)
        self.assertEqual(("l2-static",), first.confirmed)
        self.assertEqual(4, len(first.evaluations))
        probe_effects = {
            item.hypothesis_id: item.effect
            for item in first.evaluations
            if item.phase == "probe"
        }
        self.assertGreater(probe_effects["l2-static"], probe_effects["l1-static"])
        self.assertGreater(probe_effects["l2-static"], probe_effects["l3-static"])
        second = AutolabSession(config, evaluate=self._evaluate).run()
        self.assertEqual(first.session_id, second.session_id)
        self.assertEqual(first.decision_log, second.decision_log)
        self.assertEqual(
            [item.history_digests for item in first.evaluations],
            [item.history_digests for item in second.evaluations],
        )
        verification = verify_autolab_result(
            plan,
            first,
            build_autolab_manifest(first),
            registry=config,
        )
        self.assertTrue(verification.fully_verified)


if __name__ == "__main__":
    unittest.main()
