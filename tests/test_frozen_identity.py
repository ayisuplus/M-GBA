"""Frozen 0.2.0 identity regression gate.

Guards the byte-level reference identities against accidental drift from
any new code path (feedback loop included):

* single-tick contract run experiment id and trace digest;
* 100-tick multirate reference run experiment id, history digest, and the
  ``FAILED`` negative-baseline outcome;
* the frozen WP8 21-run causal matrix id.

If any of these constants must move, it is a deliberate protocol change and
requires a new ADR plus synchronized documentation updates — never a
silent parameter tweak.
"""

import unittest
from pathlib import Path

from mgba.experiments import CausalExperimentRunner, load_causal_config
from mgba.layers.l0 import DiscreteGrnModel, load_grn_config
from mgba.layers.l1 import CoarseMolecularModel, load_molecular_config
from mgba.layers.l2 import CellStateMachineModel, StaticCellModel, load_cell_config
from mgba.layers.l3 import (
    StaticTissueModel,
    TissueEnvironmentModel,
    load_tissue_config,
)
from mgba.layers.l1 import StaticMolecularModel
from mgba.layers.l4 import PhenotypeObserverModel, load_phenotype_config
from mgba.multiscale import (
    ReferenceCrossScaleRunner,
    load_multiscale_scenario,
    summarize_trace,
)
from mgba.runner import MultirateCrossScaleRunner, load_runner_config


class FrozenIdentityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        self.layer_configs = self.root / "configs" / "layers"

    def _layer_models(self) -> dict:
        return {
            "genome_model": DiscreteGrnModel(
                load_grn_config(self.layer_configs / "l0_reference_grn.json")
            ),
            "molecular_model": CoarseMolecularModel(
                load_molecular_config(
                    self.layer_configs / "l1_reference_molecular.json"
                )
            ),
            "cell_model": CellStateMachineModel(
                load_cell_config(self.layer_configs / "l2_reference_cell.json")
            ),
            "tissue_model": TissueEnvironmentModel(
                load_tissue_config(
                    self.layer_configs / "l3_reference_tissue.json"
                )
            ),
            "phenotype_model": PhenotypeObserverModel(
                load_phenotype_config(
                    self.layer_configs / "l4_reference_phenotype.json"
                )
            ),
        }

    def test_single_tick_contract_identity_frozen(self) -> None:
        scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        runner = ReferenceCrossScaleRunner(**self._layer_models())
        result = summarize_trace(scenario, runner.run(scenario))
        self.assertEqual("mgba-2c1963fa31d6a55c", result["experiment"]["experiment_id"])
        self.assertEqual(
            "20f9578497fd67d04071cd4cd08627262ff883a620d5c7c02ea7dff4014a0135",
            result["trace_digest"],
        )

    def test_100_tick_reference_identity_frozen(self) -> None:
        scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        runner = MultirateCrossScaleRunner(
            load_runner_config(self.root / "configs" / "runner_reference.json"),
            **self._layer_models(),
        )
        run = runner.run(scenario, ticks=100)
        self.assertEqual("mgba-e6a6d65dba732341", run.manifest.experiment_id)
        self.assertEqual(
            "7bd4d10044c420f5d4f18cb706765c673a6ca1930cccb1ddea5322abb1f336ff",
            run.history_digest,
        )
        self.assertEqual("failed", run.phenotype_window.outcome.value)

    def test_wp8_matrix_identity_frozen(self) -> None:
        scenario = load_multiscale_scenario(
            self.root / "configs" / "multiscale_demo.json"
        )
        matrix_config = load_causal_config(
            self.root / "configs" / "experiments" / "wp8_reference.json"
        )
        runner_config = load_runner_config(
            self.root / "configs" / "runner_reference.json"
        )
        base_models = self._layer_models()
        runners = {"baseline": MultirateCrossScaleRunner(runner_config, **base_models)}
        for ablation in matrix_config.ablations:
            models = dict(base_models)
            if ablation == "l1_static":
                models["molecular_model"] = StaticMolecularModel()
            elif ablation == "l2_static":
                models["cell_model"] = StaticCellModel()
            elif ablation == "l3_static":
                models["tissue_model"] = StaticTissueModel()
            runners[ablation] = MultirateCrossScaleRunner(runner_config, **models)
        matrix = CausalExperimentRunner(matrix_config, runners=runners).run(scenario)
        self.assertEqual("matrix-7da4137aa39d5122", matrix.matrix_id)


if __name__ == "__main__":
    unittest.main()
