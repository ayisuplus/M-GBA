"""Contracts and reproducibility gates for the read-only clock observer."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from mgba.carm_spatial_experiments import build_carm_spatial_runners
from mgba.clock_sector import (
    ABSTRACT_L0_NODES,
    CLOCK_SECTOR_OBSERVER_VERSION,
    CLOCK_SECTOR_SCHEMA,
    ClockSectorObserver,
    save_clock_sector_artifact,
)
from mgba.layers import (
    SpatialCoordinate,
    SpatialFieldCell,
    SpatialTissueState,
    StateMetadata,
    TissueNodeState,
    TranscriptState,
)
from mgba.runner import load_checkpoint, load_runner_config, save_checkpoint
from mgba.scenarios.carm import (
    compile_carm_scenario,
    load_carm_scenario_config,
    load_carm_spatial_config,
)


ROOT = Path(__file__).parents[1]


def _metadata(
    logical_time: int, source_digest: str, *, model_version: str
) -> StateMetadata:
    return StateMetadata(
        logical_time=logical_time,
        model_version=model_version,
        source_digest=source_digest,
    )


def _spatial_state(
    coordinates: dict[str, tuple[float, float]],
    *,
    logical_time: int = 5,
    source_digest: str = "fixture-spatial-source",
) -> SpatialTissueState:
    cell_ids = tuple(sorted(coordinates))
    nodes = tuple(
        TissueNodeState(
            cell_id=cell_id,
            stress=0.2,
            resource_level=0.8,
            signal=0.3,
        )
        for cell_id in cell_ids
    )
    return SpatialTissueState(
        metadata=_metadata(
            logical_time,
            source_digest,
            model_version="fixture-spatial-l3-0.1",
        ),
        cell_count=len(cell_ids),
        nodes=nodes,
        edges=(),
        edge_density=0.0,
        mean_activation=0.3,
        mean_viability=0.8,
        mean_resource=0.8,
        mean_signal=0.3,
        dead_fraction=0.0,
        repair_activity=0.2,
        coordinated_signal=0.3,
        tissue_damage=0.2,
        coordinates=tuple(
            SpatialCoordinate(
                cell_id=cell_id,
                x=coordinates[cell_id][0],
                y=coordinates[cell_id][1],
            )
            for cell_id in cell_ids
        ),
        field_rows=1,
        field_columns=1,
        field_cells=(
            SpatialFieldCell(
                row=0,
                column=0,
                stress=0.2,
                resource_level=0.8,
                signal=0.3,
            ),
        ),
    )


def _transcripts(
    cell_ids: tuple[str, ...], *, logical_time: int = 1
) -> tuple[TranscriptState, ...]:
    return tuple(
        TranscriptState(
            metadata=_metadata(
                logical_time,
                f"l0-source-{cell_id}",
                model_version="fixture-abstract-grn-0.1",
            ),
            cell_id=cell_id,
            damage_response=0.11 + index * 0.01,
            signal_expression=0.22 + index * 0.01,
            repair_expression=0.33 + index * 0.01,
            metabolic_expression=0.44 + index * 0.01,
            death_expression=0.55 + index * 0.01,
            negative_feedback_expression=0.66 + index * 0.01,
        )
        for index, cell_id in enumerate(cell_ids)
    )


def _cell(observation, cell_id):
    return next(item for item in observation.cells if item.cell_id == cell_id)


def _assignment(observation, focal_id: str, neighbor_id: str):
    focal = _cell(observation, focal_id)
    for slot in focal.bins:
        for neighbor in slot.neighbors:
            if neighbor.cell_id == neighbor_id:
                return (
                    slot.direction_index,
                    slot.ring_index,
                    neighbor.normalized_distance,
                )
    raise AssertionError(f"missing {neighbor_id} around {focal_id}")


class ClockSectorGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observer = ClockSectorObserver()

    def test_input_order_is_invariant_and_l0_nodes_are_sorted(self) -> None:
        coordinates = {
            "a": (0.20, 0.20),
            "b": (0.30, 0.20),
            "c": (0.20, 0.40),
        }
        state = _spatial_state(coordinates)
        transcripts = _transcripts(tuple(sorted(coordinates)))
        forward = self.observer.observe(state, transcripts)
        reversed_input = self.observer.observe(state, tuple(reversed(transcripts)))
        self.assertEqual(forward.as_dict(), reversed_input.as_dict())
        neighbor = next(
            item
            for slot in _cell(forward, "a").bins
            for item in slot.neighbors
            if item.cell_id == "b"
        )
        self.assertEqual(
            ABSTRACT_L0_NODES,
            tuple(name for name, _ in neighbor.abstract_l0_nodes),
        )
        self.assertEqual(CLOCK_SECTOR_OBSERVER_VERSION, self.observer.model_version)

    def test_uniform_coordinate_scale_preserves_normalized_encoding(self) -> None:
        coordinates = {
            "a": (0.10, 0.10),
            "b": (0.20, 0.10),
            "c": (0.10, 0.30),
            "d": (0.30, 0.30),
        }
        scaled = {
            cell_id: (2.0 * x, 2.0 * y)
            for cell_id, (x, y) in coordinates.items()
        }
        transcripts = _transcripts(tuple(sorted(coordinates)))
        first = self.observer.observe(_spatial_state(coordinates), transcripts)
        second = self.observer.observe(
            _spatial_state(scaled, source_digest="scaled-spatial-source"),
            transcripts,
        )
        self.assertAlmostEqual(
            2.0 * first.normalization_distance,
            second.normalization_distance,
            places=12,
        )
        for focal_id in sorted(coordinates):
            for neighbor_id in sorted(set(coordinates) - {focal_id}):
                self.assertEqual(
                    _assignment(first, focal_id, neighbor_id),
                    _assignment(second, focal_id, neighbor_id),
                )

    def test_all_eighteen_slots_exist_and_empty_sectors_are_explicit(self) -> None:
        state = _spatial_state({"a": (0.2, 0.2), "b": (0.3, 0.2)})
        observation = self.observer.observe(state, _transcripts(("a", "b")))
        for focal in observation.cells:
            self.assertEqual(18, len(focal.bins))
            self.assertEqual(17, sum(not slot.neighbors for slot in focal.bins))
            self.assertEqual(1, sum(len(slot.neighbors) for slot in focal.bins))
        payload = observation.as_dict()
        self.assertEqual(CLOCK_SECTOR_SCHEMA, payload["schema_version"])
        empty = [
            slot
            for slot in payload["cells"][0]["bins"]
            if slot["neighbor_count"] == 0
        ]
        self.assertEqual(17, len(empty))
        self.assertTrue(all(slot["neighbors"] == [] for slot in empty))

    def test_exact_angular_boundary_goes_to_counter_clockwise_sector(self) -> None:
        radius = 0.10
        coordinates = {
            "a": (0.50, 0.50),
            "b": (
                0.50 + radius * math.cos(math.radians(30.0)),
                0.50 + radius * math.sin(math.radians(30.0)),
            ),
            "c": (
                0.50 + radius * math.cos(math.radians(-30.0)),
                0.50 + radius * math.sin(math.radians(-30.0)),
            ),
        }
        observation = self.observer.observe(
            _spatial_state(coordinates), _transcripts(("a", "b", "c"))
        )
        self.assertEqual(1, _assignment(observation, "a", "b")[0])
        self.assertEqual(0, _assignment(observation, "a", "c")[0])
        self.assertEqual(0, _assignment(observation, "a", "b")[1])

    def test_single_cell_negative_case_keeps_all_slots_empty(self) -> None:
        state = _spatial_state({"only": (0.5, 0.5)})
        observation = self.observer.observe(state, _transcripts(("only",)))
        self.assertEqual(1.0, observation.normalization_distance)
        self.assertTrue(all(not slot.neighbors for slot in observation.cells[0].bins))


class ClockSectorArtifactTests(unittest.TestCase):
    def test_checkpoint_rebuild_is_byte_exact_and_observer_is_non_mutating(self) -> None:
        compiled = compile_carm_scenario(
            load_carm_scenario_config(
                ROOT / "configs" / "scenarios" / "carm" / "high_immune_her2.json"
            )
        )
        runners = build_carm_spatial_runners(
            compiled,
            runner_config=load_runner_config(
                ROOT / "configs" / "runner_reference.json"
            ),
            spatial_config=load_carm_spatial_config(
                ROOT / "configs" / "layers" / "l3_carm_spatial.json"
            ),
            l0_config=ROOT / "configs" / "layers" / "l0_reference_grn.json",
            l1_config=ROOT / "configs" / "layers" / "l1_reference_molecular.json",
            l4_config=ROOT / "configs" / "layers" / "l4_reference_phenotype.json",
        )
        run = runners["spatial_field"].run(compiled.scenario, ticks=2)
        before = run.as_dict()
        history_digest = run.history_digest
        checkpoint = run.checkpoint
        observer = ClockSectorObserver()
        live_observation = observer.observe_tick(run.ticks[-1])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_path = root / "checkpoint.json"
            save_checkpoint(checkpoint_path, checkpoint)
            loaded = load_checkpoint(checkpoint_path)
            rebuilt_observation = observer.observe(loaded.l3, loaded.l0)
            live_path = root / "live.json"
            rebuilt_path = root / "rebuilt.json"
            save_clock_sector_artifact(live_path, live_observation)
            original_bytes = live_path.read_bytes()
            save_clock_sector_artifact(live_path, live_observation)
            save_clock_sector_artifact(rebuilt_path, rebuilt_observation)
            self.assertEqual(original_bytes, live_path.read_bytes())
            self.assertEqual(original_bytes, rebuilt_path.read_bytes())
            payload = json.loads(original_bytes)
            self.assertEqual(
                live_observation.observation_digest,
                payload["observation_digest"],
            )
            live_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_clock_sector_artifact(live_path, live_observation)

        self.assertEqual(before, run.as_dict())
        self.assertEqual(history_digest, run.history_digest)
        self.assertEqual(checkpoint, run.checkpoint)


if __name__ == "__main__":
    unittest.main()
