"""Read-only per-tick trajectory report for a single saved run artifact.

This module is experiment-observation infrastructure: it reads one raw run
artifact written by ``mgba simulate --trace-out`` (or one matrix raw run) and
rebuilds deterministic CSV tables, accessible SVG charts, and a static HTML
record. It never executes or mutates any layer model, and it refuses artifacts
whose manifest, history hash chain, or checkpoint identity fail recomputation.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

from .hashing import digest_payload
from .layers import CellPhase
from .reporting import (
    COLORS,
    history_digest,
    label,
    svg_document,
    validate_experiment,
    write_csv,
)
from .validation import file_sha256

_RUN_REPORT_SCHEMA = "mgba-run-report-files-0.1"

L0_FIELDS = (
    "damage_response",
    "signal_expression",
    "repair_expression",
    "metabolic_expression",
    "death_expression",
    "negative_feedback_expression",
)
L1_FIELDS = (
    "damage_receptor",
    "signal_protein",
    "repair_protein",
    "metabolic_capacity",
    "death_effector",
    "feedback_inhibitor",
)
L2_FIELDS = ("viability", "activation", "stress_load")
L3_FIELDS = (
    "mean_resource",
    "tissue_damage",
    "repair_activity",
    "mean_activation",
    "mean_signal",
    "dead_fraction",
)
L4_FIELDS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)
_RUN_KEYS = {
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


@dataclass(frozen=True, slots=True)
class RunReportPaths:
    root: Path
    manifest: Path
    l0_csv: Path
    l1_csv: Path
    l2_csv: Path
    l2_phase_csv: Path
    l3_csv: Path
    l4_csv: Path
    l0_chart: Path
    l1_chart: Path
    l2_chart: Path
    l2_phase_chart: Path
    l3_chart: Path
    l4_chart: Path
    html: Path

    @property
    def csvs(self) -> tuple[Path, ...]:
        return (
            self.l0_csv,
            self.l1_csv,
            self.l2_csv,
            self.l2_phase_csv,
            self.l3_csv,
            self.l4_csv,
        )

    @property
    def charts(self) -> tuple[Path, ...]:
        return (
            self.l0_chart,
            self.l1_chart,
            self.l2_chart,
            self.l2_phase_chart,
            self.l3_chart,
            self.l4_chart,
        )

    @property
    def generated_files(self) -> tuple[Path, ...]:
        return (*self.csvs, *self.charts, self.html)


def _validate_run_document(run: Any) -> dict[str, Any]:
    if not isinstance(run, dict) or set(run) != _RUN_KEYS:
        raise ValueError("run artifact fields do not match the run artifact schema")
    validate_experiment(run["experiment"])
    start = run["start_tick"]
    end = run["end_tick"]
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or start != 1
        or end < start
        or run["tick_count"] != end
        or len(run["ticks"]) != end
    ):
        raise ValueError("run artifact does not contain a complete 1..end_tick range")
    times = []
    for tick in run["ticks"]:
        if not isinstance(tick, dict):
            raise ValueError("run artifact tick is not an object")
        times.append(tick["logical_time"])
        for layer in ("l0", "l1", "l2"):
            states = tick[layer]
            if not isinstance(states, list) or not states:
                raise ValueError(f"run artifact tick {layer} states are missing")
        if not isinstance(tick["l3"], dict):
            raise ValueError("run artifact tick l3 state is missing")
        observed = tick["l4_observed"]
        if (tick["l4"] is not None) != bool(observed):
            raise ValueError("run artifact l4 observation flag is inconsistent")
        if not isinstance(tick["transitions"], list):
            raise ValueError("run artifact tick transitions are missing")
    if tuple(times) != tuple(range(1, end + 1)):
        raise ValueError("run artifact tick times are incomplete or unordered")
    if history_digest(run) != run["history_digest"]:
        raise ValueError("run artifact history hash chain is invalid")
    checkpoint = dict(run["checkpoint"])
    checkpoint_id = checkpoint.pop("checkpoint_id", None)
    expected_checkpoint_id = f"checkpoint-{digest_payload(checkpoint)[:16]}"
    if (
        checkpoint_id != expected_checkpoint_id
        or run["checkpoint_id"] != expected_checkpoint_id
        or checkpoint["history_digest"] != run["history_digest"]
    ):
        raise ValueError("run artifact checkpoint identity is invalid")
    return run


def _mean_series(
    run: Mapping[str, Any], layer: str, fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    rows = []
    for tick in run["ticks"]:
        states = tick[layer]
        row: dict[str, Any] = {"tick": tick["logical_time"]}
        for field in fields:
            row[field] = fmean(state[field] for state in states)
        rows.append(row)
    return rows


def _phase_rows(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for tick in run["ticks"]:
        states = tick["l2"]
        row: dict[str, Any] = {"tick": tick["logical_time"]}
        for phase in CellPhase:
            row[f"phase_{phase.value}"] = sum(
                1 for state in states if state["phase"] == phase.value
            )
        rows.append(row)
    return rows


def _l3_rows(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "tick": tick["logical_time"],
            **{field: tick["l3"][field] for field in L3_FIELDS},
        }
        for tick in run["ticks"]
    ]


def _l4_rows(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "tick": tick["logical_time"],
            **{field: tick["l4"][field] for field in L4_FIELDS},
        }
        for tick in run["ticks"]
        if tick["l4"] is not None
    ]


def _series_chart(
    *,
    title: str,
    subtitle: str,
    description: str,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    y_max: float = 1.0,
) -> str:
    width, height = 1060, 520
    left, right, top, bottom = 80, 40, 118, 70
    plot_width = width - left - right
    plot_height = height - top - bottom
    first_tick = rows[0]["tick"]
    last_tick = rows[-1]["tick"]
    span = max(1, last_tick - first_tick)

    def x(tick: int) -> float:
        return left + (tick - first_tick) / span * plot_width

    def y(value: float) -> float:
        clamped = min(y_max, max(0.0, value))
        return top + (1.0 - clamped / y_max) * plot_height

    parts = [
        f'<text class="title" x="20" y="32">{title}</text>',
        f'<text class="subtitle" x="20" y="55">{subtitle}</text>',
    ]
    for index, field in enumerate(fields):
        legend_x = 80 + index * 155
        parts.append(
            f'<circle cx="{legend_x}" cy="86" r="5" fill="{COLORS[index % len(COLORS)]}"/>'
            f'<text x="{legend_x + 10}" y="90">{field}</text>'
        )
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        py = y(fraction * y_max)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{width - right}" y2="{py:.2f}"/>'
            f'<text x="{left - 10}" y="{py + 4:.2f}" text-anchor="end">{label(fraction * y_max)}</text>'
        )
    tick_marks = sorted(
        {first_tick, last_tick}
        | {
            round(first_tick + span * fraction)
            for fraction in (0.2, 0.4, 0.6, 0.8)
        }
    )
    for tick in tick_marks:
        parts.append(
            f'<text x="{x(tick):.2f}" y="{height - bottom + 24}" text-anchor="middle">{tick}</text>'
        )
    for index, field in enumerate(fields):
        points = " ".join(
            f"{x(row['tick']):.2f},{y(row[field]):.2f}" for row in rows
        )
        first = label(rows[0][field])
        last = label(rows[-1][field])
        parts.append(
            f'<polyline points="{points}" fill="none" '
            f'stroke="{COLORS[index % len(COLORS)]}" stroke-width="2.5">'
            f"<title>{field}: first={first}, last={last}</title></polyline>"
        )
    parts.extend(
        (
            f'<line class="axis" x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"/>',
            f'<text x="{left + plot_width / 2:.2f}" y="{height - 20}" text-anchor="middle">logical tick</text>',
        )
    )
    return svg_document(
        width=width,
        height=height,
        title=title,
        description=description,
        body="\n".join(parts),
    )


def _report_html(
    run: Mapping[str, Any], cell_count: int, chart_rows: Mapping[str, int]
) -> str:
    experiment = run["experiment"]
    window = run["phenotype_window"]
    model_rows = "".join(
        f"<tr><td>{html.escape(layer)}</td><td><code>{html.escape(str(version))}</code></td></tr>"
        for layer, version in sorted(experiment["model_versions"].items())
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M-GBA run trajectory report</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 24px; line-height: 1.5; }}
h1, h2 {{ font-weight: 600; }}
.boundary {{ border-left: 4px solid #ca8a04; padding-left: 12px; }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); padding: 8px; text-align: left; }}
figure {{ margin: 28px 0; }}
img {{ width: 100%; height: auto; }}
figcaption {{ color: color-mix(in srgb, currentColor 70%, transparent); }}
code {{ font-family: ui-monospace, monospace; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<h1>M-GBA run trajectory report</h1>
<p><strong>Experiment:</strong> <code>{html.escape(experiment["experiment_id"])}</code> · <strong>name:</strong> {html.escape(experiment["experiment_name"])} · <strong>seed:</strong> {experiment["seed"]} · <strong>code:</strong> <code>{html.escape(experiment["code_version"])}</code></p>
<p><strong>Ticks:</strong> {run["start_tick"]}–{run["end_tick"]} · <strong>cells:</strong> {cell_count} · <strong>outcome:</strong> {html.escape(str(window["outcome"]))} · <strong>history digest:</strong> <code>{html.escape(run["history_digest"])}</code></p>
<p><strong>Model status:</strong> {html.escape(str(run["model_status"]))}</p>
<p class="boundary">All quantities are dimensionless reference-model proxies, not biological or clinical measurements. L0–L3 series are per-tick means across {cell_count} cells, so single-cell heterogeneity is only visible in the raw artifact. L4 is observed on the slow clock; only scheduled observation ticks are charted. This page is read-only and contains no simulation controls or network dependencies.</p>
<h2>Model versions</h2>
<table>
<thead><tr><th>Layer</th><th>Model version</th></tr></thead>
<tbody>{model_rows}</tbody>
</table>
<h2>Layer trajectories</h2>
<figure><img src="l0-gene-expression.svg" alt="L0 abstract gene expression over ticks"><figcaption>L0 abstract gene expression, mean across cells. These are abstract regulatory variables, not real DNA.</figcaption></figure>
<figure><img src="l1-molecular-state.svg" alt="L1 molecular state over ticks"><figcaption>L1 coarse molecular species, mean across cells. Coarse-grained proxies, not all-atom dynamics.</figcaption></figure>
<figure><img src="l2-cell-state.svg" alt="L2 cell state means over ticks"><figcaption>L2 cell viability, activation, and stress load, mean across cells.</figcaption></figure>
<figure><img src="l2-phase-counts.svg" alt="L2 cell phase counts over ticks"><figcaption>L2 five-state phase counts; every tick sums to {cell_count} cells.</figcaption></figure>
<figure><img src="l3-tissue-fields.svg" alt="L3 tissue fields over ticks"><figcaption>L3 local environment and tissue fields on the fixed reference graph.</figcaption></figure>
<figure><img src="l4-phenotype.svg" alt="L4 phenotype observations"><figcaption>L4 macroscopic phenotype at scheduled observations only ({chart_rows["l4"]} of {run["tick_count"]} ticks).</figcaption></figure>
<h2>Rebuildable data</h2>
<p>The tables behind these figures are <a href="l0-gene-expression.csv">l0-gene-expression.csv</a>, <a href="l1-molecular-state.csv">l1-molecular-state.csv</a>, <a href="l2-cell-state.csv">l2-cell-state.csv</a>, <a href="l2-phase-counts.csv">l2-phase-counts.csv</a>, <a href="l3-tissue-fields.csv">l3-tissue-fields.csv</a>, and <a href="l4-phenotype.csv">l4-phenotype.csv</a>. Every file plus this page is listed with its SHA-256 in <a href="run-report-manifest.json">run-report-manifest.json</a>.</p>
</body>
</html>
"""


def build_run_report(
    run_path: str | Path, output_dir: str | Path | None = None
) -> RunReportPaths:
    source = Path(run_path).resolve()
    if not source.is_file():
        raise ValueError(f"run artifact does not exist: {source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"run artifact is not readable JSON: {source}") from error
    run = _validate_run_document(raw)
    if output_dir is not None:
        output = Path(output_dir).resolve()
    else:
        output = source.with_name(f"{source.stem}-report")
        if "raw" in output.parts:
            raise ValueError(
                "refusing to write a derived report inside a raw artifact directory; "
                "pass --output-dir explicitly"
            )
    output.mkdir(parents=True, exist_ok=True)
    paths = RunReportPaths(
        root=output,
        manifest=output / "run-report-manifest.json",
        l0_csv=output / "l0-gene-expression.csv",
        l1_csv=output / "l1-molecular-state.csv",
        l2_csv=output / "l2-cell-state.csv",
        l2_phase_csv=output / "l2-phase-counts.csv",
        l3_csv=output / "l3-tissue-fields.csv",
        l4_csv=output / "l4-phenotype.csv",
        l0_chart=output / "l0-gene-expression.svg",
        l1_chart=output / "l1-molecular-state.svg",
        l2_chart=output / "l2-cell-state.svg",
        l2_phase_chart=output / "l2-phase-counts.svg",
        l3_chart=output / "l3-tissue-fields.svg",
        l4_chart=output / "l4-phenotype.svg",
        html=output / "run-report.html",
    )
    l0_rows = _mean_series(run, "l0", L0_FIELDS)
    l1_rows = _mean_series(run, "l1", L1_FIELDS)
    l2_rows = _mean_series(run, "l2", L2_FIELDS)
    phase_rows = _phase_rows(run)
    l3_rows = _l3_rows(run)
    l4_rows = _l4_rows(run)
    cell_count = len(run["ticks"][0]["l2"])
    write_csv(paths.l0_csv, ("tick", *L0_FIELDS), l0_rows)
    write_csv(paths.l1_csv, ("tick", *L1_FIELDS), l1_rows)
    write_csv(paths.l2_csv, ("tick", *L2_FIELDS), l2_rows)
    write_csv(
        paths.l2_phase_csv,
        ("tick", *(f"phase_{phase.value}" for phase in CellPhase)),
        phase_rows,
    )
    write_csv(paths.l3_csv, ("tick", *L3_FIELDS), l3_rows)
    write_csv(paths.l4_csv, ("tick", *L4_FIELDS), l4_rows)
    paths.l0_chart.write_text(
        _series_chart(
            title="L0 abstract gene expression",
            subtitle="Mean across cells; abstract regulatory variables, not real DNA",
            description="Line chart of six mean L0 gene expression series over logical ticks.",
            rows=l0_rows,
            fields=L0_FIELDS,
        ),
        encoding="utf-8",
    )
    paths.l1_chart.write_text(
        _series_chart(
            title="L1 molecular state",
            subtitle="Mean across cells; coarse-grained proxies, not all-atom dynamics",
            description="Line chart of six mean L1 molecular species over logical ticks.",
            rows=l1_rows,
            fields=L1_FIELDS,
        ),
        encoding="utf-8",
    )
    paths.l2_chart.write_text(
        _series_chart(
            title="L2 cell state",
            subtitle="Mean across cells",
            description="Line chart of mean L2 viability, activation, and stress load over logical ticks.",
            rows=l2_rows,
            fields=L2_FIELDS,
        ),
        encoding="utf-8",
    )
    paths.l2_phase_chart.write_text(
        _series_chart(
            title="L2 cell phase counts",
            subtitle=f"Five-state counts; every tick sums to {cell_count} cells",
            description="Line chart of L2 phase counts over logical ticks.",
            rows=phase_rows,
            fields=tuple(f"phase_{phase.value}" for phase in CellPhase),
            y_max=float(cell_count),
        ),
        encoding="utf-8",
    )
    paths.l3_chart.write_text(
        _series_chart(
            title="L3 tissue fields",
            subtitle="Local environment fields on the fixed reference graph",
            description="Line chart of six L3 tissue field series over logical ticks.",
            rows=l3_rows,
            fields=L3_FIELDS,
        ),
        encoding="utf-8",
    )
    paths.l4_chart.write_text(
        _series_chart(
            title="L4 phenotype observations",
            subtitle="Scheduled slow-clock observations only",
            description="Line chart of five L4 phenotype metrics at scheduled observation ticks.",
            rows=l4_rows,
            fields=L4_FIELDS,
        ),
        encoding="utf-8",
    )
    paths.html.write_text(
        _report_html(run, cell_count, {"l4": len(l4_rows)}), encoding="utf-8"
    )
    manifest_payload = {
        "schema_version": _RUN_REPORT_SCHEMA,
        "experiment_id": run["experiment"]["experiment_id"],
        "history_digest": run["history_digest"],
        "source_run_file": source.name,
        "source_run_sha256": file_sha256(source),
        "files": {
            path.name: file_sha256(path)
            for path in sorted(paths.generated_files, key=lambda item: item.name)
        },
    }
    paths.manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return paths
