import json
import tempfile
import unittest
from pathlib import Path

from mgba.experiment import (
    ExperimentManifest,
    LayerTransitionEvent,
    append_transition_event,
    initialize_experiment_artifacts,
)
from mgba.layers import LayerId


class ExperimentProtocolTests(unittest.TestCase):
    def _manifest(self, seed: int = 42) -> ExperimentManifest:
        return ExperimentManifest.create(
            experiment_name="contract-test",
            seed=seed,
            code_version="0.1.0",
            config={"environment_stress": 0.35},
            model_versions={"L0": "l0-0.1", "L1": "l1-0.1"},
        )

    def test_same_inputs_produce_same_experiment_id(self) -> None:
        first = self._manifest()
        second = self._manifest()
        self.assertEqual(first.experiment_id, second.experiment_id)
        self.assertNotEqual(first.experiment_id, self._manifest(seed=43).experiment_id)

    def test_raw_artifacts_are_plain_json_and_append_only_events(self) -> None:
        manifest = self._manifest()
        event = LayerTransitionEvent(
            logical_time=0,
            source_layer=LayerId.L0,
            target_layer=LayerId.L1,
            model_version="l1-0.1",
            input_digest="input",
            output_digest="output",
            timescale="contract-step",
            reason="test transition",
        )

        with tempfile.TemporaryDirectory() as directory:
            paths = initialize_experiment_artifacts(Path(directory), manifest)
            append_transition_event(paths, event)
            append_transition_event(paths, event)

            saved_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
            lines = paths.events.read_text(encoding="utf-8").splitlines()

            self.assertEqual(manifest.experiment_id, saved_manifest["experiment_id"])
            self.assertEqual(2, len(lines))
            self.assertEqual(event.event_id, json.loads(lines[0])["event_id"])
            self.assertTrue(paths.states.is_dir())
            self.assertTrue(paths.derived.is_dir())


if __name__ == "__main__":
    unittest.main()
