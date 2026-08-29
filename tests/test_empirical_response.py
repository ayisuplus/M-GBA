"""Tests for the ADR-0038 response table and the empirical L0 variant."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from mgba.empirical_response import (
    TABLE_SCHEMA_VERSION,
    EmpiricalResponseTable,
    build_response_table,
    load_response_table,
    save_response_table,
)
from mgba.layers.l0 import ABSTRACT_GENE_NAMES, DiscreteGrnModel, load_grn_config
from mgba.layers.l0_empirical import (
    EMPIRICAL_L0_MODEL_VERSION,
    EmpiricalResponseGrnModel,
    load_empirical_l0_config,
)
from mgba.models import Genome
from mgba.layers.contracts import PerturbationKind, RegulatoryInput

ROOT = Path(__file__).parents[1]
L0_CONFIG = ROOT / "configs" / "layers" / "l0_reference_grn.json"
_UNIT = "BAK1"
_VECTOR = [1.0, -1.0, 0.0, 0.5, 0.0, 0.0]


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _genome() -> Genome:
    return Genome(
        version="abstract-genome-0.2",
        traits={
            "damage_response": 0.2,
            "signal_expression": 0.8,
            "repair_expression": 0.7,
            "metabolic_expression": 0.8,
            "death_expression": 0.1,
            "negative_feedback_expression": 0.3,
        },
    )


def _table(vectors: dict[str, list[float]] | None = None) -> EmpiricalResponseTable:
    units = vectors or {_UNIT: list(_VECTOR)}
    return EmpiricalResponseTable(
        table_id="l0-response-table-fixture",
        source={"verdict": "passed"},
        vectors=tuple(
            (unit, tuple(vector)) for unit, vector in sorted(units.items())
        ),
        table_digest="d" * 64,
    )


def _model(table: EmpiricalResponseTable | None = None) -> EmpiricalResponseGrnModel:
    return EmpiricalResponseGrnModel(
        load_grn_config(L0_CONFIG),
        response_table=table or _table(),
        table_path="fixture-table.json",
    )


def _natural(cell: str = "cell-a", time: int = 1) -> dict[str, float]:
    reference = DiscreteGrnModel(load_grn_config(L0_CONFIG))
    state = reference.initialize(
        cell_id=cell,
        genome=_genome(),
        regulatory_input=RegulatoryInput(damage_signal=0.0),
        perturbations={},
    ).state
    result = reference.step(
        cell_id=cell,
        genome=_genome(),
        previous_state=state,
        regulatory_input=RegulatoryInput(damage_signal=0.0),
        perturbations={},
        logical_time=time,
    ).state
    return {gene: getattr(result, gene) for gene in ABSTRACT_GENE_NAMES}


class ResponseTableGateTests(unittest.TestCase):
    def _write_pair(self, root: Path, *, verdict: str = "passed") -> tuple[Path, Path]:
        predictions = {
            "schema_version": "mgba-l0-response-predictions-0.1",
            "profile_id": "p-fixture",
            "profile_sha256": "a" * 64,
            "units": [{"unit": _UNIT, "mlp_pred": list(_VECTOR)}],
        }
        pred_path = root / "pred.json"
        pred_path.write_text(json.dumps(predictions), encoding="utf-8")
        evaluation = {
            "schema_version": "mgba-l0-training-evaluation-0.1",
            "evaluation_id": "l0-training-eval-fixture",
            "pass_rule": {"verdict": verdict},
            "source": {
                "predictions_sha256": _sha256(pred_path),
                "profile_sha256": "a" * 64,
            },
        }
        eval_path = root / "eval.json"
        eval_path.write_text(json.dumps(evaluation), encoding="utf-8")
        return pred_path, eval_path

    def test_build_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred, ev = self._write_pair(root)
            table = build_response_table(pred, ev)
            self.assertEqual(TABLE_SCHEMA_VERSION, table["schema_version"])
            self.assertEqual(list(_VECTOR), table["units"][_UNIT])
            out = save_response_table(table, root / "table.json")
            loaded = load_response_table(out, expected_sha256=_sha256(out))
            self.assertEqual(tuple(_VECTOR), loaded.vector(_UNIT))
            self.assertEqual(table["table_id"], loaded.table_id)
            self.assertEqual(
                dict(zip(ABSTRACT_GENE_NAMES, _VECTOR)), loaded.as_node_dict(_UNIT)
            )

    def test_unpassed_verdict_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pred, ev = self._write_pair(Path(tmp), verdict="failed")
            with self.assertRaisesRegex(ValueError, "passed"):
                build_response_table(pred, ev)

    def test_digest_mismatch_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred, ev = self._write_pair(root)
            payload = json.loads(ev.read_text(encoding="utf-8"))
            payload["source"]["predictions_sha256"] = "f" * 64
            ev.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not cover"):
                build_response_table(pred, ev)

    def test_loader_rejects_tampered_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred, ev = self._write_pair(root)
            out = save_response_table(build_response_table(pred, ev), root / "t.json")
            payload = json.loads(out.read_text(encoding="utf-8"))
            payload["units"][_UNIT][0] = 0.25
            out.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "id does not match"):
                load_response_table(out, expected_sha256=_sha256(out))

    def test_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred, ev = self._write_pair(root)
            table = build_response_table(pred, ev)
            save_response_table(table, root / "t.json")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_response_table(table, root / "t.json")


class EmpiricalModelTests(unittest.TestCase):
    def test_empirical_math_and_events(self) -> None:
        # step(previous_state=None) applies one GRN dynamics step over traits;
        # expectations use the reference model's natural values.
        natural = _natural()
        result = _model().step(
            cell_id="cell-a",
            genome=_genome(),
            previous_state=None,
            regulatory_input=RegulatoryInput(damage_signal=0.0),
            perturbations={_UNIT: 1.0},
            logical_time=1,
        )
        state = result.state
        for node, log2fc in zip(ABSTRACT_GENE_NAMES, _VECTOR):
            expected = min(1.0, max(0.0, natural[node] * (2.0 ** log2fc)))
            self.assertAlmostEqual(expected, getattr(state, node), places=15)
        self.assertEqual(6, len(result.perturbation_events))
        kinds = {event.gene: event.kind for event in result.perturbation_events}
        self.assertEqual(PerturbationKind.OVEREXPRESSION, kinds["damage_response"])
        self.assertEqual(PerturbationKind.KNOCKDOWN, kinds["signal_expression"])
        self.assertEqual(PerturbationKind.CLAMP_NO_CHANGE, kinds["repair_expression"])
        self.assertEqual(EMPIRICAL_L0_MODEL_VERSION.split("+")[0], state.metadata.model_version.split("+")[0])

    def test_zero_dose_is_noop(self) -> None:
        result = _model().initialize(
            cell_id="cell-a",
            genome=_genome(),
            regulatory_input=RegulatoryInput(damage_signal=0.0),
            perturbations={_UNIT: 0.0},
        )
        for node in ABSTRACT_GENE_NAMES:
            self.assertAlmostEqual(
                _genome().traits[node], getattr(result.state, node), places=15
            )
        self.assertTrue(
            all(
                event.kind == PerturbationKind.CLAMP_NO_CHANGE
                for event in result.perturbation_events
            )
        )

    def test_abstract_fallback_matches_reference_bit_for_bit(self) -> None:
        reference = DiscreteGrnModel(load_grn_config(L0_CONFIG))
        perturbations = {"damage_response": 1.0}
        ref = reference.initialize(
            cell_id="cell-a",
            genome=_genome(),
            regulatory_input=RegulatoryInput(damage_signal=0.0),
            perturbations=perturbations,
        )
        emp = _model().initialize(
            cell_id="cell-a",
            genome=_genome(),
            regulatory_input=RegulatoryInput(damage_signal=0.0),
            perturbations=perturbations,
        )
        for node in ABSTRACT_GENE_NAMES:
            self.assertEqual(
                getattr(ref.state, node), getattr(emp.state, node)
            )
        self.assertEqual(
            [e.gene for e in ref.perturbation_events],
            [e.gene for e in emp.perturbation_events],
        )

    def test_unknown_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown genes/units"):
            _model().initialize(
                cell_id="cell-a",
                genome=_genome(),
                regulatory_input=RegulatoryInput(damage_signal=0.0),
                perturbations={"NOT_A_GENE": 1.0},
            )

    def test_step_path_matches_reference_natural_plus_rule(self) -> None:
        reference = DiscreteGrnModel(load_grn_config(L0_CONFIG))
        first = reference.initialize(
            cell_id="cell-a",
            genome=_genome(),
            regulatory_input=RegulatoryInput(damage_signal=0.0),
            perturbations={},
        ).state
        natural = _natural()
        result = _model().step(
            cell_id="cell-a",
            genome=_genome(),
            previous_state=first,
            regulatory_input=RegulatoryInput(damage_signal=0.0),
            perturbations={_UNIT: 1.0},
            logical_time=1,
        )
        for node, log2fc in zip(ABSTRACT_GENE_NAMES, _VECTOR):
            expected = min(1.0, max(0.0, natural[node] * (2.0 ** log2fc)))
            self.assertAlmostEqual(expected, getattr(result.state, node), places=15)

    def test_config_loader_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "good.json"
            good.write_text(
                json.dumps(
                    {
                        "model_version": EMPIRICAL_L0_MODEL_VERSION,
                        "response_table_path": "x.json",
                        "response_table_sha256": "e" * 64,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual("x.json", load_empirical_l0_config(good)["response_table_path"])
            bad = root / "bad.json"
            bad.write_text(json.dumps({"model_version": "other"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "keys must be"):
                load_empirical_l0_config(bad)


if __name__ == "__main__":
    unittest.main()
