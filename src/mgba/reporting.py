from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from .experiment import ExperimentManifest, digest_payload
from .layers import LayerId, OrganismOutcome


_REPORT_SCHEMA = "mgba-causal-report-files-0.1"
_LAYER_ORDER = tuple(layer.value for layer in LayerId)
_L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)
_COLORS = (
    "#2563eb",
    "#ea580c",
    "#16a34a",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#ca8a04",
)


@dataclass(frozen=True, slots=True)
class CausalReportPaths:
    root: Path
    manifest: Path
    condition_summary_csv: Path
    layer_effects_csv: Path
    metric_effects_csv: Path
    tissue_timeseries_csv: Path
    l4_observations_csv: Path
    layer_effects_chart: Path
    repair_path_chart: Path
    tissue_damage_chart: Path
    metric_effects_chart: Path
    html: Path

    @property
    def charts(self) -> tuple[Path, ...]:
        return (
            self.layer_effects_chart,
            self.repair_path_chart,
            self.tissue_damage_chart,
            self.metric_effects_chart,
        )

    @property
    def generated_files(self) -> tuple[Path, ...]:
        return (
            self.condition_summary_csv,
            self.layer_effects_csv,
            self.metric_effects_csv,
            self.tissue_timeseries_csv,
            self.l4_observations_csv,
            *self.charts,
            self.html,
        )


@dataclass(frozen=True, slots=True)
class _RawRecord:
    condition_id: str
    condition_kind: str
    seed: int
    relative_path: str
    run: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _MatrixInput:
    root: Path
    manifest: dict[str, Any]
    matrix_id: str
    ticks: int
    seeds: tuple[int, ...]
    condition_order: tuple[str, ...]
    condition_kinds: tuple[tuple[str, str], ...]
    records: tuple[_RawRecord, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read valid JSON from {path}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return raw


def _validated_relative_path(root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute():
        raise ValueError("matrix record path must be relative")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("matrix record path escapes matrix root") from error
    return resolved


def _validate_experiment(raw: Mapping[str, Any]) -> None:
    try:
        manifest = ExperimentManifest(
            schema_version=str(raw["schema_version"]),
            experiment_name=str(raw["experiment_name"]),
            seed=raw["seed"],
            code_version=str(raw["code_version"]),
            config_digest=str(raw["config_digest"]),
            model_versions=tuple(
                sorted(
                    (str(layer), str(version))
                    for layer, version in raw["model_versions"].items()
                )
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("raw run has an invalid experiment manifest") from error
    if manifest.experiment_id != raw.get("experiment_id"):
        raise ValueError("raw run experiment_id does not match its manifest")


def _history_digest(run: Mapping[str, Any]) -> str:
    history = digest_payload(
        {"phase": "initial", "manifest": run["experiment"]}
    )
    for tick in run["ticks"]:
        clean_tick = json.loads(json.dumps(tick))
        for transition in clean_tick["transitions"]:
            transition.pop("event_id", None)
        history = digest_payload({"previous": history, "tick": clean_tick})
    return history


def _validate_raw_run(
    run: dict[str, Any], record: Mapping[str, Any], expected_ticks: int
) -> None:
    required = {
        "checkpoint",
        "checkpoint_id",
        "end_tick",
        "experiment",
        "history_digest",
        "model_status",
        "phenotype_window",
        "scheduled_l4_observations",
        "start_tick",
        "terminal_observation",
        "tick_count",
        "ticks",
    }
    if set(run) != required:
        raise ValueError("raw run fields do not match the run artifact schema")
    _validate_experiment(run["experiment"])
    if run["experiment"]["experiment_id"] != record["experiment_id"]:
        raise ValueError("raw run experiment_id differs from matrix manifest")
    if run["experiment"]["seed"] != record["seed"]:
        raise ValueError("raw run seed differs from matrix manifest")
    if run["history_digest"] != record["history_digest"]:
        raise ValueError("raw run history differs from matrix manifest")
    if (
        run["start_tick"] != 1
        or run["end_tick"] != expected_ticks
        or run["tick_count"] != expected_ticks
        or len(run["ticks"]) != expected_ticks
    ):
        raise ValueError("raw run does not contain the configured full tick range")
    observed_times = tuple(tick["logical_time"] for tick in run["ticks"])
    if observed_times != tuple(range(1, expected_ticks + 1)):
        raise ValueError("raw run tick times are incomplete or unordered")
    computed_history = _history_digest(run)
    if computed_history != run["history_digest"]:
        raise ValueError("raw run history hash chain is invalid")
    checkpoint = dict(run["checkpoint"])
    checkpoint_id = checkpoint.pop("checkpoint_id", None)
    expected_checkpoint_id = f"checkpoint-{digest_payload(checkpoint)[:16]}"
    if (
        checkpoint_id != expected_checkpoint_id
        or run["checkpoint_id"] != expected_checkpoint_id
        or checkpoint["history_digest"] != run["history_digest"]
    ):
        raise ValueError("raw run checkpoint identity is invalid")


def _load_matrix(matrix_root: str | Path) -> _MatrixInput:
    root = Path(matrix_root).resolve()
    manifest = _read_json(root / "manifest.json")
    if manifest.get("schema_version") != "mgba-causal-artifact-0.1":
        raise ValueError("unsupported causal matrix artifact schema")
    matrix_id = str(manifest.get("matrix_id", ""))
    if not matrix_id:
        raise ValueError("causal matrix id must not be empty")
    config = manifest.get("config")
    if not isinstance(config, dict):
        raise ValueError("causal matrix manifest config is missing")
    try:
        ticks = config["ticks"]
        seeds = tuple(config["seeds"])
        perturbation_ids = tuple(
            item["condition_id"] for item in config["perturbations"]
        )
        ablations = tuple(config["ablations"])
    except (KeyError, TypeError) as error:
        raise ValueError("causal matrix config fields are invalid") from error
    if not isinstance(ticks, int) or ticks < 1:
        raise ValueError("causal matrix ticks must be positive")
    condition_order = ("baseline", *perturbation_ids, *ablations)
    condition_kinds = (
        ("baseline", "baseline"),
        *((condition_id, "perturbation") for condition_id in perturbation_ids),
        *((condition_id, "ablation") for condition_id in ablations),
    )
    expected_pairs = {
        (condition_id, seed)
        for condition_id in condition_order
        for seed in seeds
    }
    records_raw = manifest.get("records")
    if not isinstance(records_raw, list):
        raise ValueError("causal matrix record index is missing")
    records: list[_RawRecord] = []
    observed_pairs: set[tuple[str, int]] = set()
    kind_map = dict(condition_kinds)
    for record in records_raw:
        if not isinstance(record, dict):
            raise ValueError("causal matrix record index item must be an object")
        condition_id = record.get("condition_id")
        seed = record.get("seed")
        pair = (condition_id, seed)
        if pair not in expected_pairs or pair in observed_pairs:
            raise ValueError("causal matrix record condition/seed is unexpected")
        if record.get("condition_kind") != kind_map[condition_id]:
            raise ValueError("causal matrix record condition kind is inconsistent")
        path = _validated_relative_path(root, str(record.get("path", "")))
        expected_relative = (
            Path("raw") / condition_id / f"seed-{seed}.json"
        ).as_posix()
        if Path(str(record["path"])).as_posix() != expected_relative:
            raise ValueError("causal matrix record path does not match condition/seed")
        run = _read_json(path)
        _validate_raw_run(run, record, ticks)
        records.append(
            _RawRecord(
                condition_id=condition_id,
                condition_kind=kind_map[condition_id],
                seed=seed,
                relative_path=expected_relative,
                run=run,
            )
        )
        observed_pairs.add(pair)
    if observed_pairs != expected_pairs:
        raise ValueError("causal matrix record index is incomplete")
    record_map = {(record.condition_id, record.seed): record for record in records}
    ordered_records = tuple(
        record_map[(condition_id, seed)]
        for condition_id in condition_order
        for seed in seeds
    )
    return _MatrixInput(
        root=root,
        manifest=manifest,
        matrix_id=matrix_id,
        ticks=ticks,
        seeds=seeds,
        condition_order=condition_order,
        condition_kinds=condition_kinds,
        records=ordered_records,
    )


def _mean_absolute(values: Iterable[float]) -> float:
    materialized = tuple(values)
    if not materialized:
        raise ValueError("raw layer distance cannot be empty")
    return fmean(materialized)


def _aligned_states(
    baseline: list[dict[str, Any]], condition: list[dict[str, Any]]
):
    if tuple(item["cell_id"] for item in baseline) != tuple(
        item["cell_id"] for item in condition
    ):
        raise ValueError("raw paired Cell states do not align")
    return zip(baseline, condition, strict=True)


def _raw_l0_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    fields = (
        "damage_response",
        "signal_expression",
        "repair_expression",
        "metabolic_expression",
        "death_expression",
        "negative_feedback_expression",
    )
    return _mean_absolute(
        abs(a[field] - b[field])
        for a, b in _aligned_states(left["l0"], right["l0"])
        for field in fields
    )


def _raw_l1_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    fields = (
        "damage_receptor",
        "signal_protein",
        "repair_protein",
        "metabolic_capacity",
        "death_effector",
        "feedback_inhibitor",
    )
    return _mean_absolute(
        abs(a[field] - b[field])
        for a, b in _aligned_states(left["l1"], right["l1"])
        for field in fields
    )


def _raw_l2_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    differences: list[float] = []
    for a, b in _aligned_states(left["l2"], right["l2"]):
        differences.extend(
            (
                float(a["phase"] != b["phase"]),
                abs(a["activation"] - b["activation"]),
                abs(a["viability"] - b["viability"]),
                abs(a["stress_load"] - b["stress_load"]),
            )
        )
    return _mean_absolute(differences)


def _raw_l3_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    a = left["l3"]
    b = right["l3"]
    if tuple(node["cell_id"] for node in a["nodes"]) != tuple(
        node["cell_id"] for node in b["nodes"]
    ):
        raise ValueError("raw paired TissueState nodes do not align")
    differences = [float(a["edges"] != b["edges"])]
    for node_a, node_b in zip(a["nodes"], b["nodes"], strict=True):
        differences.extend(
            abs(node_a[field] - node_b[field])
            for field in ("stress", "resource_level", "signal")
        )
    differences.extend(
        abs(a[field] - b[field])
        for field in (
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
    )
    return _mean_absolute(differences)


def _raw_l4_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    return _mean_absolute(abs(left[field] - right[field]) for field in _L4_METRICS)


def _tick_distance(
    layer: str, left: Mapping[str, Any], right: Mapping[str, Any]
) -> float | None:
    if layer == "L0":
        return _raw_l0_distance(left, right)
    if layer == "L1":
        return _raw_l1_distance(left, right)
    if layer == "L2":
        return _raw_l2_distance(left, right)
    if layer == "L3":
        return _raw_l3_distance(left, right)
    if left["l4"] is None or right["l4"] is None:
        return None
    return _raw_l4_distance(left["l4"], right["l4"])


def _derive_rows(matrix: _MatrixInput) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    record_map = {
        (record.condition_id, record.seed): record for record in matrix.records
    }
    layer_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    tissue_rows: list[dict[str, Any]] = []
    l4_rows: list[dict[str, Any]] = []
    kind_map = dict(matrix.condition_kinds)

    for record in matrix.records:
        for tick in record.run["ticks"]:
            tissue_rows.append(
                {
                    "condition_id": record.condition_id,
                    "condition_kind": record.condition_kind,
                    "seed": record.seed,
                    "tick": tick["logical_time"],
                    "tissue_damage": tick["l3"]["tissue_damage"],
                    "mean_viability": tick["l3"]["mean_viability"],
                    "mean_resource": tick["l3"]["mean_resource"],
                }
            )
            if tick["l4"] is not None:
                l4_rows.append(
                    {
                        "condition_id": record.condition_id,
                        "condition_kind": record.condition_kind,
                        "seed": record.seed,
                        "tick": tick["logical_time"],
                        "is_terminal": tick["logical_time"] == record.run["end_tick"],
                        **{field: tick["l4"][field] for field in _L4_METRICS},
                        "outcome": (
                            record.run["phenotype_window"]["outcome"]
                            if tick["logical_time"] == record.run["end_tick"]
                            else ""
                        ),
                    }
                )
        if l4_rows[-1]["tick"] != record.run["end_tick"] or l4_rows[-1][
            "condition_id"
        ] != record.condition_id or l4_rows[-1]["seed"] != record.seed:
            terminal = record.run["terminal_observation"]
            l4_rows.append(
                {
                    "condition_id": record.condition_id,
                    "condition_kind": record.condition_kind,
                    "seed": record.seed,
                    "tick": record.run["end_tick"],
                    "is_terminal": True,
                    **{field: terminal[field] for field in _L4_METRICS},
                    "outcome": record.run["phenotype_window"]["outcome"],
                }
            )

    for condition_id in matrix.condition_order[1:]:
        for seed in matrix.seeds:
            baseline = record_map[("baseline", seed)].run
            condition = record_map[(condition_id, seed)].run
            for layer in _LAYER_ORDER:
                if layer == "L4":
                    effect = _raw_l4_distance(
                        baseline["terminal_observation"],
                        condition["terminal_observation"],
                    )
                else:
                    effect = _tick_distance(
                        layer, baseline["ticks"][-1], condition["ticks"][-1]
                    )
                    assert effect is not None
                first_difference: int | None = None
                for left_tick, right_tick in zip(
                    baseline["ticks"], condition["ticks"], strict=True
                ):
                    distance = _tick_distance(layer, left_tick, right_tick)
                    if distance is not None and distance > 1e-12:
                        first_difference = left_tick["logical_time"]
                        break
                if layer == "L4" and first_difference is None and effect > 1e-12:
                    first_difference = condition["end_tick"]
                layer_rows.append(
                    {
                        "condition_id": condition_id,
                        "condition_kind": kind_map[condition_id],
                        "seed": seed,
                        "layer": layer,
                        "effect": effect,
                        "first_difference_tick": first_difference,
                    }
                )
            for metric in _L4_METRICS:
                metric_rows.append(
                    {
                        "condition_id": condition_id,
                        "condition_kind": kind_map[condition_id],
                        "seed": seed,
                        "metric": metric,
                        "effect": condition["terminal_observation"][metric]
                        - baseline["terminal_observation"][metric],
                    }
                )

    condition_rows: list[dict[str, Any]] = []
    for condition_id in matrix.condition_order[1:]:
        condition_metric_rows = [
            row for row in metric_rows if row["condition_id"] == condition_id
        ]
        outcomes = [
            record_map[(condition_id, seed)].run["phenotype_window"]["outcome"]
            for seed in matrix.seeds
        ]
        row: dict[str, Any] = {
            "condition_id": condition_id,
            "condition_kind": kind_map[condition_id],
            "seed_count": len(matrix.seeds),
        }
        for outcome in OrganismOutcome:
            row[outcome.value] = outcomes.count(outcome.value)
        for metric in _L4_METRICS:
            row[f"delta_{metric}"] = fmean(
                item["effect"]
                for item in condition_metric_rows
                if item["metric"] == metric
            )
        condition_rows.append(row)
    return condition_rows, layer_rows, metric_rows, tissue_rows, l4_rows


def _csv_value(value: Any) -> str | int:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.12g}"
    return value


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_value(row[name]) for name in fieldnames})


def _svg_style() -> str:
    return """<style>
text { font-family: system-ui, sans-serif; fill: #1f2937; font-size: 12px; }
.title { font-size: 20px; font-weight: 600; }
.subtitle { fill: #4b5563; }
.axis { stroke: #6b7280; stroke-width: 1; }
.grid { stroke: #d1d5db; stroke-width: 1; }
@media (prefers-color-scheme: dark) {
  text { fill: #e5e7eb; }
  .subtitle { fill: #9ca3af; }
  .axis { stroke: #9ca3af; }
  .grid { stroke: #374151; }
}
</style>"""


def _svg_document(
    *, width: int, height: int, title: str, description: str, body: str
) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">\n'
        f"<title id=\"title\">{html.escape(title)}</title>\n"
        f"<desc id=\"desc\">{html.escape(description)}</desc>\n"
        f"{_svg_style()}\n{body}\n</svg>\n"
    )


def _label(value: float) -> str:
    if value == 0.0:
        return "0"
    if abs(value) < 0.001:
        return f"{value:.2e}"
    return f"{value:.4f}"


def _layer_effects_svg(
    rows: list[dict[str, Any]], condition_order: tuple[str, ...]
) -> str:
    width, height = 1060, 520
    left, right, top, bottom = 170, 40, 100, 65
    plot_width = width - left - right
    conditions = condition_order[1:]
    floor = 1e-5
    log_floor = math.log10(floor)

    def x(value: float) -> float:
        normalized = (math.log10(max(value, floor)) - log_floor) / -log_floor
        return left + normalized * plot_width

    means = {
        (condition, layer): fmean(
            row["effect"]
            for row in rows
            if row["condition_id"] == condition and row["layer"] == layer
        )
        for condition in conditions
        for layer in _LAYER_ORDER
    }
    parts = [
        '<text class="title" x="20" y="32">Layer effects by condition</text>',
        '<text class="subtitle" x="20" y="55">Mean absolute state distance; log10 axis, exact zeros remain in CSV</text>',
    ]
    for index, layer in enumerate(_LAYER_ORDER):
        legend_x = 200 + index * 145
        parts.append(
            f'<circle cx="{legend_x}" cy="77" r="5" fill="{_COLORS[index]}"/>'
            f'<text x="{legend_x + 10}" y="81">{layer}</text>'
        )
    tick_values = (1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0)
    plot_top = top
    plot_bottom = height - bottom
    for value in tick_values:
        px = x(value)
        parts.append(
            f'<line class="grid" x1="{px:.2f}" y1="{plot_top}" x2="{px:.2f}" y2="{plot_bottom}"/>'
            f'<text x="{px:.2f}" y="{plot_bottom + 22}" text-anchor="middle">{value:g}</text>'
        )
    row_height = (plot_bottom - plot_top) / len(conditions)
    offsets = (-12, -6, 0, 6, 12)
    for condition_index, condition in enumerate(conditions):
        center_y = plot_top + (condition_index + 0.5) * row_height
        parts.append(
            f'<text x="{left - 12}" y="{center_y + 4:.2f}" text-anchor="end">{html.escape(condition)}</text>'
        )
        for layer_index, layer in enumerate(_LAYER_ORDER):
            value = means[(condition, layer)]
            px = x(value)
            py = center_y + offsets[layer_index]
            parts.append(
                f'<circle cx="{px:.2f}" cy="{py:.2f}" r="5" fill="{_COLORS[layer_index]}">'
                f'<title>{html.escape(condition)} {layer}: {_label(value)}</title></circle>'
            )
    parts.extend(
        (
            f'<line class="axis" x1="{left}" y1="{plot_bottom}" x2="{width-right}" y2="{plot_bottom}"/>',
            f'<text x="{left + plot_width / 2:.2f}" y="{height - 18}" text-anchor="middle">Mean absolute effect (unit interval, log10 display)</text>',
        )
    )
    return _svg_document(
        width=width,
        height=height,
        title="Layer effects by condition",
        description="Log-scale dot plot comparing L0 through L4 mean absolute effects for six conditions.",
        body="\n".join(parts),
    )


def _repair_path_svg(rows: list[dict[str, Any]], condition_id: str) -> str:
    width, height = 820, 440
    left, right, top, bottom = 80, 45, 75, 70
    effects = [
        fmean(
            row["effect"]
            for row in rows
            if row["condition_id"] == condition_id and row["layer"] == layer
        )
        for layer in _LAYER_ORDER
    ]
    floor = 1e-5
    y_min, y_max = math.log10(floor), 0.0

    def x(index: int) -> float:
        return left + index * (width - left - right) / (len(_LAYER_ORDER) - 1)

    def y(value: float) -> float:
        normalized = (math.log10(max(value, floor)) - y_min) / (y_max - y_min)
        return height - bottom - normalized * (height - top - bottom)

    points = " ".join(
        f"{x(index):.2f},{y(value):.2f}" for index, value in enumerate(effects)
    )
    parts = [
        f'<text class="title" x="20" y="32">{html.escape(condition_id)} propagation path</text>',
        '<text class="subtitle" x="20" y="54">Mean absolute effect across the frozen L0→L4 state vectors</text>',
        f'<polyline points="{points}" fill="none" stroke="{_COLORS[0]}" stroke-width="3"/>',
    ]
    for index, (layer, value) in enumerate(zip(_LAYER_ORDER, effects, strict=True)):
        px, py = x(index), y(value)
        parts.extend(
            (
                f'<circle cx="{px:.2f}" cy="{py:.2f}" r="6" fill="{_COLORS[0]}"/>',
                f'<text x="{px:.2f}" y="{height-bottom+25}" text-anchor="middle">{layer}</text>',
                f'<text x="{px:.2f}" y="{py-12:.2f}" text-anchor="middle">{_label(value)}</text>',
            )
        )
    for tick in (1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0):
        py = y(tick)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{width-right}" y2="{py:.2f}"/>'
            f'<text x="{left-10}" y="{py+4:.2f}" text-anchor="end">{tick:g}</text>'
        )
    parts.append(
        f'<text transform="translate(18 {top + (height-top-bottom)/2:.2f}) rotate(-90)" text-anchor="middle">Mean absolute effect (log10)</text>'
    )
    return _svg_document(
        width=width,
        height=height,
        title=f"{condition_id} propagation path",
        description="Line plot of mean absolute effect from L0 to L4 for the complete repair knockdown condition.",
        body="\n".join(parts),
    )


def _tissue_damage_svg(
    rows: list[dict[str, Any]], condition_order: tuple[str, ...], selected_seed: int
) -> str:
    width, height = 1060, 520
    left, right, top, bottom = 75, 45, 105, 65
    selected = [row for row in rows if row["seed"] == selected_seed]
    max_tick = max(row["tick"] for row in selected)

    def x(tick: int) -> float:
        return left + (tick - 1) / max(1, max_tick - 1) * (width - left - right)

    def y(value: float) -> float:
        return top + (1.0 - value) * (height - top - bottom)

    parts = [
        f'<text class="title" x="20" y="32">Tissue damage trajectories — seed {selected_seed}</text>',
        '<text class="subtitle" x="20" y="54">Every fast tick from raw L3 TissueState</text>',
    ]
    for index, condition in enumerate(condition_order):
        legend_x = 30 + (index % 4) * 250
        legend_y = 76 + (index // 4) * 22
        color = _COLORS[index % len(_COLORS)]
        parts.append(
            f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x+24}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>'
            f'<text x="{legend_x+32}" y="{legend_y+4}">{html.escape(condition)}</text>'
        )
        condition_rows = [
            row for row in selected if row["condition_id"] == condition
        ]
        points = " ".join(
            f"{x(row['tick']):.2f},{y(row['tissue_damage']):.2f}"
            for row in condition_rows
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2">'
            f'<title>{html.escape(condition)}</title></polyline>'
        )
    plot_bottom = height - bottom
    for value in (0.0, 0.25, 0.5, 0.75, 1.0):
        py = y(value)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{width-right}" y2="{py:.2f}"/>'
            f'<text x="{left-10}" y="{py+4:.2f}" text-anchor="end">{value:g}</text>'
        )
    for tick in (1, max(1, round(max_tick / 2)), max_tick):
        px = x(tick)
        parts.append(
            f'<text x="{px:.2f}" y="{plot_bottom+22}" text-anchor="middle">{tick}</text>'
        )
    parts.extend(
        (
            f'<line class="axis" x1="{left}" y1="{plot_bottom}" x2="{width-right}" y2="{plot_bottom}"/>',
            f'<text x="{left+(width-left-right)/2:.2f}" y="{height-18}" text-anchor="middle">Logical tick</text>',
            f'<text transform="translate(18 {top+(height-top-bottom)/2:.2f}) rotate(-90)" text-anchor="middle">Tissue damage (unit interval)</text>',
        )
    )
    return _svg_document(
        width=width,
        height=height,
        title=f"Tissue damage trajectories for seed {selected_seed}",
        description="Line chart of tissue damage over every logical tick for all matrix conditions.",
        body="\n".join(parts),
    )


def _metric_effects_svg(
    rows: list[dict[str, Any]], condition_order: tuple[str, ...]
) -> str:
    width, height = 1060, 540
    left, right, top, bottom = 175, 45, 105, 65
    conditions = condition_order[1:]
    max_abs = max(abs(row["effect"]) for row in rows)
    max_abs = max(max_abs, 1e-6)

    def x(value: float) -> float:
        return left + (value + max_abs) / (2 * max_abs) * (width - left - right)

    means = {
        (condition, metric): fmean(
            row["effect"]
            for row in rows
            if row["condition_id"] == condition and row["metric"] == metric
        )
        for condition in conditions
        for metric in _L4_METRICS
    }
    parts = [
        '<text class="title" x="20" y="32">Final L4 metric effects</text>',
        '<text class="subtitle" x="20" y="54">Condition minus paired baseline; shared linear axis</text>',
    ]
    for index, metric in enumerate(_L4_METRICS):
        legend_x = 120 + index * 180
        parts.append(
            f'<circle cx="{legend_x}" cy="78" r="5" fill="{_COLORS[index]}"/>'
            f'<text x="{legend_x+10}" y="82">{html.escape(metric)}</text>'
        )
    plot_bottom = height - bottom
    zero_x = x(0.0)
    parts.append(
        f'<line class="axis" x1="{zero_x:.2f}" y1="{top}" x2="{zero_x:.2f}" y2="{plot_bottom}"/>'
    )
    for value in (-max_abs, -max_abs / 2, 0.0, max_abs / 2, max_abs):
        px = x(value)
        parts.append(
            f'<line class="grid" x1="{px:.2f}" y1="{top}" x2="{px:.2f}" y2="{plot_bottom}"/>'
            f'<text x="{px:.2f}" y="{plot_bottom+22}" text-anchor="middle">{value:.3g}</text>'
        )
    row_height = (plot_bottom - top) / len(conditions)
    offsets = (-12, -6, 0, 6, 12)
    for condition_index, condition in enumerate(conditions):
        center_y = top + (condition_index + 0.5) * row_height
        parts.append(
            f'<text x="{left-12}" y="{center_y+4:.2f}" text-anchor="end">{html.escape(condition)}</text>'
        )
        for metric_index, metric in enumerate(_L4_METRICS):
            value = means[(condition, metric)]
            px = x(value)
            py = center_y + offsets[metric_index]
            parts.append(
                f'<circle cx="{px:.2f}" cy="{py:.2f}" r="5" fill="{_COLORS[metric_index]}">'
                f'<title>{html.escape(condition)} {html.escape(metric)}: {_label(value)}</title></circle>'
            )
    parts.append(
        f'<text x="{left+(width-left-right)/2:.2f}" y="{height-18}" text-anchor="middle">Final metric difference (condition − baseline)</text>'
    )
    return _svg_document(
        width=width,
        height=height,
        title="Final L4 metric effects",
        description="Diverging dot plot of five final L4 metric differences for six non-baseline conditions.",
        body="\n".join(parts),
    )


def _report_html(
    matrix: _MatrixInput,
    condition_rows: list[dict[str, Any]],
    selected_seed: int,
) -> str:
    table_rows = []
    for row in condition_rows:
        outcomes = ", ".join(
            f"{outcome.value}={row[outcome.value]}" for outcome in OrganismOutcome
        )
        table_rows.append(
            "<tr>"
            f"<td><code>{html.escape(row['condition_id'])}</code></td>"
            f"<td>{html.escape(row['condition_kind'])}</td>"
            f"<td>{html.escape(outcomes)}</td>"
            f"<td>{row['delta_vitality']:.6f}</td>"
            f"<td>{row['delta_damage_burden']:.6f}</td>"
            f"<td>{row['delta_homeostasis']:.6f}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M-GBA WP8 causal matrix report</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 24px; line-height: 1.5; }}
h1, h2 {{ font-weight: 600; }}
.boundary {{ border-left: 4px solid #ca8a04; padding-left: 12px; }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); padding: 8px; text-align: right; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
figure {{ margin: 28px 0; }}
img {{ width: 100%; height: auto; }}
figcaption {{ color: color-mix(in srgb, currentColor 70%, transparent); }}
code {{ font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<h1>M-GBA WP8 causal matrix report</h1>
<p><strong>Matrix:</strong> <code>{html.escape(matrix.matrix_id)}</code> · <strong>runs:</strong> {len(matrix.records)} · <strong>seeds:</strong> {', '.join(map(str, matrix.seeds))}</p>
<p class="boundary">All quantities are paired counterfactual differences inside the current dimensionless reference model. They are not biological, clinical, or real-world causal estimates. The current model has no stochastic dynamics, so the seed replicates are numerically identical.</p>
<h2>Condition outcomes</h2>
<table>
<thead><tr><th>Condition</th><th>Kind</th><th>Outcomes</th><th>Δ vitality</th><th>Δ damage</th><th>Δ homeostasis</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody>
</table>
<figure><img src="layer-effects.svg" alt="Layer effects for every non-baseline condition"><figcaption>Mean absolute state distance across L0–L4. The log display keeps small perturbation effects visible beside large ablations.</figcaption></figure>
<figure><img src="repair-path.svg" alt="Repair knockdown propagation from L0 to L4"><figcaption>Complete repair knockdown attenuates strongly from L0 into L3, then remains measurable at L4.</figcaption></figure>
<figure><img src="tissue-damage.svg" alt="Tissue damage over time for all conditions"><figcaption>Raw L3 tissue damage at every tick for seed {selected_seed}.</figcaption></figure>
<figure><img src="metric-effects.svg" alt="Final L4 metric differences"><figcaption>Signed final phenotype differences relative to the same-seed baseline.</figcaption></figure>
<h2>Rebuildable data</h2>
<p>The tables behind these figures are <a href="condition-summary.csv">condition-summary.csv</a>, <a href="layer-effects.csv">layer-effects.csv</a>, <a href="metric-effects.csv">metric-effects.csv</a>, <a href="tissue-timeseries.csv">tissue-timeseries.csv</a>, and <a href="l4-observations.csv">l4-observations.csv</a>. This page is read-only and contains no simulation controls or network dependencies.</p>
</body>
</html>
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_causal_report(
    matrix_root: str | Path, output_dir: str | Path | None = None
) -> CausalReportPaths:
    matrix = _load_matrix(matrix_root)
    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else matrix.root / "derived" / "report"
    )
    raw_root = (matrix.root / "raw").resolve()
    try:
        output.relative_to(raw_root)
    except ValueError:
        pass
    else:
        raise ValueError("report output cannot be inside the raw artifact directory")
    output.mkdir(parents=True, exist_ok=True)
    paths = CausalReportPaths(
        root=output,
        manifest=output / "report-manifest.json",
        condition_summary_csv=output / "condition-summary.csv",
        layer_effects_csv=output / "layer-effects.csv",
        metric_effects_csv=output / "metric-effects.csv",
        tissue_timeseries_csv=output / "tissue-timeseries.csv",
        l4_observations_csv=output / "l4-observations.csv",
        layer_effects_chart=output / "layer-effects.svg",
        repair_path_chart=output / "repair-path.svg",
        tissue_damage_chart=output / "tissue-damage.svg",
        metric_effects_chart=output / "metric-effects.svg",
        html=output / "report.html",
    )
    condition_rows, layer_rows, metric_rows, tissue_rows, l4_rows = _derive_rows(
        matrix
    )
    _write_csv(
        paths.condition_summary_csv,
        (
            "condition_id",
            "condition_kind",
            "seed_count",
            "stable",
            "recovered",
            "deteriorating",
            "failed",
            *(f"delta_{metric}" for metric in _L4_METRICS),
        ),
        condition_rows,
    )
    _write_csv(
        paths.layer_effects_csv,
        (
            "condition_id",
            "condition_kind",
            "seed",
            "layer",
            "effect",
            "first_difference_tick",
        ),
        layer_rows,
    )
    _write_csv(
        paths.metric_effects_csv,
        ("condition_id", "condition_kind", "seed", "metric", "effect"),
        metric_rows,
    )
    _write_csv(
        paths.tissue_timeseries_csv,
        (
            "condition_id",
            "condition_kind",
            "seed",
            "tick",
            "tissue_damage",
            "mean_viability",
            "mean_resource",
        ),
        tissue_rows,
    )
    _write_csv(
        paths.l4_observations_csv,
        (
            "condition_id",
            "condition_kind",
            "seed",
            "tick",
            "is_terminal",
            *_L4_METRICS,
            "outcome",
        ),
        l4_rows,
    )
    selected_seed = 42 if 42 in matrix.seeds else matrix.seeds[0]
    repair_condition = (
        "repair_kd_000"
        if "repair_kd_000" in matrix.condition_order
        else matrix.condition_order[1]
    )
    paths.layer_effects_chart.write_text(
        _layer_effects_svg(layer_rows, matrix.condition_order), encoding="utf-8"
    )
    paths.repair_path_chart.write_text(
        _repair_path_svg(layer_rows, repair_condition), encoding="utf-8"
    )
    paths.tissue_damage_chart.write_text(
        _tissue_damage_svg(tissue_rows, matrix.condition_order, selected_seed),
        encoding="utf-8",
    )
    paths.metric_effects_chart.write_text(
        _metric_effects_svg(metric_rows, matrix.condition_order), encoding="utf-8"
    )
    paths.html.write_text(
        _report_html(matrix, condition_rows, selected_seed), encoding="utf-8"
    )
    manifest_payload = {
        "schema_version": _REPORT_SCHEMA,
        "matrix_id": matrix.matrix_id,
        "source_manifest_digest": digest_payload(matrix.manifest),
        "files": {
            path.name: _sha256(path)
            for path in sorted(paths.generated_files, key=lambda item: item.name)
        },
    }
    paths.manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return paths
