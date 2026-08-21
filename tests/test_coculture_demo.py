"""Two-population co-culture scenario tests (ADR-0021).

Proves that cell-type identity lives only in L0 Genome templates and that
cross-type influence travels through L3 edges, never through type labels:
removing the four cross-group edges must change the repair population's
L3 signal trajectory. Zero contract changes are required for a second
cell type.
"""

import unittest
from dataclasses import replace
from pathlib import Path
from statistics import fmean

from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, load_cell_config
from mgba.layers.l3 import TissueEnvironmentModel, load_tissue_config
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import load_multiscale_scenario
from mgba.runner import MultirateCrossScaleRunner, load_runner_config

ROOT = Path(__file__).parents[1]
LAYER_CONFIGS = ROOT / "configs" / "layers"
TICKS = 60
CROSS_GROUP_EDGES = (
    ("sig-1", "rep-1"),
    ("rep-1", "sig-2"),
    ("sig-3", "rep-2"),
    ("rep-2", "sig-4"),
)


def _layer_models() -> dict:
    return {
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


def _mean(values) -> float:
    return fmean(tuple(values))


class CocultureDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_multiscale_scenario(
            ROOT / "configs" / "multiscale_coculture_demo.json"
        )
        self.runner_config = load_runner_config(
            ROOT / "configs" / "runner_reference.json"
        )

    def _run(self, scenario=None):
        runner = MultirateCrossScaleRunner(self.runner_config, **_layer_models())
        return runner.run(scenario or self.scenario, ticks=TICKS)

    def test_determinism(self) -> None:
        first = self._run()
        second = self._run()
        self.assertEqual(first.history_digest, second.history_digest)

    def test_type_difference_emerges_through_layer_chain(self) -> None:
        run = self._run()
        # L0->L1 leg: the signal_expression trait gap keeps L1 signal_protein
        # ordered sig > rep for the whole trajectory (dead cells included).
        final_l1 = run.ticks[-1].l1
        sig_protein = _mean(
            state.signal_protein
            for state in final_l1
            if state.cell_id.startswith("sig-")
        )
        rep_protein = _mean(
            state.signal_protein
            for state in final_l1
            if state.cell_id.startswith("rep-")
        )
        self.assertGreater(sig_protein, rep_protein)
        # L1->L2 leg: signal_protein feeds L2 activation_drive. Under the
        # demo stress load both populations reach the DEAD absorbing state by
        # tick 4 (negative baseline, cf. the 100-tick FAILED reference
        # trajectory), so the L2 difference is asserted in the live window.
        first_l2 = run.ticks[0].l2
        sig_activation = _mean(
            state.activation
            for state in first_l2
            if state.cell_id.startswith("sig-")
        )
        rep_activation = _mean(
            state.activation
            for state in first_l2
            if state.cell_id.startswith("rep-")
        )
        self.assertGreater(sig_activation, rep_activation)

    def test_cross_type_influence_is_edge_mediated(self) -> None:
        cross = set(CROSS_GROUP_EDGES)
        pruned = replace(
            self.scenario,
            edges=tuple(edge for edge in self.scenario.edges if edge not in cross),
        )
        self.assertEqual(
            len(self.scenario.edges) - len(CROSS_GROUP_EDGES), len(pruned.edges)
        )
        full_run = self._run()
        pruned_run = self._run(pruned)
        self.assertNotEqual(full_run.history_digest, pruned_run.history_digest)
        rep_signal_differs = any(
            _mean(
                node.signal
                for node in full_tick.l3.nodes
                if node.cell_id.startswith("rep-")
            )
            != _mean(
                node.signal
                for node in pruned_tick.l3.nodes
                if node.cell_id.startswith("rep-")
            )
            for full_tick, pruned_tick in zip(full_run.ticks, pruned_run.ticks)
        )
        self.assertTrue(rep_signal_differs)


if __name__ == "__main__":
    unittest.main()
