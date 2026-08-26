from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent

L4_KEYS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)

INK = "#172033"
MUTED = "#667085"
GRID = "#D8DEE9"
BLUE = "#2A6FDB"
CYAN = "#2E9CCA"
AMBER = "#F59E0B"
ORANGE = "#E87924"
RED = "#C94B4B"
PAPER = "#FBFBF8"


mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "Arial", "DejaVu Sans", "sans-serif"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 14,
        "axes.titlesize": 19,
        "axes.labelsize": 14,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.9,
        "legend.frameon": False,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
    }
)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def terminal_observation(path: Path) -> dict[str, float]:
    payload = load_json(path)
    observation = payload["terminal_observation"]
    return {key: float(observation[key]) for key in L4_KEYS}


def l4_distance(a: dict[str, float], b: dict[str, float]) -> float:
    return float(np.mean([abs(a[key] - b[key]) for key in L4_KEYS]))


def save_figure(fig: mpl.figure.Figure, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.png", dpi=600, bbox_inches="tight")
    fig.savefig(
        OUT / f"{stem}.tiff",
        dpi=600,
        bbox_inches="tight",
        pil_kwargs={"compression": "tiff_lzw"},
    )
    plt.close(fig)


def add_source_footer(fig: mpl.figure.Figure, text: str) -> None:
    fig.text(0.01, 0.012, text, ha="left", va="bottom", fontsize=8.5, color=MUTED)


def plot_spatial_ablation() -> None:
    base = (
        ROOT
        / "artifacts"
        / "carm-spatial-ablation"
        / "carm-spatial-ablation-f53f626b9f3fb9eb"
        / "raw"
    )
    observations: dict[tuple[int, int, int], dict[str, float]] = {}
    for movement in (0, 1):
        for field in (0, 1):
            for topology in (0, 1):
                condition = f"space_m{movement}_f{field}_t{topology}"
                observations[(movement, field, topology)] = terminal_observation(
                    base / condition / "run.json"
                )

    fixed = terminal_observation(base / "fixed_graph" / "run.json")

    factor_specs = [
        ("场耦合", 1, AMBER),
        ("空间邻域", 2, BLUE),
        ("移动", 0, "#9AA4B2"),
    ]
    factor_values = []
    for _, axis, _ in factor_specs:
        paired = []
        for first in (0, 1):
            for second in (0, 1):
                low = [0, 0, 0]
                high = [0, 0, 0]
                other_axes = [idx for idx in (0, 1, 2) if idx != axis]
                low[other_axes[0]] = first
                low[other_axes[1]] = second
                high[:] = low
                high[axis] = 1
                paired.append(l4_distance(observations[tuple(low)], observations[tuple(high)]))
        factor_values.append(float(np.mean(paired)))

    control_labels = ["全关", "仅移动", "完整空间"]
    control_values = [
        l4_distance(fixed, observations[(0, 0, 0)]),
        l4_distance(fixed, observations[(1, 0, 0)]),
        l4_distance(fixed, observations[(1, 1, 1)]),
    ]

    fig = plt.figure(figsize=(11.8, 5.3))
    grid = fig.add_gridspec(
        1,
        2,
        width_ratios=[1.55, 1.0],
        wspace=0.28,
        left=0.09,
        right=0.97,
        top=0.72,
        bottom=0.22,
    )
    ax = fig.add_subplot(grid[0, 0])
    ax2 = fig.add_subplot(grid[0, 1])

    y = np.arange(len(factor_specs))
    bars = ax.barh(
        y,
        factor_values,
        height=0.56,
        color=[spec[2] for spec in factor_specs],
        edgecolor="none",
    )
    ax.invert_yaxis()
    ax.set_yticks(y, [spec[0] for spec in factor_specs])
    ax.set_xlabel("平均终末 L4 距离（四组匹配对照）")
    ax.set_xlim(0, 0.055)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, factor_values):
        ax.text(
            value + 0.0012,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.6f}",
            ha="left",
            va="center",
            fontsize=12.5,
            color=INK,
            fontweight="bold",
        )
    ax.set_title("a  当前杠杆点在场耦合与空间邻域", loc="left", fontweight="bold")

    x = np.arange(len(control_labels))
    colors = ["#B8C0CC", "#B8C0CC", CYAN]
    ax2.scatter(x, control_values, s=140, color=colors, edgecolor="white", linewidth=1.5, zorder=3)
    for xi, value in zip(x, control_values):
        ax2.vlines(xi, 0, value, color=GRID, linewidth=4, zorder=1)
        ax2.text(xi, value + 0.0034, f"{value:.6f}", ha="center", va="bottom", fontsize=11.5, color=INK)
    ax2.axhline(0, color=INK, linewidth=0.8)
    ax2.set_xticks(x, control_labels)
    ax2.set_ylabel("相对固定图的终末 L4 距离")
    ax2.set_ylim(-0.003, 0.063)
    ax2.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    ax2.set_title("b  零效应对照保持为零", loc="left", fontweight="bold")

    fig.suptitle(
        "L3 机制审计：描述性效应，而非统计或疗效证据",
        x=0.02,
        y=0.95,
        ha="left",
        fontsize=22,
        fontweight="bold",
        color=INK,
    )
    add_source_footer(
        fig,
        "2×2×2 确定性 L3 审计，20 ticks；每个主效应为 4 组匹配条件的平均绝对 L4 距离。所有 9 个条件结局均为 RECOVERED。",
    )
    save_figure(fig, "spatial_ablation_effects")


def plot_calibration() -> None:
    path = ROOT / "artifacts" / "calibration-l2" / "calibration-99ce6e355b8e0afa" / "holdout.csv"
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows.extend(csv.DictReader(handle))

    regimes = ["calm", "injury", "severe", "collapse"]
    labels = {"calm": "Calm", "injury": "Injury", "severe": "Severe", "collapse": "Collapse"}
    paired = {}
    for regime in regimes:
        records = {row["config"]: row for row in rows if row["regime"] == regime}
        if set(records) != {"reference", "calibrated"}:
            raise ValueError(f"Unexpected holdout rows for {regime}: {sorted(records)}")
        paired[regime] = records

    fig, ax = plt.subplots(figsize=(10.7, 5.5))
    fig.subplots_adjust(left=0.19, right=0.81, top=0.78, bottom=0.20)
    x = np.array([0.0, 1.0])
    colors = {"calm": AMBER, "injury": ORANGE, "severe": BLUE, "collapse": "#7B8AA0"}
    left_label_offsets = {"calm": 17, "injury": 3, "severe": -10, "collapse": -24}
    right_label_offsets = {"calm": 12, "injury": -12, "severe": 9, "collapse": -9}
    for regime in regimes:
        reference = float(paired[regime]["reference"]["mean_homeostasis"])
        calibrated = float(paired[regime]["calibrated"]["mean_homeostasis"])
        yy = np.array([reference, calibrated])
        ax.plot(x, yy, color=colors[regime], linewidth=2.8, alpha=0.95)
        ax.scatter(x, yy, s=115, color=colors[regime], edgecolor="white", linewidth=1.6, zorder=3)
        ax.annotate(
            f"{labels[regime]}  {reference:.3f}",
            xy=(x[0], yy[0]),
            xytext=(-12, left_label_offsets[regime]),
            textcoords="offset points",
            ha="right",
            va="center",
            fontsize=12.5,
            color=INK,
        )
        end_outcome = paired[regime]["calibrated"]["outcome"].upper()
        ax.annotate(
            f"{calibrated:.3f}  {end_outcome}",
            xy=(x[1], yy[1]),
            xytext=(12, right_label_offsets[regime]),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=12.5,
            color=INK,
            fontweight="bold" if end_outcome == "STABLE" else "normal",
        )

    ax.set_xlim(-0.38, 1.42)
    ax.set_ylim(0.10, 0.66)
    ax.set_xticks(x, ["参考规则", "预注册标定"])
    ax.set_ylabel("Mean homeostasis（60 ticks）")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", length=0, pad=12)
    fig.suptitle(
        "四档 holdout 均提升；仅 Calm / Injury 改变结局分级",
        x=0.02,
        y=0.95,
        ha="left",
        fontsize=21,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.5,
        0.63,
        "generalized",
        ha="center",
        va="center",
        fontsize=13,
        color=AMBER,
        fontweight="bold",
    )
    add_source_footer(
        fig,
        "同一冻结搜索协议；每档为一个确定性合成压力场景。Severe / Collapse 仍为 FAILED，未为展示效果调参。",
    )
    save_figure(fig, "calibration_holdout_gain")


def plot_intervention() -> None:
    base = (
        ROOT
        / "artifacts"
        / "carm-state-conditioned-intervention"
        / "state-intervention-0e92bb234ba3a840"
        / "raw"
    )
    seeds = (41, 42, 43)
    conditions = ("baseline", "early_short", "late_short", "early_long", "late_long")
    data: dict[str, list[dict[str, float]]] = {condition: [] for condition in conditions}
    outcomes: set[str] = set()
    for condition in conditions:
        for seed in seeds:
            payload = load_json(base / f"{condition}-seed-{seed}.json")
            observation = payload["terminal_observation"]
            data[condition].append({key: float(observation[key]) for key in L4_KEYS})
            outcomes.add(str(payload["phenotype_window"]["outcome"]).upper())
    if outcomes != {"RECOVERED"}:
        raise ValueError(f"Unexpected outcomes: {sorted(outcomes)}")

    means = {
        condition: {key: float(np.mean([row[key] for row in records])) for key in L4_KEYS}
        for condition, records in data.items()
    }
    short_delta = {key: means["late_short"][key] - means["early_short"][key] for key in L4_KEYS}
    long_delta = {key: means["late_long"][key] - means["early_long"][key] for key in L4_KEYS}
    timing_distances = [
        l4_distance(means["early_short"], means["late_short"]),
        l4_distance(means["early_long"], means["late_long"]),
    ]

    fig = plt.figure(figsize=(11.8, 5.25))
    grid = fig.add_gridspec(
        1,
        2,
        width_ratios=[0.78, 1.75],
        wspace=0.25,
        left=0.08,
        right=0.97,
        top=0.72,
        bottom=0.22,
    )
    ax = fig.add_subplot(grid[0, 0])
    ax2 = fig.add_subplot(grid[0, 1])

    bars = ax.bar([0, 1], timing_distances, width=0.58, color=[CYAN, AMBER])
    ax.set_xticks([0, 1], ["短暴露", "长暴露"])
    ax.set_ylabel("早—晚终末 L4 距离")
    ax.set_ylim(0, 0.025)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, timing_distances):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.001, f"{value:.6f}", ha="center", va="bottom", fontsize=12.5, color=INK, fontweight="bold")
    ax.set_title("a  时序差异随暴露长度放大", loc="left", fontweight="bold")

    labels = ["活力", "损伤负担", "炎症", "稳态", "恢复能力"]
    y = np.arange(len(L4_KEYS))
    height = 0.34
    short_values = np.array([short_delta[key] for key in L4_KEYS])
    long_values = np.array([long_delta[key] for key in L4_KEYS])
    ax2.barh(y - height / 2, short_values, height=height, color=CYAN, label="短暴露：晚期−早期")
    ax2.barh(y + height / 2, long_values, height=height, color=AMBER, label="长暴露：晚期−早期")
    ax2.axvline(0, color=INK, linewidth=1.0)
    ax2.set_yticks(y, labels)
    ax2.invert_yaxis()
    ax2.set_xlabel("终末 L4 指标差值（晚期−早期）")
    ax2.set_xlim(-0.015, 0.046)
    ax2.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    ax2.legend(loc="lower right", fontsize=11.0)
    ax2.set_title("b  晚期干预减轻活力/损伤代价，但炎症更高", loc="left", fontweight="bold")
    for yi, values in ((y - height / 2, short_values), (y + height / 2, long_values)):
        for ypos, value in zip(yi, values):
            ha = "left" if value >= 0 else "right"
            shift = 0.0012 if value >= 0 else -0.0012
            ax2.text(value + shift, ypos, f"{value:+.3f}", ha=ha, va="center", fontsize=9.5, color=INK)

    fig.suptitle(
        "状态条件序列干预：可审计 trade-off，而非疗效结论",
        x=0.02,
        y=0.95,
        ha="left",
        fontsize=22,
        fontweight="bold",
        color=INK,
    )
    add_source_footer(
        fig,
        "5 条件 × 3 seeds × 60 ticks；3 个 seed 轨迹完全相同，仅作确定性重放门禁，不报告 CI 或 p 值。全部条件结局为 RECOVERED。",
    )
    save_figure(fig, "intervention_timing_tradeoff")


def main() -> None:
    plot_spatial_ablation()
    plot_calibration()
    plot_intervention()


if __name__ == "__main__":
    main()
