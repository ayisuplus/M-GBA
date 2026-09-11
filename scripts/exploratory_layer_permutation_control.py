#!/usr/bin/env python
"""ADR-0048 control 2 (layer-permutation): WP8 metrics on spliced traces.

Pure standard library; runs in ``.venv``. Reads the frozen WP8 raw traces of
matrix-7da4137aa39d5122 and re-implements the WP8 paired-comparison
semantics of ``src/mgba/experiments.py`` verbatim (per-layer mean-absolute
distances, 1e-12 first-difference propagation ticks, same-seed pairing, L4
from terminal_observation with the end_tick fallback).

For every ordered donor pair (A, B) of distinct non-baseline conditions
(30 pairs x 3 seeds = 90 hybrids), a hybrid trace takes its L0/L1 segments
from donor A and its L2/L3/L4 segments from donor B (same seed, per tick),
then is compared against the same-seed baseline.

Pre-registered criteria (ADR-0048 section 3.2):
  C2-1 donor fidelity: every hybrid layer slot reproduces the donor's real
       per-layer effect (<=1e-12) and propagation tick (exact).
  C2-2 profile exclusion: every hybrid combined profile (5 distances +
       5 ticks) differs from all 6 real condition profiles.
  C2-3 propagation degradation (descriptive bands frozen in the ADR):
       collision rate of hybrid tick vectors against the real library.
Anchor: the 18 real comparisons must reproduce the frozen derived summary
within 1e-12 before any criterion is evaluated.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from itertools import permutations
from pathlib import Path

SCHEMA_VERSION = "mgba-falsification-control-0.1"
CONTROL_ID = "layer-permutation"
MATRIX_ROOT = Path("artifacts/mvp-demo/matrix-7da4137aa39d5122")
SUMMARY_PATH = MATRIX_ROOT / "derived" / "summary.json"

LAYERS = ("L0", "L1", "L2", "L3", "L4")
NON_BASELINE = (
    "repair_kd_000",
    "repair_clamp_050",
    "repair_oe_100",
    "l1_static",
    "l2_static",
    "l3_static",
)
SEEDS = (41, 42, 43)
EPSILON = 1e-12

_L0_FIELDS = (
    "damage_response",
    "signal_expression",
    "repair_expression",
    "metabolic_expression",
    "death_expression",
    "negative_feedback_expression",
)
_L1_FIELDS = (
    "damage_receptor",
    "signal_protein",
    "repair_protein",
    "metabolic_capacity",
    "death_effector",
    "feedback_inhibitor",
)
_L3_FIELDS = (
    "edge_density",
    "mean_activation",
    "mean_viability",
    "mean_resource",
    "mean_signal",
    "dead_fraction",
    "repair_activity",
    "coordinated_signal",
    "tissue_damage",
)
_L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)

SCIENTIFIC_BOUNDARY = (
    "阴性对照：检验评估管线在无信号输入下是否假阳性；不构成对任何生物主张的"
    "支持或否定，不撤销历史 verdict，仅标定其证据等级"
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mean_absolute(differences: list[float]) -> float:
    if not differences:
        raise ValueError("layer distance requires at least one value")
    return sum(differences) / len(differences)


def _aligned(left_states: list[dict], right_states: list[dict]):
    left_ids = [state["cell_id"] for state in left_states]
    right_ids = [state["cell_id"] for state in right_states]
    if left_ids != right_ids:
        raise ValueError("paired layer states must have aligned Cell ids")
    return zip(left_states, right_states)


def _l0_distance(baseline_tick: dict, condition_tick: dict) -> float:
    return _mean_absolute(
        [
            abs(left[field] - right[field])
            for left, right in _aligned(baseline_tick["l0"], condition_tick["l0"])
            for field in _L0_FIELDS
        ]
    )


def _l1_distance(baseline_tick: dict, condition_tick: dict) -> float:
    return _mean_absolute(
        [
            abs(left[field] - right[field])
            for left, right in _aligned(baseline_tick["l1"], condition_tick["l1"])
            for field in _L1_FIELDS
        ]
    )


def _l2_distance(baseline_tick: dict, condition_tick: dict) -> float:
    differences: list[float] = []
    for left, right in _aligned(baseline_tick["l2"], condition_tick["l2"]):
        differences.extend(
            (
                float(left["phase"] != right["phase"]),
                abs(left["activation"] - right["activation"]),
                abs(left["viability"] - right["viability"]),
                abs(left["stress_load"] - right["stress_load"]),
            )
        )
    return _mean_absolute(differences)


def _l3_distance(baseline_tick: dict, condition_tick: dict) -> float:
    left = baseline_tick["l3"]
    right = condition_tick["l3"]
    if [node["cell_id"] for node in left["nodes"]] != [
        node["cell_id"] for node in right["nodes"]
    ]:
        raise ValueError("paired TissueState nodes must align")
    differences = [float(left["edges"] != right["edges"])]
    for left_node, right_node in zip(left["nodes"], right["nodes"]):
        differences.extend(
            (
                abs(left_node["stress"] - right_node["stress"]),
                abs(left_node["resource_level"] - right_node["resource_level"]),
                abs(left_node["signal"] - right_node["signal"]),
            )
        )
    differences.extend(abs(left[field] - right[field]) for field in _L3_FIELDS)
    return _mean_absolute(differences)


def _l4_distance(left: dict, right: dict) -> float:
    return _mean_absolute([abs(left[field] - right[field]) for field in _L4_METRICS])


def _tick_layer_distance(layer: str, baseline_tick: dict, condition_tick: dict):
    if layer == "L0":
        return _l0_distance(baseline_tick, condition_tick)
    if layer == "L1":
        return _l1_distance(baseline_tick, condition_tick)
    if layer == "L2":
        return _l2_distance(baseline_tick, condition_tick)
    if layer == "L3":
        return _l3_distance(baseline_tick, condition_tick)
    if baseline_tick["l4"] is None or condition_tick["l4"] is None:
        return None
    return _l4_distance(baseline_tick["l4"], condition_tick["l4"])


def compare_traces(baseline: dict, condition: dict) -> dict:
    """WP8 compare_runs semantics on raw JSON traces (same seed assumed)."""
    baseline_ticks = baseline["ticks"]
    condition_ticks = condition["ticks"]
    if len(baseline_ticks) != len(condition_ticks):
        raise ValueError("paired traces must have the same tick count")
    layer_effects: dict[str, float] = {}
    propagation: dict[str, int | None] = {}
    for layer in LAYERS:
        if layer == "L4":
            terminal_distance = _l4_distance(
                baseline["terminal_observation"], condition["terminal_observation"]
            )
            layer_effects[layer] = terminal_distance
        else:
            layer_effects[layer] = _tick_layer_distance(
                layer, baseline_ticks[-1], condition_ticks[-1]
            )
        first_difference: int | None = None
        for left_tick, right_tick in zip(baseline_ticks, condition_ticks):
            distance = _tick_layer_distance(layer, left_tick, right_tick)
            if distance is not None and distance > EPSILON:
                first_difference = left_tick["logical_time"]
                break
        if layer == "L4" and first_difference is None and layer_effects[layer] > EPSILON:
            first_difference = condition["end_tick"]
        propagation[layer] = first_difference
    return {"layer_effects": layer_effects, "propagation_ticks": propagation}


def make_hybrid(donor_low: dict, donor_high: dict) -> dict:
    """L0/L1 segments from donor_low, L2/L3/L4 from donor_high, per tick."""
    ticks = []
    for low_tick, high_tick in zip(donor_low["ticks"], donor_high["ticks"]):
        if low_tick["logical_time"] != high_tick["logical_time"]:
            raise ValueError("donor ticks must align in logical time")
        ticks.append(
            {
                "logical_time": low_tick["logical_time"],
                "l0": low_tick["l0"],
                "l1": low_tick["l1"],
                "l2": high_tick["l2"],
                "l3": high_tick["l3"],
                "l4": high_tick["l4"],
            }
        )
    return {
        "ticks": ticks,
        "terminal_observation": donor_high["terminal_observation"],
        "end_tick": donor_high["end_tick"],
    }


def _profiles_equal(effects_a, ticks_a, effects_b, ticks_b) -> bool:
    return all(
        abs(effects_a[layer] - effects_b[layer]) <= EPSILON for layer in LAYERS
    ) and all(ticks_a[layer] == ticks_b[layer] for layer in LAYERS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    traces: dict[tuple[str, int], dict] = {}
    inputs = []
    for condition in ("baseline", *NON_BASELINE):
        for seed in SEEDS:
            path = MATRIX_ROOT / "raw" / condition / f"seed-{seed}.json"
            traces[(condition, seed)] = json.loads(path.read_text(encoding="utf-8"))
    for rel, role in (
        (str(SUMMARY_PATH).replace("\\", "/"), "frozen WP8 derived summary (anchor)"),
    ):
        inputs.append({"path": rel, "sha256": _sha256_file(Path(rel)), "role": role})
    inputs.append(
        {
            "path": "artifacts/mvp-demo/matrix-7da4137aa39d5122/raw/ (21 files)",
            "sha256": sha256(
                "".join(
                    _sha256_file(MATRIX_ROOT / "raw" / c / f"seed-{s}.json")
                    for c in ("baseline", *NON_BASELINE)
                    for s in SEEDS
                ).encode("utf-8")
            ).hexdigest(),
            "role": "frozen WP8 raw traces (concatenated per-file digests)",
        }
    )

    # Anchor: reproduce the 18 frozen real comparisons within 1e-12.
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    real: dict[tuple[str, int], dict] = {}
    anchor_max_diff = 0.0
    anchor_tick_mismatches = 0
    frozen = {
        (item["condition_id"], item["seed"]): item for item in summary["comparisons"]
    }
    for condition in NON_BASELINE:
        for seed in SEEDS:
            result = compare_traces(traces[("baseline", seed)], traces[(condition, seed)])
            real[(condition, seed)] = result
            reference = frozen[(condition, seed)]
            ref_effects = dict(reference["layer_effects"])
            ref_ticks = dict(reference["propagation_ticks"])
            for layer in LAYERS:
                anchor_max_diff = max(
                    anchor_max_diff,
                    abs(result["layer_effects"][layer] - ref_effects[layer]),
                )
                if result["propagation_ticks"][layer] != ref_ticks[layer]:
                    anchor_tick_mismatches += 1
    anchor_ok = anchor_max_diff <= EPSILON and anchor_tick_mismatches == 0

    # Hybrids: all ordered donor pairs (A != B), prefix splice L0-L1 / L2-L4.
    hybrids = []
    fidelity_failures = []
    library_exclusion_failures = []
    tick_collisions = 0
    for donor_low, donor_high in permutations(NON_BASELINE, 2):
        for seed in SEEDS:
            hybrid = make_hybrid(traces[(donor_low, seed)], traces[(donor_high, seed)])
            result = compare_traces(traces[("baseline", seed)], hybrid)
            low_real = real[(donor_low, seed)]
            high_real = real[(donor_high, seed)]
            # C2-1: donor fidelity per layer slot.
            for layer in LAYERS:
                donor = low_real if layer in ("L0", "L1") else high_real
                effect_diff = abs(
                    result["layer_effects"][layer] - donor["layer_effects"][layer]
                )
                tick_equal = (
                    result["propagation_ticks"][layer]
                    == donor["propagation_ticks"][layer]
                )
                if effect_diff > EPSILON or not tick_equal:
                    fidelity_failures.append(
                        {
                            "pair": [donor_low, donor_high],
                            "seed": seed,
                            "layer": layer,
                            "effect_diff": effect_diff,
                            "tick_equal": tick_equal,
                        }
                    )
            # C2-2: combined profile outside the 6-member real library.
            in_library = any(
                _profiles_equal(
                    result["layer_effects"],
                    result["propagation_ticks"],
                    real[(condition, seed)]["layer_effects"],
                    real[(condition, seed)]["propagation_ticks"],
                )
                for condition in NON_BASELINE
            )
            if in_library:
                library_exclusion_failures.append(
                    {"pair": [donor_low, donor_high], "seed": seed}
                )
            # C2-3: tick-vector collision with the real tick library.
            tick_vector = tuple(result["propagation_ticks"][layer] for layer in LAYERS)
            real_tick_vectors = {
                tuple(real[(condition, seed)]["propagation_ticks"][layer] for layer in LAYERS)
                for condition in NON_BASELINE
            }
            if tick_vector in real_tick_vectors:
                tick_collisions += 1
            hybrids.append(
                {
                    "donor_low": donor_low,
                    "donor_high": donor_high,
                    "seed": seed,
                    "layer_effects": result["layer_effects"],
                    "propagation_ticks": result["propagation_ticks"],
                    "tick_vector_in_real_library": tick_vector in real_tick_vectors,
                }
            )

    total = len(hybrids)
    collision_rate = tick_collisions / total
    c2_1 = not fidelity_failures
    c2_2 = not library_exclusion_failures
    if collision_rate < 1.0 / 3.0:
        c2_3_band = "tick 指标单独亦有区分度（<1/3）"
    elif collision_rate <= 2.0 / 3.0:
        c2_3_band = "tick 口径粗糙、单独区分度有限（1/3–2/3）"
    else:
        c2_3_band = "tick 指标无独立区分度（>2/3）"
    verdict = "criteria_met" if (anchor_ok and c2_1 and c2_2) else "criteria_not_met"

    results_payload = {
        "schema_version": SCHEMA_VERSION,
        "control_id": CONTROL_ID,
        "adr": "ADR-0048",
        "created_date": "2026-09-11",
        "status": "completed",
        "inputs": inputs,
        "derivation": {
            "rule": (
                "非 baseline 6 条件的全部有序供体对 (A,B), A!=B（30 对 × 3 种子 = 90 条）；"
                "混合 trace 每 tick 的 L0/L1 段取自供体 A 同种子 trace，L2/L3/L4 段取自供体 B "
                "同种子 trace；与同种子 baseline 配对，按 WP8 口径重算 5 层距离与传播 tick；"
                "全枚举，无随机数"
            ),
            "splice": "L0,L1 <- donor_low; L2,L3,L4 <- donor_high",
            "epsilon": EPSILON,
        },
        "criteria": {
            "C2-1": "450/450 层槽位与供体真实同层值一致（距离 ≤1e-12，tick 精确相等）",
            "C2-2": "90/90 混合组合剖面（5 距离 + 5 tick）不在 6 成员真实库内",
            "C2-3": "传播 tick 向量与真实库碰撞率的预注册解释带：<1/3 有区分度；1/3–2/3 口径粗糙；>2/3 无独立区分度",
            "anchor": "18 条真实配对复现冻结 derived summary（距离 ≤1e-12，tick 精确）后才计算判据",
        },
        "anchors": {
            "real_comparisons_recomputed": len(real),
            "anchor_max_abs_effect_diff": anchor_max_diff,
            "anchor_tick_mismatches": anchor_tick_mismatches,
            "anchor_ok": anchor_ok,
        },
        "results": {
            "hybrid_count": total,
            "c2_1_donor_fidelity": {
                "passed": c2_1,
                "slot_count": total * 5,
                "failures": fidelity_failures,
            },
            "c2_2_library_exclusion": {
                "passed": c2_2,
                "hybrids_in_real_library": len(library_exclusion_failures),
                "failures": library_exclusion_failures,
            },
            "c2_3_tick_collisions": {
                "collisions": tick_collisions,
                "collision_rate": collision_rate,
                "band": c2_3_band,
            },
            "hybrids": hybrids,
        },
        "verdict": verdict,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.json"
    if results_path.exists():
        raise SystemExit(f"refusing to overwrite existing results: {results_path}")
    results_path.write_text(
        json.dumps(results_payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    script_path = Path(__file__).resolve()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "control_id": CONTROL_ID,
        "kind": "manifest",
        "entries": [
            {
                "path": "results.json",
                "sha256": _sha256_file(results_path),
                "bytes": results_path.stat().st_size,
            },
            {
                "path": f"scripts/{script_path.name}",
                "sha256": _sha256_file(script_path),
                "bytes": script_path.stat().st_size,
            },
        ],
        "determinism": None,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "control_id": CONTROL_ID,
                "verdict": verdict,
                "anchor_ok": anchor_ok,
                "anchor_max_abs_effect_diff": anchor_max_diff,
                "c2_1_passed": c2_1,
                "c2_2_passed": c2_2,
                "c2_3_collision_rate": collision_rate,
                "c2_3_band": c2_3_band,
                "hybrid_count": total,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
