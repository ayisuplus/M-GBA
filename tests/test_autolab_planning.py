"""Tests for the non-executing Autolab Planner--Router--Verifier boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from mgba.autolab import (
    AutolabConfig,
    AutolabSession,
    EvaluatorResult,
    Hypothesis,
    build_autolab_manifest,
)
from mgba.autolab_planning import (
    PAIRED_SWAP_TOOL,
    AutolabPlan,
    PlanStep,
    compile_autolab_plan,
    load_autolab_plan,
    save_autolab_plan,
    save_verification_report,
    verify_autolab_plan,
    verify_autolab_result,
)
from mgba.hashing import digest_payload
from mgba.cli import main as cli_main


_METRICS = (
    "damage_burden",
    "homeostasis",
    "inflammation",
    "recovery_capacity",
    "vitality",
)


def _hypothesis(identifier: str, layer: str) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=identifier,
        kind="layer_static_swap",
        layer=layer,
        priority=1.0,
    )


def _config(**overrides) -> AutolabConfig:
    values = {
        "model_version": "autolab-planning-test-0.1",
        "seeds": (7, 42),
        "probe_ticks": 10,
        "confirm_ticks": 20,
        "confirm_top_k": 1,
        "budget": 4,
        "hypotheses": (
            _hypothesis("l1-static", "L1"),
            _hypothesis("l2-static", "L2"),
            _hypothesis("l3-static", "L3"),
        ),
    }
    values.update(overrides)
    return AutolabConfig(**values)


def _evaluator(call_log: list[tuple[str, int, tuple[int, ...]]]):
    effects = {"l1-static": 0.1, "l2-static": 0.5, "l3-static": 0.2}

    def evaluate(hypothesis, ticks, seeds) -> EvaluatorResult:
        call_log.append((hypothesis.hypothesis_id, ticks, seeds))
        value = effects[hypothesis.hypothesis_id]
        return EvaluatorResult(
            per_seed_metric_effects=tuple(
                (seed, tuple((metric, value) for metric in _METRICS))
                for seed in seeds
            ),
            history_digests=tuple(
                (
                    seed,
                    digest_payload(
                        {
                            "hypothesis": hypothesis.hypothesis_id,
                            "ticks": ticks,
                            "seed": seed,
                        }
                    ),
                )
                for seed in seeds
            ),
        )

    return evaluate


def _manifest(result) -> dict:
    return {
        "schema_version": "mgba-autolab-artifact-0.1",
        "session_id": result.session_id,
        "model_version": result.config.model_version,
        "registry_digest": digest_payload(
            [item.hypothesis_id for item in result.config.hypotheses]
        ),
        "evaluations": [
            {
                "hypothesis_id": item.hypothesis_id,
                "phase": item.phase,
                "ticks": item.ticks,
                "seeds": list(item.seeds),
                "history_digests": [
                    {"seed": seed, "history_digest": history_digest}
                    for seed, history_digest in item.history_digests
                ],
            }
            for item in result.evaluations
        ],
    }


class AutolabPlanCompilationTests(unittest.TestCase):
    def test_compilation_is_deterministic_and_budgeted(self) -> None:
        config = _config()
        first = compile_autolab_plan(config)
        second = compile_autolab_plan(config)
        self.assertEqual(first, second)
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertFalse(first.executed)
        self.assertEqual("reference_model", first.claim_level)
        self.assertEqual(
            [
                ("probe", "l1-static"),
                ("probe", "l2-static"),
                ("probe", "l3-static"),
                ("select", None),
                ("confirm", None),
                ("verify", None),
            ],
            [(step.phase, step.hypothesis_id) for step in first.steps],
        )
        evaluator_calls = [
            step for step in first.steps if step.tool == PAIRED_SWAP_TOOL
        ]
        self.assertEqual(config.budget, len(evaluator_calls))
        self.assertTrue(verify_autolab_plan(first, config).valid)

    def test_compilation_respects_partial_screening_budget(self) -> None:
        config = _config(budget=2)
        plan = compile_autolab_plan(config)
        self.assertEqual(("l3-static",), plan.pending_hypotheses)
        self.assertEqual(2, len([step for step in plan.steps if step.phase == "probe"]))
        self.assertEqual(0, len([step for step in plan.steps if step.phase == "confirm"]))
        self.assertTrue(verify_autolab_plan(plan, config).valid)

    def test_closed_schema_rejects_unknown_root_and_step_fields(self) -> None:
        config = _config()
        raw = compile_autolab_plan(config).as_dict()
        raw["surprise"] = True
        report = verify_autolab_plan(raw, config)
        self.assertFalse(report.valid)
        self.assertEqual("failed", report.schema_status)

        raw = compile_autolab_plan(config).as_dict()
        raw["steps"][0]["surprise"] = True
        # Preserve plan_id to prove unknown fields fail before digest acceptance.
        report = verify_autolab_plan(raw, config)
        self.assertFalse(report.valid)
        self.assertEqual("failed", report.schema_status)

    def test_missing_dependency_and_cycle_fail_closed(self) -> None:
        config = _config()
        plan = compile_autolab_plan(config)
        missing = replace(
            plan,
            steps=(
                replace(plan.steps[0], depends_on=("not-a-step",)),
                *plan.steps[1:],
            ),
        )
        report = verify_autolab_plan(missing, config)
        self.assertFalse(report.valid)
        self.assertIn("missing_dependency", [item.code for item in report.issues])

        first, second = plan.steps[:2]
        cyclic = replace(
            plan,
            steps=(
                replace(first, depends_on=(second.step_id,)),
                replace(second, depends_on=(first.step_id,)),
                *plan.steps[2:],
            ),
        )
        report = verify_autolab_plan(cyclic, config)
        self.assertFalse(report.valid)
        self.assertIn("cyclic_dag", [item.code for item in report.issues])

    def test_unknown_tool_unregistered_hypothesis_and_layer_scope_fail(self) -> None:
        config = _config()
        plan = compile_autolab_plan(config)
        cases = (
            replace(plan.steps[0], tool="online_llm_exec"),
            replace(plan.steps[0], hypothesis_id="not-registered"),
            replace(plan.steps[0], layer="L3"),
        )
        expected_codes = ("unknown_tool", "unregistered_hypothesis", "layer_scope_violation")
        for step, expected_code in zip(cases, expected_codes):
            candidate = replace(plan, steps=(step, *plan.steps[1:]))
            report = verify_autolab_plan(candidate, config)
            self.assertFalse(report.valid)
            self.assertIn(expected_code, [item.code for item in report.issues])

    def test_paired_baseline_and_seed_requirements_fail_closed(self) -> None:
        config = _config()
        plan = compile_autolab_plan(config)
        for step, expected_code in (
            (replace(plan.steps[0], paired_baseline=False), "paired_baseline_missing"),
            (replace(plan.steps[0], seeds=(7,)), "paired_seeds_missing"),
        ):
            report = verify_autolab_plan(
                replace(plan, steps=(step, *plan.steps[1:])), config
            )
            self.assertFalse(report.valid)
            self.assertIn(expected_code, [item.code for item in report.issues])

    def test_extra_evaluator_step_exceeds_budget(self) -> None:
        config = _config()
        plan = compile_autolab_plan(config)
        extra = PlanStep(
            step_id="extra-probe",
            phase="probe",
            tool=PAIRED_SWAP_TOOL,
            hypothesis_id="l1-static",
            selected_rank=None,
            layer="L1",
            ticks=config.probe_ticks,
            seeds=config.seeds,
            paired_baseline=True,
            depends_on=(plan.steps[-1].step_id,),
        )
        report = verify_autolab_plan(replace(plan, steps=(*plan.steps, extra)), config)
        self.assertFalse(report.valid)
        self.assertIn("budget_exceeded", [item.code for item in report.issues])

    def test_plan_round_trip_and_write_once_are_stable(self) -> None:
        plan = compile_autolab_plan(_config())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            save_autolab_plan(path, plan)
            first = path.read_bytes()
            save_autolab_plan(path, plan)
            self.assertEqual(first, path.read_bytes())
            self.assertEqual(plan, load_autolab_plan(path))
            changed = compile_autolab_plan(_config(confirm_ticks=21))
            with self.assertRaises(ValueError):
                save_autolab_plan(path, changed)


class AutolabPostResultVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _config()
        self.plan = compile_autolab_plan(self.config)
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.result = AutolabSession(
            self.config, evaluate=_evaluator(self.calls)
        ).run()
        self.manifest = _manifest(self.result)

    def test_public_manifest_builder_matches_frozen_artifact_contract(self) -> None:
        self.assertEqual(self.manifest, build_autolab_manifest(self.result))

    def test_valid_result_reproduces_order_l2_leader_and_histories(self) -> None:
        calls_before_verification = tuple(self.calls)
        report = verify_autolab_result(
            self.plan,
            self.result,
            self.manifest,
            registry=self.config,
            claims=("L2 has the largest paired reference-model endpoint effect.",),
        )
        self.assertTrue(report.valid)
        self.assertTrue(report.fully_verified)
        self.assertFalse(report.executed)
        self.assertEqual(calls_before_verification, tuple(self.calls))
        self.assertEqual("l2-static", self.result.leader)
        self.assertEqual(
            [
                ("probe", "l1-static"),
                ("probe", "l2-static"),
                ("probe", "l3-static"),
                ("confirm", "l2-static"),
            ],
            [(item.phase, item.hypothesis_id) for item in self.result.evaluations],
        )
        expected_histories = [
            item["history_digests"] for item in self.manifest["evaluations"]
        ]
        actual_histories = [
            [
                {"seed": seed, "history_digest": history_digest}
                for seed, history_digest in item.history_digests
            ]
            for item in self.result.evaluations
        ]
        self.assertEqual(expected_histories, actual_histories)

    def test_tampered_history_or_manifest_fails(self) -> None:
        summary = deepcopy(self.result.summary_dict())
        summary["evaluations"][0]["history_digests"][0]["history_digest"] = "f" * 64
        report = verify_autolab_result(
            self.plan, summary, self.manifest, registry=self.config
        )
        self.assertFalse(report.fully_verified)
        self.assertIn(
            "manifest_history_mismatch", [item.code for item in report.issues]
        )

        manifest = deepcopy(self.manifest)
        manifest["session_id"] = "autolab-tampered"
        report = verify_autolab_result(
            self.plan, self.result, manifest, registry=self.config
        )
        self.assertFalse(report.fully_verified)
        self.assertIn(
            "manifest_history_mismatch", [item.code for item in report.issues]
        )

    def test_claim_level_and_prohibited_claims_fail_closed(self) -> None:
        report = verify_autolab_result(
            self.plan,
            self.result,
            self.manifest,
            registry=self.config,
            claim_level="validated_result",
        )
        self.assertFalse(report.fully_verified)
        self.assertIn("claim_level_violation", [item.code for item in report.issues])

        report = verify_autolab_result(
            self.plan,
            self.result,
            self.manifest,
            registry=self.config,
            claims=("This system creates digital life with clinical value.",),
        )
        self.assertFalse(report.fully_verified)
        self.assertIn("prohibited_claim", [item.code for item in report.issues])

    def test_wrong_adaptive_confirmation_and_leader_fail(self) -> None:
        summary = deepcopy(self.result.summary_dict())
        summary["evaluations"][-1]["hypothesis_id"] = "l1-static"
        summary["decision_log"][-1]["hypothesis_id"] = "l1-static"
        summary["confirmed"] = ["l1-static"]
        summary["leader"] = "l1-static"
        report = verify_autolab_result(
            self.plan, summary, self.manifest, registry=self.config
        )
        self.assertFalse(report.fully_verified)
        self.assertIn(
            "evaluation_order_mismatch", [item.code for item in report.issues]
        )

    def test_malformed_result_is_reported_without_execution_or_exception(self) -> None:
        calls_before_verification = tuple(self.calls)
        report = verify_autolab_result(
            self.plan,
            {"schema_version": object()},
            {"not": object()},
            registry=self.config,
            claims=None,  # type: ignore[arg-type]
        )
        self.assertFalse(report.fully_verified)
        self.assertEqual("failed", report.result_status)
        self.assertEqual(calls_before_verification, tuple(self.calls))
        self.assertIn("invalid_result_schema", [item.code for item in report.issues])

    def test_report_is_deterministic_and_write_once(self) -> None:
        first = verify_autolab_result(
            self.plan, self.result, self.manifest, registry=self.config
        )
        second = verify_autolab_result(
            self.plan, self.result, self.manifest, registry=self.config
        )
        self.assertEqual(first, second)
        self.assertEqual(first.report_id, second.report_id)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verification.json"
            save_verification_report(path, first)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(payload["executed"])
            self.assertTrue(payload["fully_verified"])
            self.assertEqual(first.report_id, payload["report_id"])

    def test_planning_module_has_no_runner_import(self) -> None:
        module_path = Path(__file__).parents[1] / "src" / "mgba" / "autolab_planning.py"
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("from .runner", source)
        self.assertNotIn("import mgba.runner", source)


class AutolabPlanCliTests(unittest.TestCase):
    def test_cli_compiles_and_validates_without_constructing_a_session(self) -> None:
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            command = [
                "mgba",
                "autolab-plan",
                "--autolab-config",
                str(root / "configs" / "experiments" / "autolab_screen.json"),
                "--artifact-root",
                directory,
            ]
            with (
                patch("sys.argv", command),
                patch("mgba.cli.AutolabSession") as session_type,
                redirect_stdout(stdout),
            ):
                cli_main()
            session_type.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["executed"])
            self.assertFalse(payload["plan"]["executed"])
            self.assertEqual("accepted", payload["verification"]["verdict"])
            self.assertEqual("not_requested", payload["verification"]["layers"][2]["status"])
            self.assertTrue(Path(payload["plan_artifact"]).is_file())
            self.assertTrue(Path(payload["verification_artifact"]).is_file())


if __name__ == "__main__":
    unittest.main()
