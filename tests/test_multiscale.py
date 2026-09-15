import unittest
from pathlib import Path

from mgba.layers import CellPhase
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import (
    ReferenceCrossScaleRunner,
    load_multiscale_scenario,
    summarize_trace,
)


class MultiscaleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        config = Path(__file__).parents[1] / "configs" / "multiscale_demo.json"
        l0_config = (
            Path(__file__).parents[1]
            / "configs"
            / "layers"
            / "l0_reference_grn.json"
        )
        l1_config = (
            Path(__file__).parents[1]
            / "configs"
            / "layers"
            / "l1_reference_molecular.json"
        )
        l2_config = (
            Path(__file__).parents[1]
            / "configs"
            / "layers"
            / "l2_reference_cell.json"
        )
        l3_config = (
            Path(__file__).parents[1]
            / "configs"
            / "layers"
            / "l3_reference_tissue.json"
        )
        l4_config = (
            Path(__file__).parents[1]
            / "configs"
            / "layers"
            / "l4_reference_phenotype.json"
        )
        self.scenario = load_multiscale_scenario(config)
        self.runner = ReferenceCrossScaleRunner(
            genome_model=DiscreteGrnModel(load_grn_config(l0_config)),
            molecular_model=CoarseMolecularModel(
                load_molecular_config(l1_config)
            ),
            cell_model=CellStateMachineModel(load_cell_config(l2_config)),
            tissue_model=TissueEnvironmentModel(load_tissue_config(l3_config)),
            phenotype_model=PhenotypeObserverModel(
                load_phenotype_config(l4_config)
            ),
        )

    def test_trace_contains_every_layer_in_order(self) -> None:
        trace = self.runner.run(self.scenario)
        self.assertEqual(4, len(trace.l0))
        self.assertEqual(4, len(trace.l1_inputs))
        self.assertEqual(4, len(trace.l1))
        self.assertEqual(4, len(trace.l2_environments))
        self.assertEqual(4, len(trace.l2))
        self.assertEqual(4, len(trace.l2_actions))
        self.assertEqual(4, trace.l3.cell_count)
        self.assertGreater(trace.l4.vitality, 0.0)

    def test_summary_manifest_and_digest_are_deterministic(self) -> None:
        first = summarize_trace(self.scenario, self.runner.run(self.scenario))
        second = summarize_trace(self.scenario, self.runner.run(self.scenario))
        self.assertEqual(first["experiment"], second["experiment"])
        self.assertEqual(first["trace_digest"], second["trace_digest"])
        self.assertEqual(
            "mgba-2cf0461e4813712f", first["experiment"]["experiment_id"]
        )
        self.assertEqual(
            "20f9578497fd67d04071cd4cd08627262ff883a620d5c7c02ea7dff4014a0135",
            first["trace_digest"],
        )

        perturbations = {"cell-a": {"repair_expression": 0.0}}
        perturbed = summarize_trace(
            self.scenario,
            self.runner.run(self.scenario, perturbations=perturbations),
            perturbations=perturbations,
        )
        self.assertNotEqual(
            first["experiment"]["experiment_id"],
            perturbed["experiment"]["experiment_id"],
        )

    def test_l0_repair_knockdown_propagates_to_l4(self) -> None:
        baseline = self.runner.run(self.scenario)
        perturbed = self.runner.run(
            self.scenario,
            perturbations={"cell-a": {"repair_expression": 0.0}},
        )
        self.assertEqual(1, len(perturbed.l0_perturbation_events))
        self.assertEqual(
            "repair_expression", perturbed.l0_perturbation_events[0].gene
        )
        self.assertLess(perturbed.l1[0].repair_protein, baseline.l1[0].repair_protein)
        self.assertEqual(CellPhase.ACTIVATED, baseline.l2[0].phase)
        self.assertEqual(CellPhase.DEAD, perturbed.l2[0].phase)
        self.assertLess(perturbed.l2[0].viability, baseline.l2[0].viability)
        self.assertLess(perturbed.l3.mean_viability, baseline.l3.mean_viability)
        self.assertGreater(perturbed.l3.nodes[0].stress, baseline.l3.nodes[0].stress)
        self.assertGreater(
            perturbed.l4.damage_burden, baseline.l4.damage_burden
        )
        self.assertGreater(
            perturbed.l4.inflammation, baseline.l4.inflammation
        )
        self.assertLess(perturbed.l4.vitality, baseline.l4.vitality)
        self.assertLess(perturbed.l4.homeostasis, baseline.l4.homeostasis)
        self.assertLess(
            perturbed.l4.recovery_capacity, baseline.l4.recovery_capacity
        )


if __name__ == "__main__":
    unittest.main()
