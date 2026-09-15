"""Read-only unified evidence overview report across all saved artifacts.

ADR-0050: this module is experiment-observation infrastructure outside the
generation chain. It scans nine enumerated evidence sources under the
artifact root (plus the data registry), normalizes them into a single
``mgba-evidence-report-0.1`` model, and renders a static Chinese HTML page
with inline SVG charts, per-section CSV tables, and a SHA-256 manifest.
It never imports or calls any L0--L4 model, never re-runs any experiment,
and never modifies its inputs. Missing sources degrade to an explicit
"未生成" section instead of failing the build. ``--verify`` rebuilds the
report into a temporary directory and byte-compares every generated file.

Pipeline (frozen): collect -> normalize -> render -> manifest -> verify.
"""

from __future__ import annotations

import html
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

from .hashing import digest_payload
from .reporting import COLORS, label, svg_document, write_csv
from .validation import file_sha256

EVIDENCE_SCHEMA = "mgba-evidence-report-0.1"
MANIFEST_SCHEMA = "mgba-evidence-report-manifest-0.1"

REPORT_BOUNDARY = (
    "本报告是生成链外的只读观察层：只读取既有 artifact 与登记表，不重跑任何实验，"
    "不改变任何历史 verdict 或证据等级。所有数值逐字来自来源 artifact；"
    "负面结果（failed / criteria_not_met / No-Go / 未锚定）原样显著标注。"
)

_EVIDENCE_LEVELS = {
    "training-evaluation": "reference model（离线训练评估）",
    "extrapolation-boundary": "确认性边界判决（failed）",
    "falsification-controls": "阴性对照（证伪对照组）",
    "effect-robustness": "探索性诊断（非确认性结论）",
    "wp8-matrix": "reference model（WP8 冻结矩阵）",
    "carm-intervention": "reference model（reference-rule trade-off）",
    "spatial-anchor": "reference model（描述性对照，未锚定）",
    "bridge-coverage": "只读审计",
    "data-registry": "登记状态总览",
}

SECTION_ORDER = (
    ("training-evaluation", "训练评估"),
    ("extrapolation-boundary", "外推边界"),
    ("falsification-controls", "证伪对照"),
    ("effect-robustness", "效应稳健性"),
    ("wp8-matrix", "WP8 矩阵"),
    ("carm-intervention", "CAR-M 干预"),
    ("spatial-anchor", "空间锚定"),
    ("bridge-coverage", "桥覆盖"),
    ("data-registry", "数据登记"),
)

_EVAL_DISPLAY_NAMES = {
    "aivc-l0-training-evaluation": "OE 主评估（Norman CRISPRa）",
    "aivc-replogle-kd-training-evaluation": "KD 主评估（Replogle CRISPRi）",
    "aivc-replogle-kd-hallmark-training-evaluation": "KD Hallmark 结构化目标",
    "aivc-norman-hallmark-training-evaluation": "OE Hallmark 结构化目标",
}

_EXPERIMENT_DISPLAY_NAMES = {
    "mvp-demo": "WP8 矩阵",
    "carm-intervention": "CAR-M 干预",
    "empirical-l0": "实证 L0",
}

_FIELD_DISPLAY_NAMES = {
    "activation": "活化",
    "stress_load": "压力负荷",
    "viability": "存活度",
}
_FIELD_ORDER = ("activation", "stress_load", "viability")

_L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)
_LAYER_ORDER = ("L0", "L1", "L2", "L3", "L4")
_ROLE_ORDER = ("calibration", "holdout", "external_validation")
_ROLE_DISPLAY = {
    "calibration": "calibration（标定）",
    "holdout": "holdout（留出）",
    "external_validation": "external validation（外部验证）",
}

_OK = COLORS[2]
_BAD = COLORS[3]
_WARN = COLORS[6]


@dataclass(frozen=True, slots=True)
class _Input:
    input_id: str
    display_path: str
    status: str  # "present" | "missing" | "unreadable" | "schema-mismatch"
    sha256: str | None
    schema_version: str | None
    payload: dict[str, Any] | None
    note: str | None

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "path": self.display_path,
            "status": self.status,
            "sha256": self.sha256,
            "schema_version": self.schema_version,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class _Section:
    section_id: str
    title: str
    evidence_level: str
    status: str  # "present" | "missing"
    source_paths: tuple[str, ...]
    findings: dict[str, Any]
    notes: tuple[str, ...]
    svg_name: str | None
    svg: str | None
    csv_name: str | None
    csv_fields: tuple[str, ...] | None
    csv_rows: tuple[dict[str, Any], ...] | None
    html_table: str | None

    def model(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "evidence_level": self.evidence_level,
            "status": self.status,
            "source_paths": list(self.source_paths),
            "findings": self.findings,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class EvidenceReportPaths:
    root: Path
    manifest: Path
    summary: Path
    html: Path
    section_files: tuple[Path, ...]

    @property
    def generated_files(self) -> tuple[Path, ...]:
        return (*self.section_files, self.html, self.summary)


# ---------------------------------------------------------------------------
# collect


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _load_input(
    input_id: str,
    path: Path,
    project_root: Path,
    expected_schemas: tuple[str, ...],
) -> _Input:
    display = _display_path(path, project_root)
    if not path.is_file():
        return _Input(input_id, display, "missing", None, None, None, "未生成")
    digest = file_sha256(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _Input(
            input_id, display, "unreadable", digest, None, None,
            "文件存在但无法解析为 JSON",
        )
    if not isinstance(payload, dict):
        return _Input(
            input_id, display, "unreadable", digest, None, None,
            "JSON 根不是对象",
        )
    schema = payload.get("schema_version")
    if schema not in expected_schemas:
        return _Input(
            input_id, display, "schema-mismatch", digest,
            str(schema) if schema is not None else None, None,
            f"schema_version 与冻结枚举不符（期望 {'/'.join(expected_schemas)}）",
        )
    return _Input(input_id, display, "present", digest, str(schema), payload, None)


def _collect(
    artifact_root: Path, project_root: Path, registry_path: Path
) -> dict[str, list[_Input]]:
    inputs: dict[str, list[_Input]] = {}

    registry = _load_input(
        "data-registry",
        registry_path,
        project_root,
        ("mgba-data-registry-0.1", "mgba-data-registry-0.2"),
    )
    inputs["data-registry"] = [registry]

    evaluation_inputs: list[_Input] = []
    if registry.payload is not None:
        datasets = registry.payload.get("datasets")
        if isinstance(datasets, list):
            for entry in datasets:
                if not isinstance(entry, dict):
                    continue
                dataset_id = str(entry.get("dataset_id", ""))
                if not (
                    dataset_id.startswith("aivc-")
                    and "training-evaluation" in dataset_id
                ):
                    continue
                rel = entry.get("path")
                if not isinstance(rel, str) or not rel:
                    continue
                evaluation_inputs.append(
                    _load_input(
                        f"training-evaluation:{dataset_id}",
                        project_root / rel,
                        project_root,
                        (
                            "mgba-l0-training-evaluation-0.1",
                            "mgba-l0-hallmark-training-evaluation-0.1",
                        ),
                    )
                )
    inputs["training-evaluation"] = evaluation_inputs

    inputs["extrapolation-boundary"] = [
        _load_input(
            "extrapolation-boundary",
            artifact_root / "extrapolation-boundary" / "results.json",
            project_root,
            ("mgba-extrapolation-boundary-0.1",),
        )
    ]

    falsification_root = artifact_root / "falsification"
    falsification_inputs: list[_Input] = []
    if falsification_root.is_dir():
        for child in sorted(falsification_root.iterdir(), key=lambda p: p.name):
            results = child / "results.json"
            if child.is_dir() and results.is_file():
                falsification_inputs.append(
                    _load_input(
                        f"falsification:{child.name}",
                        results,
                        project_root,
                        ("mgba-falsification-control-0.1",),
                    )
                )
    if not falsification_inputs:
        falsification_inputs.append(
            _Input(
                "falsification",
                _display_path(falsification_root, project_root),
                "missing",
                None,
                None,
                None,
                "未生成",
            )
        )
    inputs["falsification-controls"] = falsification_inputs

    robustness_root = artifact_root / "exploratory" / "effect-robustness-2026-09-11"
    robustness_inputs = [
        _load_input(
            "effect-robustness:summary",
            robustness_root / "summary.json",
            project_root,
            ("mgba-exploratory-effect-robustness-0.1",),
        )
    ]
    if robustness_root.is_dir():
        for detail in sorted(
            robustness_root.glob("detail-*.json"), key=lambda p: p.name
        ):
            robustness_inputs.append(
                _load_input(
                    f"effect-robustness:{detail.name}",
                    detail,
                    project_root,
                    ("mgba-exploratory-effect-robustness-0.1",),
                )
            )
    inputs["effect-robustness"] = robustness_inputs

    inputs["wp8-matrix"] = [
        _load_input(
            "wp8-matrix",
            artifact_root
            / "mvp-demo"
            / "matrix-7da4137aa39d5122"
            / "derived"
            / "summary.json",
            project_root,
            ("mgba-causal-matrix-0.1",),
        )
    ]

    inputs["carm-intervention"] = [
        _load_input(
            "carm-intervention",
            artifact_root
            / "carm-state-conditioned-intervention"
            / "state-intervention-0e92bb234ba3a840"
            / "derived"
            / "summary.json",
            project_root,
            ("mgba-state-conditioned-intervention-result-0.1",),
        )
    ]

    spatial_root = artifact_root / "carm-spatial-anchor"
    spatial_inputs: list[_Input] = []
    if spatial_root.is_dir():
        for child in sorted(spatial_root.iterdir(), key=lambda p: p.name):
            summary = child / "derived" / "summary.json"
            if child.is_dir() and summary.is_file():
                spatial_inputs.append(
                    _load_input(
                        f"spatial-anchor:{child.name}",
                        summary,
                        project_root,
                        ("mgba-carm-spatial-anchor-evaluation-0.1",),
                    )
                )
                break
    if not spatial_inputs:
        spatial_inputs.append(
            _Input(
                "spatial-anchor",
                _display_path(spatial_root, project_root),
                "missing",
                None,
                None,
                None,
                "未生成",
            )
        )
    inputs["spatial-anchor"] = spatial_inputs

    inputs["bridge-coverage"] = [
        _load_input(
            "bridge-coverage",
            artifact_root / "audit" / "bridge-coverage-2026-09-11" / "audit.json",
            project_root,
            ("mgba-bridge-coverage-audit-0.1",),
        )
    ]

    return inputs


# ---------------------------------------------------------------------------
# shared render helpers


def _verdict_class(verdict: str) -> str:
    if verdict in ("passed", "criteria_met"):
        return "ok"
    if verdict in ("failed", "criteria_not_met"):
        return "bad"
    return "warn"


def _grouped_bar_svg(
    *,
    title: str,
    subtitle: str,
    description: str,
    groups: tuple[str, ...],
    series: tuple[str, ...],
    values: Mapping[tuple[str, str], float],
    log_scale: bool = False,
    annotations: Mapping[str, tuple[str, str]] | None = None,
    y_label: str = "",
    floor: float = 1e-5,
) -> str:
    width, height = 1060, 520
    left, right, top, bottom = 90, 40, 118, 96
    plot_width = width - left - right
    plot_height = height - top - bottom
    plot_bottom = height - bottom
    peak = max(max(values.values()), floor * 10)

    if log_scale:
        low = math.log10(floor)
        high = math.ceil(math.log10(peak))

        def y(value: float) -> float:
            clamped = max(value, floor)
            fraction = (math.log10(clamped) - low) / (high - low)
            return plot_bottom - fraction * plot_height

        ticks = [10.0**power for power in range(int(low), int(high) + 1)]
    else:
        high_lin = peak * 1.15

        def y(value: float) -> float:
            return plot_bottom - (value / high_lin) * plot_height

        ticks = [high_lin * step / 4 for step in range(5)]

    parts = [
        f'<text class="title" x="20" y="32">{html.escape(title)}</text>',
        f'<text class="subtitle" x="20" y="55">{html.escape(subtitle)}</text>',
    ]
    for index, name in enumerate(series):
        legend_x = 90 + index * 190
        parts.append(
            f'<rect x="{legend_x}" y="72" width="12" height="12" fill="{COLORS[index % len(COLORS)]}"/>'
            f'<text x="{legend_x + 18}" y="82">{html.escape(name)}</text>'
        )
    for tick in ticks:
        py = y(tick)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{width - right}" y2="{py:.2f}"/>'
            f'<text x="{left - 10}" y="{py + 4:.2f}" text-anchor="end">{label(tick)}</text>'
        )
    slot = plot_width / len(groups)
    bar_width = slot * 0.72 / len(series)
    for group_index, group in enumerate(groups):
        base_x = left + group_index * slot + slot * 0.14
        for series_index, name in enumerate(series):
            value = values[(group, name)]
            px = base_x + series_index * bar_width
            py = y(value)
            parts.append(
                f'<rect x="{px:.2f}" y="{py:.2f}" width="{bar_width * 0.9:.2f}" '
                f'height="{plot_bottom - py:.2f}" fill="{COLORS[series_index % len(COLORS)]}">'
                f"<title>{html.escape(group)} {html.escape(name)}: {label(value)}</title></rect>"
                f'<text x="{px + bar_width * 0.45:.2f}" y="{py - 4:.2f}" '
                f'text-anchor="middle" font-size="10">{label(value)}</text>'
            )
        parts.append(
            f'<text x="{left + group_index * slot + slot / 2:.2f}" y="{plot_bottom + 20}" '
            f'text-anchor="middle">{html.escape(group)}</text>'
        )
        if annotations and group in annotations:
            text, klass = annotations[group]
            color = {"ok": _OK, "bad": _BAD, "warn": _WARN}[klass]
            parts.append(
                f'<text x="{left + group_index * slot + slot / 2:.2f}" y="{plot_bottom + 40}" '
                f'text-anchor="middle" font-weight="600" fill="{color}">{html.escape(text)}</text>'
            )
    parts.append(
        f'<line class="axis" x1="{left}" y1="{plot_bottom}" x2="{width - right}" y2="{plot_bottom}"/>'
    )
    if y_label:
        parts.append(
            f'<text transform="translate(24 {top + plot_height / 2:.2f}) rotate(-90)" '
            f'text-anchor="middle">{html.escape(y_label)}</text>'
        )
    return svg_document(
        width=width, height=height, title=title, description=description,
        body="\n".join(parts),
    )


# ---------------------------------------------------------------------------
# normalize + render per section


def _missing_section(section_id: str, title: str, inputs: list[_Input]) -> _Section:
    notes = tuple(
        f"{item.display_path}：{item.note or item.status}" for item in inputs
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="missing",
        source_paths=tuple(item.display_path for item in inputs),
        findings={},
        notes=notes or ("未生成",),
        svg_name=None,
        svg=None,
        csv_name=None,
        csv_fields=None,
        csv_rows=None,
        html_table=None,
    )


def _section_training(inputs: list[_Input]) -> _Section:
    section_id, title = "training-evaluation", "训练评估"
    usable = [item for item in inputs if item.payload is not None]
    if not usable:
        return _missing_section(section_id, title, inputs)
    findings_list: list[dict[str, Any]] = []
    for item in usable:
        payload = item.payload
        assert payload is not None
        dataset_id = item.input_id.split(":", 1)[1]
        pass_rule = payload.get("pass_rule", {})
        if payload["schema_version"] == "mgba-l0-hallmark-training-evaluation-0.1":
            holdout = payload["metrics"]["six_node_head"]["holdout"]
            mae_scope = "六节点头 MAE（56 维 Hallmark 结构化目标）"
            maes = {model: holdout[model]["mae"] for model in ("centroid", "ridge", "mlp")}
        else:
            holdout = payload["metrics"]["holdout"]
            mae_scope = "六节点 MAE"
            maes = {
                model: holdout[model]["six_node_mae"]
                for model in ("centroid", "ridge", "mlp")
            }
        findings_list.append(
            {
                "dataset_id": dataset_id,
                "display_name": _EVAL_DISPLAY_NAMES.get(dataset_id, dataset_id),
                "evaluation_id": payload.get("evaluation_id"),
                "verdict": pass_rule.get("verdict"),
                "mae_scope": mae_scope,
                "holdout_mae": maes,
                "margin_vs_centroid": pass_rule.get("margin_vs_centroid"),
                "margin_vs_ridge": pass_rule.get("margin_vs_ridge"),
                "holdout_units": holdout["mlp"].get("unit_count"),
                "source_path": item.display_path,
            }
        )
    groups = tuple(item["display_name"] for item in findings_list)
    series = ("centroid（质心）", "ridge（岭回归）", "mlp（MLP）")
    series_keys = ("centroid", "ridge", "mlp")
    values = {
        (item["display_name"], display): item["holdout_mae"][key]
        for item in findings_list
        for display, key in zip(series, series_keys, strict=True)
    }
    annotations = {
        item["display_name"]: (
            f"verdict = {item['verdict']}",
            _verdict_class(str(item["verdict"])),
        )
        for item in findings_list
    }
    svg = _grouped_bar_svg(
        title="L0 训练评估 holdout MAE 对比",
        subtitle="每个评估的三模型 holdout MAE（越低越好）；标注为冻结通过规则 verdict",
        description="Grouped bar chart of holdout MAE for centroid, ridge and MLP across four frozen training evaluations.",
        groups=groups,
        series=series,
        values=values,
        annotations=annotations,
        y_label="holdout MAE",
    )
    rows = [
        {
            "dataset_id": item["dataset_id"],
            "evaluation_id": item["evaluation_id"],
            "verdict": item["verdict"],
            "mae_scope": item["mae_scope"],
            "holdout_units": item["holdout_units"],
            "holdout_mae_centroid": item["holdout_mae"]["centroid"],
            "holdout_mae_ridge": item["holdout_mae"]["ridge"],
            "holdout_mae_mlp": item["holdout_mae"]["mlp"],
            "margin_vs_centroid": item["margin_vs_centroid"],
            "margin_vs_ridge": item["margin_vs_ridge"],
        }
        for item in findings_list
    ]
    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['display_name'])}</td>"
        f"<td class=\"{_verdict_class(str(item['verdict']))}\">{html.escape(str(item['verdict']))}</td>"
        f"<td>{html.escape(item['mae_scope'])}</td>"
        f"<td>{label(item['holdout_mae']['centroid'])}</td>"
        f"<td>{label(item['holdout_mae']['ridge'])}</td>"
        f"<td>{label(item['holdout_mae']['mlp'])}</td>"
        f"<td>{label(item['margin_vs_centroid'])}</td>"
        f"<td>{label(item['margin_vs_ridge'])}</td>"
        "</tr>"
        for item in findings_list
    )
    table = (
        "<table><thead><tr><th>评估</th><th>verdict</th><th>MAE 口径</th>"
        "<th>质心 MAE</th><th>ridge MAE</th><th>MLP MAE</th>"
        "<th>margin vs 质心</th><th>margin vs ridge</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table>"
    )
    notes = tuple(
        f"{item['display_name']}：{item['mae_scope']}，holdout {item['holdout_units']} 单元；"
        f"通过规则 = MLP 同时严格优于质心与 ridge（margin > 1e-12）。"
        for item in findings_list
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=tuple(item.display_path for item in usable),
        findings={"evaluations": findings_list},
        notes=notes,
        svg_name="training-evaluation.svg",
        svg=svg,
        csv_name="training-evaluation.csv",
        csv_fields=(
            "dataset_id",
            "evaluation_id",
            "verdict",
            "mae_scope",
            "holdout_units",
            "holdout_mae_centroid",
            "holdout_mae_ridge",
            "holdout_mae_mlp",
            "margin_vs_centroid",
            "margin_vs_ridge",
        ),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _section_extrapolation(inputs: list[_Input]) -> _Section:
    section_id, title = "extrapolation-boundary", "外推边界"
    item = inputs[0]
    if item.payload is None:
        return _missing_section(section_id, title, inputs)
    payload = item.payload
    strata = payload["strata"]
    verdict = str(payload.get("verdict"))
    stratum_ids = ("component-seen", "component-unseen")
    rows = []
    for stratum_id in stratum_ids:
        entry = strata[stratum_id]
        rows.append(
            {
                "stratum": stratum_id,
                "units": entry["units"],
                "mae_centroid": entry["mae"]["centroid"],
                "mae_ridge": entry["mae"]["ridge"],
                "mae_mlp": entry["mae"]["mlp"],
                "margin_vs_centroid": entry["margin_vs_centroid"],
                "margin_vs_ridge": entry["margin_vs_ridge"],
            }
        )
    groups = tuple(f"{row['stratum']}（{row['units']} 单元）" for row in rows)
    series = ("centroid（质心）", "ridge（岭回归）", "mlp（MLP）")
    series_keys = ("mae_centroid", "mae_ridge", "mae_mlp")
    values = {
        (group, display): row[key]
        for group, row in zip(groups, rows, strict=True)
        for display, key in zip(series, series_keys, strict=True)
    }
    svg = _grouped_bar_svg(
        title="OE 成分外推边界：两层三模型 MAE",
        subtitle=f"component-seen（插值层）vs component-unseen（外推层）；判据 verdict = {verdict}（ADR-0049）",
        description="Grouped bar chart comparing centroid, ridge and MLP MAE on component-seen and component-unseen holdout strata.",
        groups=groups,
        series=series,
        values=values,
        y_label="六节点 MAE",
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['stratum'])}</td>"
        f"<td>{row['units']}</td>"
        f"<td>{label(row['mae_centroid'])}</td>"
        f"<td>{label(row['mae_ridge'])}</td>"
        f"<td>{label(row['mae_mlp'])}</td>"
        f"<td>{label(row['margin_vs_centroid'])}</td>"
        f"<td>{label(row['margin_vs_ridge'])}</td>"
        "</tr>"
        for row in rows
    )
    table = (
        "<table><thead><tr><th>分层</th><th>单元数</th><th>质心 MAE</th>"
        "<th>ridge MAE</th><th>MLP MAE</th><th>margin vs 质心</th>"
        "<th>margin vs ridge</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table>"
    )
    unseen = rows[1]
    notes = (
        f"判据（预注册）：component-unseen 层 MLP 同时严格优于质心与 ridge → passed，否则 failed；实际 verdict = {verdict}。",
        f"外推层 margin：对质心 {label(unseen['margin_vs_centroid'])}、对 ridge {label(unseen['margin_vs_ridge'])}；"
        "双胜不成立，OE 外推方向已按 ADR-0049 §4 正式关闭。",
        f"对照锚核验：anchor_check_passed = {payload['anchors'].get('anchor_check_passed')}。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=(item.display_path,),
        findings={
            "verdict": verdict,
            "strata": rows,
            "anchor_check_passed": payload["anchors"].get("anchor_check_passed"),
        },
        notes=notes,
        svg_name="extrapolation-boundary.svg",
        svg=svg,
        csv_name="extrapolation-boundary.csv",
        csv_fields=(
            "stratum",
            "units",
            "mae_centroid",
            "mae_ridge",
            "mae_mlp",
            "margin_vs_centroid",
            "margin_vs_ridge",
        ),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _falsification_headline(control_id: str, results: Mapping[str, Any]) -> dict[str, Any]:
    if control_id == "label-shuffle":
        return {
            "打乱后 margin（对质心）": results.get("margin_vs_centroid"),
            "打乱后 margin（对 ridge）": results.get("margin_vs_ridge"),
            "ADR-0037 通过规则在打乱数据上仍成立": results.get(
                "adr0037_pass_rule_holds_on_shuffled"
            ),
        }
    if control_id == "layer-permutation":
        return {
            "C2-1 供体保真通过": results.get("c2_1_donor_fidelity", {}).get("passed"),
            "C2-2 真实库排除通过": results.get("c2_2_library_exclusion", {}).get("passed"),
            "传播 tick 碰撞率": results.get("c2_3_tick_collisions", {}).get("collision_rate"),
            "C2-3 解释带": results.get("c2_3_tick_collisions", {}).get("band"),
        }
    if control_id == "target-permutation":
        return {
            "真实总均值 NAE": results.get("real_overall_mean_nae"),
            "置换总均值 NAE": results.get("permuted_overall_mean_nae"),
            "真实 holdout NAE": results.get("real_role_mean_nae", {}).get("holdout"),
            "置换 holdout NAE": results.get("permuted_role_mean_nae", {}).get("holdout"),
            "置换全面更差": results.get("overall_worse"),
        }
    return {}


def _section_falsification(inputs: list[_Input]) -> _Section:
    section_id, title = "falsification-controls", "证伪对照"
    usable = [item for item in inputs if item.payload is not None]
    if not usable:
        return _missing_section(section_id, title, inputs)
    controls: list[dict[str, Any]] = []
    for item in usable:
        payload = item.payload
        assert payload is not None
        control_id = str(payload.get("control_id"))
        controls.append(
            {
                "control_id": control_id,
                "verdict": payload.get("verdict"),
                "adr": payload.get("adr"),
                "headline": _falsification_headline(
                    control_id, payload.get("results", {})
                ),
                "source_path": item.display_path,
            }
        )
    width = 1060
    row_height = 84
    top = 96
    height = top + row_height * len(controls) + 40
    parts = [
        '<text class="title" x="20" y="32">管线证伪对照（ADR-0048）</text>',
        '<text class="subtitle" x="20" y="55">三组阴性对照的预注册判据 verdict；红色 = 判据不成立（负面结果原样标注）</text>',
    ]
    for index, control in enumerate(controls):
        cy = top + index * row_height
        verdict = str(control["verdict"])
        color = _OK if verdict == "criteria_met" else _BAD
        headline_text = "；".join(
            f"{key} = {label(value) if isinstance(value, float) else value}"
            for key, value in control["headline"].items()
        )
        parts.extend(
            (
                f'<text x="20" y="{cy + 18}">{html.escape(control["control_id"])}</text>',
                f'<rect x="220" y="{cy}" width="180" height="30" fill="{color}"/>',
                f'<text x="310" y="{cy + 20}" text-anchor="middle" fill="#ffffff" font-weight="600">{html.escape(verdict)}</text>',
                f'<text x="420" y="{cy + 20}">{html.escape(headline_text)}</text>',
            )
        )
    svg = svg_document(
        width=width,
        height=height,
        title="管线证伪对照 verdict 总览",
        description="Color block table of the three ADR-0048 falsification control verdicts.",
        body="\n".join(parts),
    )
    rows = [
        {
            "control_id": control["control_id"],
            "verdict": control["verdict"],
            "item": key,
            "value": value,
        }
        for control in controls
        for key, value in control["headline"].items()
    ]
    table_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(control['control_id'])}</code></td>"
        f"<td class=\"{_verdict_class(str(control['verdict']))}\">{html.escape(str(control['verdict']))}</td>"
        f"<td>{html.escape('；'.join(f'{k} = {label(v) if isinstance(v, float) else v}' for k, v in control['headline'].items()))}</td>"
        "</tr>"
        for control in controls
    )
    table = (
        "<table><thead><tr><th>对照</th><th>verdict</th><th>关键数值</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table>"
    )
    notes = tuple(
        f"{control['control_id']}：verdict = {control['verdict']}。"
        for control in controls
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=tuple(control["source_path"] for control in controls),
        findings={"controls": controls},
        notes=notes,
        svg_name="falsification-controls.svg",
        svg=svg,
        csv_name="falsification-controls.csv",
        csv_fields=("control_id", "verdict", "item", "value"),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _forest_svg(rows: list[dict[str, Any]], boundary: str) -> str:
    width = 1180
    left, right, top, bottom = 300, 330, 108, 78
    plot_width = width - left - right
    zero_x = left + plot_width / 2
    half = plot_width / 2
    row_height = 24
    band_height = 30

    def sx(value: float) -> float:
        if value == 0.0:
            return zero_x
        sign = 1.0 if value > 0 else -1.0
        magnitude = (math.log10(max(abs(value), 1e-4)) + 4.0) / 4.0
        return zero_x + sign * min(magnitude, 1.0) * half

    experiments: list[str] = []
    for row in rows:
        if row["experiment"] not in experiments:
            experiments.append(row["experiment"])
    height = (
        top + bottom + len(rows) * row_height + len(experiments) * band_height
    )
    parts = [
        '<text class="title" x="20" y="32">效应稳健性森林图（探索性诊断）</text>',
        '<text class="subtitle" x="20" y="55">逐细胞配对差值 mean_diff 与 95% CI（细胞级配对 bootstrap 10000 次）；有向对数轴，|效应| ≤ 1e-4 显示在零线</text>',
        '<text class="subtitle" x="20" y="76">实心方块 = CI 不含 0；空心 = CI 含 0；右侧为 mean [CI] 与方向一致率</text>',
    ]
    for tick in (-1.0, -1e-1, -1e-2, -1e-3, -1e-4, 0.0, 1e-4, 1e-3, 1e-2, 1e-1, 1.0):
        px = sx(tick)
        parts.append(
            f'<line class="grid" x1="{px:.2f}" y1="{top}" x2="{px:.2f}" y2="{height - bottom}"/>'
            f'<text x="{px:.2f}" y="{height - bottom + 20}" text-anchor="middle">'
            f'{"0" if tick == 0.0 else f"{tick:g}"}</text>'
        )
    parts.append(
        f'<line class="axis" x1="{zero_x:.2f}" y1="{top}" x2="{zero_x:.2f}" y2="{height - bottom}" stroke-width="2"/>'
    )
    y_cursor = top + 6
    for experiment in experiments:
        color = COLORS[experiments.index(experiment) % len(COLORS)]
        parts.append(
            f'<rect x="20" y="{y_cursor}" width="{width - 40}" height="{band_height - 6}" fill="{color}" opacity="0.12"/>'
            f'<text x="30" y="{y_cursor + 17}" font-weight="600">{html.escape(_EXPERIMENT_DISPLAY_NAMES.get(experiment, experiment))}（{html.escape(experiment)}）</text>'
        )
        y_cursor += band_height
        for row in rows:
            if row["experiment"] != experiment:
                continue
            cy = y_cursor + row_height / 2
            lo, hi, mean = row["ci95_lower"], row["ci95_upper"], row["mean_diff"]
            parts.append(
                f'<text x="{left - 12}" y="{cy + 4:.2f}" text-anchor="end">'
                f'{html.escape(row["condition"])} · {html.escape(_FIELD_DISPLAY_NAMES.get(row["field"], row["field"]))}</text>'
            )
            parts.append(
                f'<line x1="{sx(lo):.2f}" y1="{cy:.2f}" x2="{sx(hi):.2f}" y2="{cy:.2f}" stroke="{color}" stroke-width="2"/>'
                f'<line x1="{sx(lo):.2f}" y1="{cy - 5:.2f}" x2="{sx(lo):.2f}" y2="{cy + 5:.2f}" stroke="{color}" stroke-width="2"/>'
                f'<line x1="{sx(hi):.2f}" y1="{cy - 5:.2f}" x2="{sx(hi):.2f}" y2="{cy + 5:.2f}" stroke="{color}" stroke-width="2"/>'
            )
            fill = color if row["ci_excludes_zero"] else "#ffffff"
            parts.append(
                f'<rect x="{sx(mean) - 5:.2f}" y="{cy - 5:.2f}" width="10" height="10" '
                f'fill="{fill}" stroke="{color}" stroke-width="2">'
                f"<title>{html.escape(row['condition'])} {html.escape(row['field'])}: mean={label(mean)}, CI=[{label(lo)}, {label(hi)}]</title></rect>"
            )
            parts.append(
                f'<text x="{width - right + 16}" y="{cy + 4:.2f}" font-size="11">'
                f'{label(mean)} [{label(lo)}, {label(hi)}]　一致率 {row["direction_consistency"]:.2f}</text>'
            )
            y_cursor += row_height
    parts.append(
        f'<text x="{left + plot_width / 2:.2f}" y="{height - 22}" text-anchor="middle">逐细胞配对差值（条件 − 同 seed baseline；有向 log10 显示，±1e-4 内线性截断到零线）</text>'
    )
    return svg_document(
        width=width,
        height=height,
        title="效应稳健性森林图",
        description="Forest plot of paired per-cell effect sizes with 95 percent bootstrap confidence intervals across three experiments.",
        body="\n".join(parts),
    )


def _section_effect_robustness(inputs: list[_Input]) -> _Section:
    section_id, title = "effect-robustness", "效应稳健性"
    summary_input = next(
        (item for item in inputs if item.input_id == "effect-robustness:summary"),
        inputs[0],
    )
    if summary_input.payload is None:
        return _missing_section(section_id, title, inputs)
    payload = summary_input.payload
    boundary = str(payload.get("exploratory_boundary", ""))
    rows: list[dict[str, Any]] = []
    experiments_model: list[dict[str, Any]] = []
    for experiment in payload["experiments"]:
        cross_check = experiment.get("l4_cross_check", {})
        pairings_model = []
        for pairing in experiment["pairings"]:
            fields_model = {}
            for field in _FIELD_ORDER:
                result = pairing["result"]["fields"].get(field)
                if result is None:
                    continue
                row = {
                    "experiment": experiment["experiment"],
                    "condition": pairing["condition"],
                    "field": field,
                    "mean_diff": result["mean_diff"],
                    "ci95_lower": result["ci95_lower"],
                    "ci95_upper": result["ci95_upper"],
                    "ci_excludes_zero": result["ci_excludes_zero"],
                    "direction_consistency": result["direction_consistency"],
                    "n_cells_paired": pairing["result"]["n_cells_paired"],
                }
                rows.append(row)
                fields_model[field] = {
                    key: row[key]
                    for key in (
                        "mean_diff",
                        "ci95_lower",
                        "ci95_upper",
                        "ci_excludes_zero",
                        "direction_consistency",
                    )
                }
            pairings_model.append(
                {
                    "condition": pairing["condition"],
                    "canonical_seed": pairing["canonical_seed"],
                    "seed_results_byte_identical": pairing["seed_results_byte_identical"],
                    "fields": fields_model,
                }
            )
        experiments_model.append(
            {
                "experiment": experiment["experiment"],
                "l4_cross_check_status": cross_check.get("status"),
                "l4_cross_check_all_match": cross_check.get("all_match"),
                "pairings": pairings_model,
            }
        )
    svg = _forest_svg(rows, boundary)
    checked = sum(1 for item in experiments_model if item["l4_cross_check_all_match"])
    notes = (
        boundary,
        f"L4 交叉核验（raw 重算 vs derived summary，容差 1e-9）：{checked}/{len(experiments_model)} 个实验全部一致。",
        "全部 seed 经逐位比对为确定性重放重复，不构成统计重复；CI 只刻画单次实现内部逐细胞离散度。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=tuple(item.display_path for item in inputs if item.payload is not None),
        findings={"experiments": experiments_model},
        notes=notes,
        svg_name="effect-robustness-forest.svg",
        svg=svg,
        csv_name="effect-robustness-forest.csv",
        csv_fields=(
            "experiment",
            "condition",
            "field",
            "mean_diff",
            "ci95_lower",
            "ci95_upper",
            "ci_excludes_zero",
            "direction_consistency",
            "n_cells_paired",
        ),
        csv_rows=tuple(rows),
        html_table=None,
    )


def _section_wp8(inputs: list[_Input]) -> _Section:
    section_id, title = "wp8-matrix", "WP8 矩阵"
    item = inputs[0]
    if item.payload is None:
        return _missing_section(section_id, title, inputs)
    payload = item.payload
    summaries = payload["summaries"]
    groups = tuple(entry["condition_id"] for entry in summaries)
    values = {
        (entry["condition_id"], layer): effect
        for entry in summaries
        for layer, effect in entry["mean_layer_effects"]
    }
    svg = _grouped_bar_svg(
        title="WP8 矩阵：逐条件 L0–L4 平均绝对效应",
        subtitle="逐 seed 配对终点平均绝对状态距离（log10 轴）；口径：直接读取冻结 derived/summary.json 均值，非本报告重算",
        description="Grouped log-scale bar chart of L0 to L4 mean absolute effects for the six non-baseline WP8 conditions.",
        groups=groups,
        series=_LAYER_ORDER,
        values=values,
        log_scale=True,
        y_label="平均绝对效应（log10 显示）",
    )
    rows = [
        {
            "condition_id": entry["condition_id"],
            "condition_kind": entry["condition_kind"],
            "layer": layer,
            "mean_effect": effect,
        }
        for entry in summaries
        for layer, effect in entry["mean_layer_effects"]
    ]
    outcome_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(entry['condition_id'])}</code></td>"
        f"<td>{html.escape(entry['condition_kind'])}</td>"
        + "".join(
            f"<td class=\"{'bad' if outcome == 'failed' and count else ''}\">{count}</td>"
            for outcome, count in entry["outcome_counts"]
        )
        + "</tr>"
        for entry in summaries
    )
    outcome_names = [outcome for outcome, _ in summaries[0]["outcome_counts"]]
    table = (
        "<table><thead><tr><th>条件</th><th>类型</th>"
        + "".join(f"<th>{html.escape(name)}</th>" for name in outcome_names)
        + "</tr></thead>"
        f"<tbody>{outcome_rows}</tbody></table>"
    )
    notes = (
        f"矩阵 {payload['matrix_id']}：{payload['condition_count']} 条件 × {len(payload['config']['seeds'])} seed，"
        f"{payload['run_count']} 份 raw run，{payload['comparison_count']} 个配对比较。",
        "口径声明：本区块直接读取冻结 derived/summary.json 的逐 seed 均值与结局计数（该 summary 本身可由 raw 经 ADR-0008 协议重建）；"
        "raw-only 重算报告由 mgba report（ADR-0009）承担，本报告不替代它。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=(item.display_path,),
        findings={
            "matrix_id": payload["matrix_id"],
            "run_count": payload["run_count"],
            "comparison_count": payload["comparison_count"],
            "provenance": "derived/summary.json 直接读取（均值口径见 notes）",
            "conditions": [
                {
                    "condition_id": entry["condition_id"],
                    "condition_kind": entry["condition_kind"],
                    "mean_layer_effects": dict(entry["mean_layer_effects"]),
                    "outcome_counts": dict(entry["outcome_counts"]),
                }
                for entry in summaries
            ],
        },
        notes=notes,
        svg_name="wp8-matrix.svg",
        svg=svg,
        csv_name="wp8-matrix.csv",
        csv_fields=("condition_id", "condition_kind", "layer", "mean_effect"),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _carm_intervention_svg(
    contrasts: list[dict[str, Any]],
) -> str:
    width, height = 1060, 800
    left, right = 120, 60
    plot_width = width - left - right
    parts = [
        '<text class="title" x="20" y="32">CAR-M 状态条件干预：timing contrast</text>',
        '<text class="subtitle" x="20" y="55">上：各 contrast 终末 L4 距离（逐 seed 均值）；下：late − early 五指标效应（逐 seed 均值，以 0 为中心）</text>',
    ]
    top_a, height_a = 100, 180
    peak = max(row["terminal_l4_distance_mean"] for row in contrasts) * 1.2
    slot = plot_width / len(contrasts)
    for index, row in enumerate(contrasts):
        value = row["terminal_l4_distance_mean"]
        bar_height = value / peak * height_a
        px = left + index * slot + slot * 0.25
        py = top_a + height_a - bar_height
        parts.append(
            f'<rect x="{px:.2f}" y="{py:.2f}" width="{slot * 0.5:.2f}" height="{bar_height:.2f}" fill="{COLORS[index]}">'
            f"<title>{html.escape(row['contrast_id'])}: {label(value)}</title></rect>"
            f'<text x="{px + slot * 0.25:.2f}" y="{py - 6:.2f}" text-anchor="middle">{label(value)}</text>'
            f'<text x="{px + slot * 0.25:.2f}" y="{top_a + height_a + 20:.2f}" text-anchor="middle">{html.escape(row["contrast_id"])}</text>'
        )
    parts.append(
        f'<line class="axis" x1="{left}" y1="{top_a + height_a}" x2="{width - right}" y2="{top_a + height_a}"/>'
    )
    top_b, height_b = 360, 330
    max_abs = max(
        abs(value)
        for row in contrasts
        for value in row["late_minus_early_metrics_mean"].values()
    )
    max_abs = max(max_abs, 1e-6) * 1.15
    zero_y = top_b + height_b / 2

    def sy(value: float) -> float:
        return zero_y - (value / max_abs) * (height_b / 2)

    for fraction in (-1.0, -0.5, 0.0, 0.5, 1.0):
        py = sy(fraction * max_abs / 1.15)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{width - right}" y2="{py:.2f}"/>'
            f'<text x="{left - 10}" y="{py + 4:.2f}" text-anchor="end">{fraction * max_abs / 1.15:.4f}</text>'
        )
    slot_b = plot_width / len(contrasts)
    bar_width = slot_b * 0.72 / len(_L4_METRICS)
    for contrast_index, row in enumerate(contrasts):
        base_x = left + contrast_index * slot_b + slot_b * 0.14
        for metric_index, metric in enumerate(_L4_METRICS):
            value = row["late_minus_early_metrics_mean"][metric]
            px = base_x + metric_index * bar_width
            py = sy(value)
            parts.append(
                f'<rect x="{px:.2f}" y="{min(py, zero_y):.2f}" width="{bar_width * 0.9:.2f}" '
                f'height="{abs(py - zero_y):.2f}" fill="{COLORS[metric_index]}">'
                f"<title>{html.escape(row['contrast_id'])} {html.escape(metric)}: {label(value)}</title></rect>"
            )
        parts.append(
            f'<text x="{left + contrast_index * slot_b + slot_b / 2:.2f}" y="{top_b + height_b + 24}" '
            f'text-anchor="middle">{html.escape(row["contrast_id"])}（{html.escape(row["early_condition_id"])} → {html.escape(row["late_condition_id"])}）</text>'
        )
    parts.append(
        f'<line class="axis" x1="{left}" y1="{zero_y:.2f}" x2="{width - right}" y2="{zero_y:.2f}" stroke-width="2"/>'
    )
    for metric_index, metric in enumerate(_L4_METRICS):
        legend_x = 90 + metric_index * 185
        parts.append(
            f'<rect x="{legend_x}" y="{top_b - 26}" width="12" height="12" fill="{COLORS[metric_index]}"/>'
            f'<text x="{legend_x + 18}" y="{top_b - 16}">{html.escape(metric)}</text>'
        )
    return svg_document(
        width=width,
        height=height,
        title="CAR-M 状态条件干预 timing contrast",
        description="Bar panels of terminal L4 distance and five late-minus-early metric effects for the two timing contrasts.",
        body="\n".join(parts),
    )


def _section_carm_intervention(inputs: list[_Input]) -> _Section:
    section_id, title = "carm-intervention", "CAR-M 干预"
    item = inputs[0]
    if item.payload is None:
        return _missing_section(section_id, title, inputs)
    payload = item.payload
    by_contrast: dict[str, list[dict[str, Any]]] = {}
    for entry in payload["timing_contrasts"]:
        by_contrast.setdefault(entry["contrast_id"], []).append(entry)
    contrasts: list[dict[str, Any]] = []
    for contrast_id in sorted(by_contrast):
        entries = by_contrast[contrast_id]
        metrics_mean = {
            metric: fmean(
                dict(entry["late_minus_early_metrics"])[metric] for entry in entries
            )
            for metric in _L4_METRICS
        }
        contrasts.append(
            {
                "contrast_id": contrast_id,
                "early_condition_id": entries[0]["early_condition_id"],
                "late_condition_id": entries[0]["late_condition_id"],
                "seed_count": len(entries),
                "terminal_l4_distance_mean": fmean(
                    entry["terminal_l4_distance"] for entry in entries
                ),
                "late_minus_early_metrics_mean": metrics_mean,
            }
        )
    svg = _carm_intervention_svg(contrasts)
    rows = [
        {
            "contrast_id": contrast["contrast_id"],
            "quantity": "terminal_l4_distance",
            "value": contrast["terminal_l4_distance_mean"],
        }
        for contrast in contrasts
    ] + [
        {"contrast_id": contrast["contrast_id"], "quantity": metric, "value": value}
        for contrast in contrasts
        for metric, value in contrast["late_minus_early_metrics_mean"].items()
    ]
    outcome_counts: dict[str, int] = {}
    for record in payload["records"]:
        outcome_counts[record["outcome"]] = outcome_counts.get(record["outcome"], 0) + 1
    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(contrast['contrast_id'])}</td>"
        f"<td><code>{html.escape(contrast['early_condition_id'])}</code> → <code>{html.escape(contrast['late_condition_id'])}</code></td>"
        f"<td>{label(contrast['terminal_l4_distance_mean'])}</td>"
        + "".join(
            f"<td>{label(contrast['late_minus_early_metrics_mean'][metric])}</td>"
            for metric in _L4_METRICS
        )
        + "</tr>"
        for contrast in contrasts
    )
    table = (
        "<table><thead><tr><th>contrast</th><th>early → late</th><th>终末 L4 距离</th>"
        + "".join(f"<th>Δ {html.escape(metric)}</th>" for metric in _L4_METRICS)
        + "</tr></thead>"
        f"<tbody>{table_rows}</tbody></table>"
    )
    notes = (
        f"实验 {payload['experiment_id']}：{payload['condition_count']} 条件 × 3 seed × {payload['config']['ticks']} tick；"
        f"结局分布 {dict(sorted(outcome_counts.items()))}。",
        "模型状态：" + str(payload.get("model_status", "")),
        "三个 seed 数值逐位相同，只作确定性重放门禁，不构成统计重复；晚期干预减轻 vitality/damage 代价但提高 inflammation 是 reference-rule trade-off，不是疗效证据。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=(item.display_path,),
        findings={
            "experiment_id": payload["experiment_id"],
            "model_status": payload.get("model_status"),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "timing_contrasts": contrasts,
        },
        notes=notes,
        svg_name="carm-intervention.svg",
        svg=svg,
        csv_name="carm-intervention.csv",
        csv_fields=("contrast_id", "quantity", "value"),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _section_spatial_anchor(inputs: list[_Input]) -> _Section:
    section_id, title = "spatial-anchor", "空间锚定"
    usable = [item for item in inputs if item.payload is not None]
    if not usable:
        return _missing_section(section_id, title, inputs)
    item = usable[0]
    payload = item.payload
    assert payload is not None
    score = payload["score"]
    role_scores = {entry["role"]: entry for entry in score["role_scores"]}
    comparisons = score["comparisons"]
    by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in _ROLE_ORDER}
    for comparison in comparisons:
        by_role.setdefault(comparison["role"], []).append(comparison)

    width = 1180
    left = 300
    row_height = 24
    band_height = 32
    top = 100
    total_rows = sum(len(by_role.get(role, [])) for role in _ROLE_ORDER)
    height = top + total_rows * row_height + len(_ROLE_ORDER) * band_height + 50
    parts = [
        '<text class="title" x="20" y="32">空间锚定：39 指标归一化绝对误差（NAE）色块表</text>',
        '<text class="subtitle" x="20" y="55">绿色 = 模型值落在 target 观测区间内；红色 = 出界；右列为该指标 NAE</text>',
        f'<text class="subtitle" x="20" y="76">评估 {html.escape(payload["evaluation_id"])} → target {html.escape(payload["target_id"])}</text>',
    ]
    y_cursor = top
    out_of_range_total = 0
    rows: list[dict[str, Any]] = []
    for role in _ROLE_ORDER:
        entries = by_role.get(role, [])
        if not entries:
            continue
        role_score = role_scores.get(role, {})
        parts.append(
            f'<rect x="20" y="{y_cursor}" width="{width - 40}" height="{band_height - 8}" fill="{COLORS[1]}" opacity="0.12"/>'
            f'<text x="30" y="{y_cursor + 17}" font-weight="600">{html.escape(_ROLE_DISPLAY[role])}'
            f'　指标数 {role_score.get("metric_count", len(entries))}，平均 NAE {label(role_score.get("mean_normalized_absolute_error", 0.0))}，'
            f'区间内比例 {role_score.get("observed_range_fraction", 0.0):.4f}</text>'
        )
        y_cursor += band_height
        for comparison in entries:
            cy = y_cursor + row_height / 2
            in_range = comparison["in_observed_range"]
            out_of_range_total += 0 if in_range else 1
            color = _OK if in_range else _BAD
            parts.extend(
                (
                    f'<rect x="{left - 40}" y="{y_cursor + 3}" width="18" height="18" fill="{color}">'
                    f"<title>{html.escape(comparison['metric_id'])}: NAE={label(comparison['normalized_absolute_error'])}, in_range={in_range}</title></rect>",
                    f'<text x="{left - 50}" y="{cy + 4:.2f}" text-anchor="end">{html.escape(comparison["metric_id"])}</text>',
                    f'<text x="{left + 10}" y="{cy + 4:.2f}">NAE {label(comparison["normalized_absolute_error"])}</text>',
                    f'<text x="{left + 210}" y="{cy + 4:.2f}">模型值 {label(comparison["model_value"])}</text>',
                    f'<text x="{left + 400}" y="{cy + 4:.2f}">target 中位 {label(comparison["target_median"])}</text>',
                    f'<text x="{left + 590}" y="{cy + 4:.2f}">区间 [{label(comparison["target_minimum"])}, {label(comparison["target_maximum"])}]</text>',
                )
            )
            rows.append(
                {
                    "role": role,
                    "metric_id": comparison["metric_id"],
                    "model_value": comparison["model_value"],
                    "target_median": comparison["target_median"],
                    "target_minimum": comparison["target_minimum"],
                    "target_maximum": comparison["target_maximum"],
                    "normalized_absolute_error": comparison["normalized_absolute_error"],
                    "in_observed_range": in_range,
                }
            )
            y_cursor += row_height
    svg = svg_document(
        width=width,
        height=height,
        title="空间锚定 39 指标 NAE 色块表",
        description="Color block table of 39 normalized absolute errors grouped by calibration, holdout and external validation roles.",
        body="\n".join(parts),
    )
    role_rows = "".join(
        "<tr>"
        f"<td>{html.escape(_ROLE_DISPLAY[role])}</td>"
        f"<td>{role_scores[role]['metric_count']}</td>"
        f"<td>{label(role_scores[role]['mean_normalized_absolute_error'])}</td>"
        f"<td>{label(role_scores[role]['maximum_normalized_absolute_error'])}</td>"
        f"<td class=\"{'bad' if role != 'external_validation' else ''}\">{role_scores[role]['observed_range_fraction']:.4f}</td>"
        "</tr>"
        for role in _ROLE_ORDER
        if role in role_scores
    )
    table = (
        "<table><thead><tr><th>role</th><th>指标数</th><th>平均 NAE</th>"
        "<th>最大 NAE</th><th>观测区间内比例</th></tr></thead>"
        f"<tbody>{role_rows}</tbody></table>"
    )
    notes = (
        f"39 个指标中 {out_of_range_total} 个落在 target 观测区间外；按预注册判据记为未锚定（负面结果原样保留）。",
        "评估边界（逐字来源）：" + str(payload.get("scientific_boundary", "")),
        "关联发现：ADR-0048 对照 3（目标置换）判据不成立——置换 target 的 holdout 平均 NAE 反而优于真实 target，"
        "说明该评估器在 holdout field 指标上区分度不足；见证伪对照区块。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=(item.display_path,),
        findings={
            "evaluation_id": payload["evaluation_id"],
            "target_id": payload["target_id"],
            "out_of_range_count": out_of_range_total,
            "metric_count": len(comparisons),
            "role_scores": [
                {
                    "role": role,
                    "metric_count": role_scores[role]["metric_count"],
                    "mean_normalized_absolute_error": role_scores[role][
                        "mean_normalized_absolute_error"
                    ],
                    "maximum_normalized_absolute_error": role_scores[role][
                        "maximum_normalized_absolute_error"
                    ],
                    "observed_range_fraction": role_scores[role][
                        "observed_range_fraction"
                    ],
                }
                for role in _ROLE_ORDER
                if role in role_scores
            ],
        },
        notes=notes,
        svg_name="spatial-anchor.svg",
        svg=svg,
        csv_name="spatial-anchor.csv",
        csv_fields=(
            "role",
            "metric_id",
            "model_value",
            "target_median",
            "target_minimum",
            "target_maximum",
            "normalized_absolute_error",
            "in_observed_range",
        ),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _section_bridge_coverage(inputs: list[_Input]) -> _Section:
    section_id, title = "bridge-coverage", "桥覆盖"
    item = inputs[0]
    if item.payload is None:
        return _missing_section(section_id, title, inputs)
    payload = item.payload
    node_order = payload["bridge"]["node_order"]
    coverage = payload["node_coverage"]
    groups = tuple(node_order)
    series = ("Norman OE 宇宙", "Replogle KD 宇宙")
    values = {
        (node, display): coverage[node][key]["coverage_rate"]
        for node in groups
        for display, key in zip(series, ("norman", "replogle_kd"), strict=True)
    }
    svg = _grouped_bar_svg(
        title="Hallmark 六节点桥：两宇宙基因覆盖率",
        subtitle="每个节点的桥映射基因在 Norman OE 与 Replogle KD 宇宙中的覆盖率；下方为宇宙级缺口",
        description="Grouped bar chart of per-node gene coverage rates over the Norman and Replogle KD universes.",
        groups=groups,
        series=series,
        values=values,
        y_label="覆盖率",
    )
    rows = [
        {
            "node": node,
            "mapped_genes": coverage[node]["mapped_genes"],
            "norman_covered_genes": coverage[node]["norman"]["covered_genes"],
            "norman_coverage_rate": coverage[node]["norman"]["coverage_rate"],
            "replogle_kd_covered_genes": coverage[node]["replogle_kd"]["covered_genes"],
            "replogle_kd_coverage_rate": coverage[node]["replogle_kd"]["coverage_rate"],
        }
        for node in groups
    ]
    gap = payload["universe_gap"]
    universes = payload["universes"]
    gap_rows = "".join(
        "<tr>"
        f"<td>{html.escape(universes[key]['dataset_id'])}</td>"
        f"<td>{universes[key]['universe_genes']}</td>"
        f"<td>{universes[key]['unit_count']}</td>"
        f"<td class=\"bad\">{gap[key]['uncovered_genes']}</td>"
        f"<td class=\"bad\">{gap[key]['uncovered_rate']:.4f}</td>"
        "</tr>"
        for key in ("norman", "replogle_kd")
    )
    table = (
        "<table><thead><tr><th>宇宙</th><th>宇宙基因数</th><th>单元数</th>"
        "<th>不落入任何节点的基因数</th><th>缺口比例</th></tr></thead>"
        f"<tbody>{gap_rows}</tbody></table>"
    )
    notes = (
        f"桥版本 {payload['bridge']['version']}；六节点桥外基因缺口："
        f"Norman {gap['norman']['uncovered_genes']}/{gap['norman']['universe_genes']}"
        f"（{gap['norman']['uncovered_rate']:.4f}）、"
        f"Replogle KD {gap['replogle_kd']['uncovered_genes']}/{gap['replogle_kd']['universe_genes']}"
        f"（{gap['replogle_kd']['uncovered_rate']:.4f}）。",
        "只读审计（2026-09-11）：不修改任何冻结契约、映射或数据文件；缺口数字是桥表达力的诚实边界。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=(item.display_path,),
        findings={
            "audit_id": payload.get("audit_id"),
            "bridge_version": payload["bridge"]["version"],
            "node_coverage": rows,
            "universe_gap": {
                key: {
                    "universe_genes": gap[key]["universe_genes"],
                    "uncovered_genes": gap[key]["uncovered_genes"],
                    "uncovered_rate": gap[key]["uncovered_rate"],
                }
                for key in ("norman", "replogle_kd")
            },
        },
        notes=notes,
        svg_name="bridge-coverage.svg",
        svg=svg,
        csv_name="bridge-coverage.csv",
        csv_fields=(
            "node",
            "mapped_genes",
            "norman_covered_genes",
            "norman_coverage_rate",
            "replogle_kd_covered_genes",
            "replogle_kd_coverage_rate",
        ),
        csv_rows=tuple(rows),
        html_table=table,
    )


def _section_data_registry(inputs: list[_Input]) -> _Section:
    section_id, title = "data-registry", "数据登记"
    item = inputs[0]
    if item.payload is None:
        return _missing_section(section_id, title, inputs)
    payload = item.payload
    datasets = payload["datasets"]
    status_counts: dict[str, int] = {}
    for entry in datasets:
        status = str(entry.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    statuses = tuple(sorted(status_counts))
    groups = statuses
    series = ("条目数",)
    values = {(status, "条目数"): float(status_counts[status]) for status in statuses}
    svg = _grouped_bar_svg(
        title="数据登记表：条目状态总览",
        subtitle=f"共 {len(datasets)} 条目；materialized = 已落盘并核验 SHA-256，generated = 内部合成，planned = 已登记待授权/下载",
        description="Bar chart of data registry entry counts by status.",
        groups=groups,
        series=series,
        values=values,
        y_label="条目数",
    )
    rows = [
        {
            "dataset_id": entry.get("dataset_id"),
            "kind": entry.get("kind"),
            "status": entry.get("status"),
            "path": entry.get("path"),
        }
        for entry in datasets
    ]
    table_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(str(row['dataset_id']))}</code></td>"
        f"<td>{html.escape(str(row['kind']))}</td>"
        f"<td class=\"{'warn' if row['status'] == 'planned' else ''}\">{html.escape(str(row['status']))}</td>"
        f"<td><code>{html.escape(str(row['path']))}</code></td>"
        "</tr>"
        for row in rows
    )
    table = (
        "<table><thead><tr><th>dataset_id</th><th>kind</th><th>status</th><th>path</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table>"
    )
    notes = (
        f"registry schema {payload.get('schema_version')}，共 {len(datasets)} 条目："
        + "、".join(f"{status} {status_counts[status]}" for status in statuses)
        + "。mgba data-check 为 fail-closed 校验门禁（ADR-0021）。",
    )
    return _Section(
        section_id=section_id,
        title=title,
        evidence_level=_EVIDENCE_LEVELS[section_id],
        status="present",
        source_paths=(item.display_path,),
        findings={
            "entry_count": len(datasets),
            "status_counts": {status: status_counts[status] for status in statuses},
            "entries": rows,
        },
        notes=notes,
        svg_name="data-registry.svg",
        svg=svg,
        csv_name="data-registry.csv",
        csv_fields=("dataset_id", "kind", "status", "path"),
        csv_rows=tuple(rows),
        html_table=table,
    )


# ---------------------------------------------------------------------------
# negative findings + html


def _negative_findings(sections: list[_Section]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    by_id = {section.section_id: section for section in sections}

    training = by_id["training-evaluation"]
    if training.status == "present":
        for item in training.findings["evaluations"]:
            if item["verdict"] != "passed":
                findings.append(
                    {
                        "section_id": training.section_id,
                        "text": (
                            f"训练评估 {item['display_name']}：verdict = {item['verdict']}"
                            f"（margin vs 质心 {label(item['margin_vs_centroid'])}、"
                            f"vs ridge {label(item['margin_vs_ridge'])}）"
                        ),
                    }
                )

    extrapolation = by_id["extrapolation-boundary"]
    if extrapolation.status == "present" and extrapolation.findings["verdict"] != "passed":
        unseen = extrapolation.findings["strata"][1]
        findings.append(
            {
                "section_id": extrapolation.section_id,
                "text": (
                    f"OE 成分外推边界（ADR-0049）：verdict = {extrapolation.findings['verdict']}；"
                    f"component-unseen 层 MLP MAE {label(unseen['mae_mlp'])} 不优于质心 "
                    f"{label(unseen['mae_centroid'])}（margin {label(unseen['margin_vs_centroid'])}），"
                    "OE 外推方向正式关闭"
                ),
            }
        )

    falsification = by_id["falsification-controls"]
    if falsification.status == "present":
        for control in falsification.findings["controls"]:
            if control["verdict"] != "criteria_met":
                headline = control["headline"]
                findings.append(
                    {
                        "section_id": falsification.section_id,
                        "text": (
                            f"证伪对照 {control['control_id']}（目标置换）：verdict = {control['verdict']}；"
                            f"置换 target holdout NAE {label(headline.get('置换 holdout NAE', 0.0))} "
                            f"反而优于真实 {label(headline.get('真实 holdout NAE', 0.0))}，"
                            "空间锚定评估器在 holdout field 指标上无区分度，负面结果原样登记"
                        ),
                    }
                )

    spatial = by_id["spatial-anchor"]
    if spatial.status == "present":
        findings.append(
            {
                "section_id": spatial.section_id,
                "text": (
                    f"空间锚定：39 指标中 {spatial.findings['out_of_range_count']} 个落在 target 观测区间外，"
                    "按预注册判记为未锚定"
                ),
            }
        )

    wp8 = by_id["wp8-matrix"]
    if wp8.status == "present":
        failed_conditions = [
            condition["condition_id"]
            for condition in wp8.findings["conditions"]
            if condition["outcome_counts"].get("failed", 0) > 0
        ]
        if failed_conditions:
            findings.append(
                {
                    "section_id": wp8.section_id,
                    "text": (
                        f"WP8 矩阵：{len(failed_conditions)} 个非 baseline 条件的结局含 failed"
                        f"（{', '.join(failed_conditions)}）；100 tick 默认链保持 FAILED 负面基线"
                    ),
                }
            )
    return findings


def _report_html(
    sections: list[_Section],
    inputs: Mapping[str, list[_Input]],
    negative: list[dict[str, str]],
) -> str:
    negative_items = "".join(
        f"<li><strong>{html.escape(item['text'])}</strong></li>" for item in negative
    )
    section_html: list[str] = []
    for index, section in enumerate(sections, start=1):
        sources = "、".join(
            f"<code>{html.escape(path)}</code>" for path in section.source_paths
        )
        if section.status == "missing":
            body = (
                f'<p class="missing">未生成：{html.escape("；".join(section.notes))}。'
                "本区块降级显示，不影响其他区块。</p>"
            )
        else:
            figure = (
                f"<figure>{section.svg}<figcaption>{html.escape(section.notes[0])}</figcaption></figure>"
                if section.svg
                else ""
            )
            table = section.html_table or ""
            shown_notes = section.notes[1:] if section.svg else section.notes
            notes = "".join(
                f'<p class="note">{html.escape(note)}</p>' for note in shown_notes
            )
            csv_link = (
                f'<p>数据表：<a href="{section.csv_name}">{section.csv_name}</a>；'
                f'图表：<a href="{section.svg_name}">{section.svg_name}</a></p>'
            )
            body = figure + table + notes + csv_link
        section_html.append(
            f'<section id="{section.section_id}">'
            f"<h2>{index}. {html.escape(section.title)}"
            f' <span class="level">{html.escape(section.evidence_level)}</span></h2>'
            f'<p class="src">来源：{sources} · 状态：{html.escape(section.status)}</p>'
            f"{body}</section>"
        )
    input_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(input_id)}</code></td>"
        f"<td><code>{html.escape(item.display_path)}</code></td>"
        f"<td>{html.escape(item.status)}</td>"
        f"<td><code>{html.escape(item.sha256[:16] + '…' if item.sha256 else '—')}</code></td>"
        "</tr>"
        for input_id in sorted(inputs)
        for item in inputs[input_id]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M-GBA 证据总览报告</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ max-width: 1200px; margin: 0 auto; padding: 24px; line-height: 1.6; }}
h1, h2 {{ font-weight: 600; }}
.boundary {{ border-left: 4px solid #ca8a04; padding-left: 12px; }}
.negative {{ border: 2px solid #dc2626; border-radius: 8px; padding: 12px 18px; }}
.negative h2 {{ color: #dc2626; margin-top: 0; }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); padding: 8px; text-align: left; }}
figure {{ margin: 28px 0; }}
figure svg {{ width: 100%; height: auto; }}
figcaption {{ color: color-mix(in srgb, currentColor 70%, transparent); }}
code {{ font-family: ui-monospace, monospace; overflow-wrap: anywhere; }}
.level {{ font-size: 0.75rem; font-weight: 600; border: 1px solid #2563eb; color: #2563eb; border-radius: 999px; padding: 2px 10px; vertical-align: middle; }}
.ok {{ color: #16a34a; font-weight: 600; }}
.bad {{ color: #dc2626; font-weight: 600; }}
.warn {{ color: #ca8a04; font-weight: 600; }}
.missing {{ color: #ca8a04; font-weight: 600; }}
.note {{ color: color-mix(in srgb, currentColor 75%, transparent); font-size: 0.95rem; }}
.src {{ color: color-mix(in srgb, currentColor 65%, transparent); font-size: 0.85rem; }}
section {{ margin-bottom: 40px; }}
</style>
</head>
<body>
<h1>M-GBA 证据总览报告</h1>
<p><strong>产物 schema：</strong><code>{EVIDENCE_SCHEMA}</code> · <strong>流水线：</strong>collect → normalize → render → manifest → verify（ADR-0050）</p>
<p class="boundary">{html.escape(REPORT_BOUNDARY)}</p>
<section class="negative">
<h2>负面结果与未通过判定（原样显著标注）</h2>
<ul>{negative_items}</ul>
</section>
{''.join(section_html)}
<section id="inputs">
<h2>输入清单与文件身份</h2>
<table>
<thead><tr><th>输入</th><th>路径</th><th>状态</th><th>SHA-256（前 16 位）</th></tr></thead>
<tbody>{input_rows}</tbody>
</table>
<p>统一证据模型：<a href="summary.json">summary.json</a>；全部生成文件与输入的 SHA-256 见 <a href="manifest.json">manifest.json</a>。
本页面不 fetch 数据、不含 JavaScript、不调用任何模型、不写回任何输入文件；同输入重跑可字节级重建（<code>mgba evidence-report --verify</code>）。</p>
</section>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# schema validation


_SECTION_IDS = tuple(section_id for section_id, _ in SECTION_ORDER)


def validate_evidence_summary(payload: Mapping[str, Any]) -> None:
    """Fail-closed structural validation of a ``mgba-evidence-report-0.1`` model."""
    if not isinstance(payload, dict):
        raise ValueError("evidence summary root must be an object")
    if payload.get("schema_version") != EVIDENCE_SCHEMA:
        raise ValueError("evidence summary schema_version mismatch")
    for key in ("report_boundary", "inputs", "sections", "derivation_notes", "negative_findings"):
        if key not in payload:
            raise ValueError(f"evidence summary missing required key: {key}")
    sections = payload["sections"]
    if not isinstance(sections, list):
        raise ValueError("evidence summary sections must be a list")
    if tuple(section.get("section_id") for section in sections) != _SECTION_IDS:
        raise ValueError("evidence summary section order does not match the frozen order")
    for section in sections:
        if section.get("status") not in ("present", "missing"):
            raise ValueError("evidence summary section status must be present/missing")
        if section.get("evidence_level") != _EVIDENCE_LEVELS[section["section_id"]]:
            raise ValueError("evidence summary section evidence level mismatch")
        if section["status"] == "present" and not section.get("findings"):
            raise ValueError("present section must carry findings")
    if not isinstance(payload["negative_findings"], list):
        raise ValueError("negative_findings must be a list")


# ---------------------------------------------------------------------------
# build + verify


_SECTION_BUILDERS = {
    "training-evaluation": _section_training,
    "extrapolation-boundary": _section_extrapolation,
    "falsification-controls": _section_falsification,
    "effect-robustness": _section_effect_robustness,
    "wp8-matrix": _section_wp8,
    "carm-intervention": _section_carm_intervention,
    "spatial-anchor": _section_spatial_anchor,
    "bridge-coverage": _section_bridge_coverage,
    "data-registry": _section_data_registry,
}

_DERIVATION_NOTES = (
    "WP8 矩阵区块直接读取冻结 derived/summary.json 的逐 seed 均值与结局计数，不从 raw 重算（raw-only 重建链见 ADR-0009 mgba report）。",
    "CAR-M 干预 timing contrast 的终末 L4 距离与五指标效应为逐 seed 算术平均（fmean）；当前 seed 为确定性重放，均值仅作展示聚合。",
    "森林图效应量、95% CI 与方向一致率逐字段读自 effect-robustness artifact，本报告不做任何重新采样。",
    "所有覆盖率、NAE、MAE 与 margin 数值逐字读自来源 artifact，本报告只格式化显示（label() 12 位有效数字规则）。",
)


def _resolve_paths(
    artifact_root: str | Path,
    output_dir: str | Path | None,
    registry: str | Path | None,
) -> tuple[Path, Path, Path]:
    root = Path(artifact_root).resolve()
    project_root = root.parent
    registry_path = (
        Path(registry).resolve()
        if registry is not None
        else project_root / "data" / "registry.json"
    )
    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else root / "evidence-report"
    )
    return root, registry_path, output


def build_evidence_report(
    artifact_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    registry: str | Path | None = None,
) -> EvidenceReportPaths:
    root, registry_path, output = _resolve_paths(artifact_root, output_dir, registry)
    project_root = root.parent
    output.mkdir(parents=True, exist_ok=True)

    # 1. collect
    inputs = _collect(root, project_root, registry_path)
    # 2. normalize + 3. render (per section, frozen order)
    sections: list[_Section] = []
    for section_id, _title in SECTION_ORDER:
        sections.append(_SECTION_BUILDERS[section_id](inputs[section_id]))

    negative = _negative_findings(sections)
    summary_payload = {
        "schema_version": EVIDENCE_SCHEMA,
        "report_boundary": REPORT_BOUNDARY,
        "inputs": {
            input_id: [item.manifest_entry() for item in items]
            for input_id, items in sorted(inputs.items())
        },
        "sections": [section.model() for section in sections],
        "derivation_notes": list(_DERIVATION_NOTES),
        "negative_findings": negative,
    }
    validate_evidence_summary(summary_payload)

    section_files: list[Path] = []
    for section in sections:
        if section.svg_name and section.svg is not None:
            target = output / section.svg_name
            target.write_text(section.svg, encoding="utf-8")
            section_files.append(target)
        if section.csv_name and section.csv_fields is not None:
            target = output / section.csv_name
            write_csv(target, section.csv_fields, list(section.csv_rows or ()))
            section_files.append(target)

    html_path = output / "index.html"
    html_path.write_text(
        _report_html(sections, inputs, negative), encoding="utf-8"
    )
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    # 4. manifest
    generated = tuple(sorted(section_files + [html_path, summary_path], key=lambda p: p.name))
    manifest_payload = {
        "schema_version": MANIFEST_SCHEMA,
        "report_schema": EVIDENCE_SCHEMA,
        "inputs": {
            input_id: [item.manifest_entry() for item in items]
            for input_id, items in sorted(inputs.items())
        },
        "inputs_digest": digest_payload(
            {
                input_id: [item.manifest_entry() for item in items]
                for input_id, items in sorted(inputs.items())
            }
        ),
        "files": {path.name: file_sha256(path) for path in generated},
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return EvidenceReportPaths(
        root=output,
        manifest=manifest_path,
        summary=summary_path,
        html=html_path,
        section_files=tuple(section_files),
    )


def verify_evidence_report(
    artifact_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    registry: str | Path | None = None,
) -> dict[str, Any]:
    """Rebuild the report into a temporary directory and byte-compare (phase 5)."""
    root, registry_path, output = _resolve_paths(artifact_root, output_dir, registry)
    if not output.is_dir():
        raise ValueError(f"evidence report output does not exist: {output}")
    existing = {
        path.name: path
        for path in sorted(output.iterdir(), key=lambda p: p.name)
        if path.is_file()
    }
    with tempfile.TemporaryDirectory(prefix="mgba-evidence-verify-") as temporary:
        rebuilt = build_evidence_report(root, temporary, registry=registry_path)
        rebuilt_files = {path.name: path for path in rebuilt.root.iterdir() if path.is_file()}
        mismatches: list[str] = []
        for name in sorted(set(existing) | set(rebuilt_files)):
            if name not in existing:
                mismatches.append(f"{name}: missing in existing output")
            elif name not in rebuilt_files:
                mismatches.append(f"{name}: not reproducible by rebuild")
            elif existing[name].read_bytes() != rebuilt_files[name].read_bytes():
                mismatches.append(f"{name}: byte mismatch")
    return {
        "verified": not mismatches,
        "report_root": str(output),
        "file_count": len(rebuilt_files),
        "mismatches": mismatches,
    }
