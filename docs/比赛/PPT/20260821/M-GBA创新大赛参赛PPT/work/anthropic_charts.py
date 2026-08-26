# -*- coding: utf-8 -*-
"""
Anthropic 风格图表重绘。
计算口径逐行对齐 visual_assets/generate_scientific_figures.py（权威来源），
数值直接读取 artifacts/ 下 raw JSON，不手写转录。仅替换视觉为 Anthropic 品牌。
"""
import csv, json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = r"D:/projects/M-GBA-main"
ART = os.path.join(ROOT, "artifacts")
OUT = os.path.join(ROOT, r"docs/比赛/PPT/20260821/M-GBA创新大赛参赛PPT/work/charts")
os.makedirs(OUT, exist_ok=True)

# ---- Anthropic palette ----
BG     = "#FAF9F5"
INK    = "#1A1A18"
ACCENT = "#D97757"   # terracotta
ACCENT2= "#B85C3E"   # darker terracotta for secondary series
GRID   = "#DDD9CE"
MUTED  = "#8A867C"
FAINT  = "#C9C4B6"   # neutral bar (reference)

L4_KEYS = ("vitality", "damage_burden", "inflammation", "homeostasis", "recovery_capacity")

for f in ["Microsoft YaHei", "SimHei", "SimSun"]:
    if any(f.lower() in x.name.lower() for x in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 13

def load_json(p):
    with open(p, encoding="utf-8") as h:
        return json.load(h)

def terminal_observation(p):
    obs = load_json(p)["terminal_observation"]
    return {k: float(obs[k]) for k in L4_KEYS}

def l4_distance(a, b):
    return float(np.mean([abs(a[k] - b[k]) for k in L4_KEYS]))

def base_ax(ax):
    ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)
    ax.set_axisbelow(True)

def new_fig(w, h):
    fig = plt.figure(figsize=(w, h), dpi=220)
    fig.patch.set_facecolor(BG)
    return fig

def footer(fig, text):
    fig.text(0.012, 0.014, text, ha="left", va="bottom", fontsize=8.5, color=MUTED)

# ============ P12 空间消融（口径 = 权威脚本 plot_spatial_ablation） ============
def plot_p12():
    base = os.path.join(ART, "carm-spatial-ablation", "carm-spatial-ablation-f53f626b9f3fb9eb", "raw")
    obs = {}
    for m in (0, 1):
        for f in (0, 1):
            for t in (0, 1):
                obs[(m, f, t)] = terminal_observation(os.path.join(base, f"space_m{m}_f{f}_t{t}", "run.json"))
    fixed = terminal_observation(os.path.join(base, "fixed_graph", "run.json"))

    factor_specs = [("场耦合", 1), ("空间邻域", 2), ("移动", 0)]
    factor_values = []
    for _, axis in factor_specs:
        paired = []
        for first in (0, 1):
            for second in (0, 1):
                low = [0, 0, 0]; high = [0, 0, 0]
                other = [i for i in (0, 1, 2) if i != axis]
                low[other[0]] = first; low[other[1]] = second
                high[:] = low; high[axis] = 1
                paired.append(l4_distance(obs[tuple(low)], obs[tuple(high)]))
        factor_values.append(float(np.mean(paired)))

    control_labels = ["全关", "仅移动", "完整空间"]
    control_values = [
        l4_distance(fixed, obs[(0, 0, 0)]),
        l4_distance(fixed, obs[(1, 0, 0)]),
        l4_distance(fixed, obs[(1, 1, 1)]),
    ]
    print("P12 主效应:", dict(zip([s[0] for s in factor_specs], [round(v, 6) for v in factor_values])))
    print("P12 对照:", dict(zip(control_labels, [round(v, 6) for v in control_values])))

    fig = new_fig(11.4, 4.9)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.55, 1.0], wspace=0.30,
                          left=0.09, right=0.97, top=0.74, bottom=0.22)
    ax = fig.add_subplot(gs[0, 0]); base_ax(ax)
    ax2 = fig.add_subplot(gs[0, 1]); base_ax(ax2)

    y = np.arange(len(factor_specs))
    bar_colors = [ACCENT, INK, FAINT]   # 场耦合橙色高亮，其余深炭/浅灰
    bars = ax.barh(y, factor_values, height=0.54, color=bar_colors, edgecolor="none")
    ax.invert_yaxis()
    ax.set_yticks(y, [s[0] for s in factor_specs], color=INK, fontsize=13)
    ax.set_xlim(0, max(factor_values) * 1.24)
    ax.xaxis.grid(True, color=GRID, linewidth=0.7)
    for bar, v in zip(bars, factor_values):
        ax.text(v + max(factor_values)*0.02, bar.get_y()+bar.get_height()/2, f"{v:.6f}",
                ha="left", va="center", fontsize=12, color=INK, fontweight="bold")
    ax.set_title("a  当前杠杆点：场耦合 > 空间邻域 > 移动", loc="left", color=INK, fontsize=13.5, pad=10)

    x = np.arange(len(control_labels))
    ax2.scatter(x, control_values, s=150, color=[FAINT, FAINT, ACCENT],
                edgecolor=BG, linewidth=1.5, zorder=3)
    for xi, v in zip(x, control_values):
        ax2.vlines(xi, 0, v, color=GRID, linewidth=4, zorder=1)
        ax2.text(xi, v + max(control_values)*0.05, f"{v:.6f}", ha="center", va="bottom",
                 fontsize=11, color=INK)
    ax2.axhline(0, color=INK, linewidth=0.8)
    ax2.set_xticks(x, control_labels, color=INK, fontsize=12)
    ax2.set_ylim(min(control_values) - 0.004, max(control_values) * 1.22)
    ax2.yaxis.grid(True, color=GRID, linewidth=0.7)
    ax2.set_title("b  零效应对照保持为零", loc="left", color=INK, fontsize=13.5, pad=10)

    fig.suptitle("L3 机制审计：描述性效应，而非统计或疗效证据", x=0.02, y=0.955,
                 ha="left", fontsize=16, fontweight="bold", color=INK)
    footer(fig, "2×2×2 确定性 L3 审计，20 ticks；每个主效应为 4 组匹配条件的平均绝对 L4 距离。所有 9 个条件结局均为 RECOVERED。数据源：artifacts/carm-spatial-ablation raw run.json")
    fig.savefig(os.path.join(OUT, "p12_ablation.png"), facecolor=BG, bbox_inches="tight")
    plt.close(fig)

# ============ P13 标定 holdout（口径 = 权威脚本 plot_calibration） ============
def plot_p13():
    path = os.path.join(ART, "calibration-l2", "calibration-99ce6e355b8e0afa", "holdout.csv")
    if not os.path.exists(path):
        # 退化：从 holdout.json 重算同名字段
        ho = load_json(path.replace(".csv", ".json"))
        rows = ho["rows"]
    else:
        with open(path, encoding="utf-8-sig", newline="") as h:
            rows = list(csv.DictReader(h))
    regimes = ["calm", "injury", "severe", "collapse"]
    labels = {"calm": "Calm", "injury": "Injury", "severe": "Severe", "collapse": "Collapse"}
    paired = {}
    for r in regimes:
        rec = {}
        for row in rows:
            if row["regime"] == r:
                rec[row["config"]] = row
        paired[r] = rec
    print("P13:", {r: (round(float(paired[r]["reference"]["mean_homeostasis"]), 4),
                        round(float(paired[r]["calibrated"]["mean_homeostasis"]), 4),
                        paired[r]["calibrated"]["outcome"]) for r in regimes})

    fig = new_fig(10.4, 5.0)
    ax = fig.add_subplot(111); base_ax(ax)
    fig.subplots_adjust(left=0.20, right=0.80, top=0.76, bottom=0.18)
    x = np.array([0.0, 1.0])
    colors = {"calm": ACCENT, "injury": ACCENT2, "severe": INK, "collapse": MUTED}
    left_off = {"calm": 14, "injury": -12, "severe": 10, "collapse": -12}
    right_off = {"calm": 12, "injury": -14, "severe": 11, "collapse": -11}
    for r in regimes:
        ref = float(paired[r]["reference"]["mean_homeostasis"])
        cal = float(paired[r]["calibrated"]["mean_homeostasis"])
        yy = np.array([ref, cal])
        ax.plot(x, yy, color=colors[r], linewidth=2.6, alpha=0.95)
        ax.scatter(x, yy, s=110, color=colors[r], edgecolor=BG, linewidth=1.6, zorder=3)
        ax.annotate(f"{labels[r]}  {ref:.3f}", xy=(x[0], yy[0]), xytext=(-14, left_off[r]),
                    textcoords="offset points", ha="right", va="center", fontsize=12, color=INK)
        oc = paired[r]["calibrated"]["outcome"].upper()
        ax.annotate(f"{cal:.3f}  {oc}", xy=(x[1], yy[1]), xytext=(14, right_off[r]),
                    textcoords="offset points", ha="left", va="center", fontsize=12,
                    color=INK, fontweight="bold" if oc == "STABLE" else "normal")
    ax.set_xlim(-0.42, 1.46)
    ax.set_ylim(0.10, 0.66)
    ax.set_xticks(x, ["参考规则", "预注册标定"], color=INK, fontsize=13)
    ax.set_ylabel("Mean homeostasis（60 ticks）", color=INK)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7)
    fig.suptitle("四档 holdout 均提升；仅 Calm / Injury 改变结局分级", x=0.02, y=0.95,
                 ha="left", fontsize=16, fontweight="bold", color=INK)
    footer(fig, "同一冻结搜索协议；每档为一个确定性合成压力场景。Severe / Collapse 仍为 FAILED，未为展示效果调参。数据源：artifacts/calibration-l2 holdout")
    fig.savefig(os.path.join(OUT, "p13_calibration.png"), facecolor=BG, bbox_inches="tight")
    plt.close(fig)

# ============ P16 干预时序（口径 = 权威脚本 plot_intervention） ============
def plot_p16():
    base = os.path.join(ART, "carm-state-conditioned-intervention", "state-intervention-0e92bb234ba3a840", "raw")
    seeds = (41, 42, 43)
    conditions = ("baseline", "early_short", "late_short", "early_long", "late_long")
    data = {c: [] for c in conditions}
    outcomes = set()
    for c in conditions:
        for s in seeds:
            pl = load_json(os.path.join(base, f"{c}-seed-{s}.json"))
            ob = pl["terminal_observation"]
            data[c].append({k: float(ob[k]) for k in L4_KEYS})
            outcomes.add(str(pl["phenotype_window"]["outcome"]).upper())
    assert outcomes == {"RECOVERED"}, outcomes
    means = {c: {k: float(np.mean([r[k] for r in recs])) for k in L4_KEYS} for c, recs in data.items()}
    short_delta = {k: means["late_short"][k] - means["early_short"][k] for k in L4_KEYS}
    long_delta = {k: means["late_long"][k] - means["early_long"][k] for k in L4_KEYS}
    timing = [l4_distance(means["early_short"], means["late_short"]),
              l4_distance(means["early_long"], means["late_long"])]
    print("P16 时序距离:", [round(v, 6) for v in timing])
    print("P16 short_delta:", {k: round(v, 4) for k, v in short_delta.items()})
    print("P16 long_delta:", {k: round(v, 4) for k, v in long_delta.items()})

    fig = new_fig(11.4, 4.9)
    gs = fig.add_gridspec(1, 2, width_ratios=[0.78, 1.75], wspace=0.26,
                          left=0.08, right=0.97, top=0.74, bottom=0.22)
    ax = fig.add_subplot(gs[0, 0]); base_ax(ax)
    ax2 = fig.add_subplot(gs[0, 1]); base_ax(ax2)

    bars = ax.bar([0, 1], timing, width=0.56, color=[INK, ACCENT])
    ax.set_xticks([0, 1], ["短暴露", "长暴露"], color=INK, fontsize=12.5)
    ax.set_ylim(0, max(timing) * 1.28)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7)
    for b, v in zip(bars, timing):
        ax.text(b.get_x()+b.get_width()/2, v + max(timing)*0.03, f"{v:.6f}",
                ha="center", va="bottom", fontsize=12, color=INK, fontweight="bold")
    ax.set_title("a  时序差异随暴露长度放大", loc="left", color=INK, fontsize=13.5, pad=10)

    labels = ["活力", "损伤负担", "炎症", "稳态", "恢复能力"]
    y = np.arange(len(L4_KEYS)); h = 0.34
    sv = np.array([short_delta[k] for k in L4_KEYS])
    lv = np.array([long_delta[k] for k in L4_KEYS])
    ax2.barh(y - h/2, sv, height=h, color=FAINT, label="短暴露：晚期−早期")
    ax2.barh(y + h/2, lv, height=h, color=ACCENT, label="长暴露：晚期−早期")
    ax2.axvline(0, color=INK, linewidth=1.0)
    ax2.set_yticks(y, labels, color=INK, fontsize=12.5)
    ax2.invert_yaxis()
    xmax = float(max(abs(sv).max(), abs(lv).max())) * 1.45
    ax2.set_xlim(-xmax*0.55, xmax)
    ax2.xaxis.grid(True, color=GRID, linewidth=0.7)
    ax2.legend(loc="lower right", fontsize=10.5, frameon=False)
    ax2.set_title("b  晚期干预减轻活力/损伤代价，但炎症更高", loc="left", color=INK, fontsize=13.5, pad=10)
    for yi, values in ((y - h/2, sv), (y + h/2, lv)):
        for yp, v in zip(yi, values):
            ha = "left" if v >= 0 else "right"
            shift = xmax*0.015 if v >= 0 else -xmax*0.015
            ax2.text(v + shift, yp, f"{v:+.3f}", ha=ha, va="center", fontsize=9.5, color=INK)

    fig.suptitle("状态条件序列干预：可审计 trade-off，而非疗效结论", x=0.02, y=0.955,
                 ha="left", fontsize=16, fontweight="bold", color=INK)
    footer(fig, "5 条件 × 3 seeds × 60 ticks；3 个 seed 轨迹完全相同，仅作确定性重放门禁，不报告 CI 或 p 值。全部条件结局为 RECOVERED。数据源：artifacts/carm-state-conditioned-intervention raw")
    fig.savefig(os.path.join(OUT, "p16_intervention.png"), facecolor=BG, bbox_inches="tight")
    plt.close(fig)

if __name__ == "__main__":
    plot_p12()
    plot_p13()
    plot_p16()
