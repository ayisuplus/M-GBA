import json
import tempfile
import unittest
from pathlib import Path

from mgba.experiment import (
    ExperimentManifest,
    LayerTransitionEvent,
    append_transition_event,
    initialize_experiment_artifacts,
    package_source_digest,
    source_tree_digest,
)
from mgba.layers import LayerId


class ExperimentProtocolTests(unittest.TestCase):
    def _manifest(
        self, seed: int = 42, source_digest: str = "a" * 64
    ) -> ExperimentManifest:
        return ExperimentManifest.create(
            experiment_name="contract-test",
            seed=seed,
            code_version="0.1.0",
            config={"environment_stress": 0.35},
            model_versions={"L0": "l0-0.1", "L1": "l1-0.1"},
            source_digest=source_digest,
        )

    def test_same_inputs_produce_same_experiment_id(self) -> None:
        first = self._manifest()
        second = self._manifest()
        self.assertEqual(first.experiment_id, second.experiment_id)
        self.assertNotEqual(first.experiment_id, self._manifest(seed=43).experiment_id)
        self.assertNotEqual(
            first.experiment_id,
            self._manifest(source_digest="b" * 64).experiment_id,
        )
        self.assertEqual("mgba-manifest-0.2", first.schema_version)
        self.assertEqual("a" * 64, first.as_dict()["source_digest"])
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._manifest(source_digest="not-a-digest")

        automatic = ExperimentManifest.create(
            experiment_name="automatic-source-test",
            seed=1,
            code_version="0.1.0",
            config={},
            model_versions={"L0": "l0-0.1"},
        )
        self.assertEqual(package_source_digest(), automatic.source_digest)

    def test_legacy_manifest_keeps_its_original_identity(self) -> None:
        legacy = ExperimentManifest(
            schema_version="mgba-manifest-0.1",
            experiment_name="contract-test",
            seed=42,
            code_version="0.1.0",
            config_digest="8ab517c1d29fdb0ae9d6dd660f114ee1e90d8f47c5e153ac6532827334f3916f",
            model_versions=(("L0", "l0-0.1"), ("L1", "l1-0.1")),
        )
        self.assertEqual("mgba-268bbd79fdd87391", legacy.experiment_id)
        self.assertNotIn("source_digest", legacy.as_dict())

    def test_source_tree_digest_tracks_python_content_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            first = source_tree_digest(root)
            (root / "notes.txt").write_text("ignored\n", encoding="utf-8")
            self.assertEqual(first, source_tree_digest(root))
            (root / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(first, source_tree_digest(root))

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
