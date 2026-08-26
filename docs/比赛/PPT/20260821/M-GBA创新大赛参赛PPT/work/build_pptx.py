# -*- coding: utf-8 -*-
"""
M-GBA 创新大赛参赛 PPT — Anthropic 风格整体重排。
文案与原 20 页完全一致；图表数值来自 artifacts 重绘结果。
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from PIL import Image

BASE = r"D:/projects/M-GBA-main/docs/比赛/PPT/20260821/M-GBA创新大赛参赛PPT"
CHARTS = os.path.join(BASE, "work", "charts")
ASSETS = os.path.join(BASE, "visual_assets")
OUT = os.path.join(BASE, "M-GBA创新大赛参赛PPT_Anthropic风格版.pptx")

# ---------- palette ----------
BG     = RGBColor(0xFA, 0xF9, 0xF5)
INK    = RGBColor(0x1A, 0x1A, 0x18)
ACCENT = RGBColor(0xD9, 0x77, 0x57)
ACC_D  = RGBColor(0xB8, 0x5C, 0x3E)
MUTED  = RGBColor(0x8A, 0x86, 0x7C)
LINE   = RGBColor(0xDD, 0xD9, 0xCE)
CARD   = RGBColor(0xF3, 0xF1, 0xEA)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)

TITLE_CN, TITLE_EN = "思源宋体", "Georgia"
BODY_CN, BODY_EN = "微软雅黑", "Arial"

EMU_W, EMU_H = Inches(13.333), Inches(7.5)

prs = Presentation()
prs.slide_width, prs.slide_height = EMU_W, EMU_H
BLANK = prs.slide_layouts[6]

def slide():
    return prs.slides.add_slide(BLANK)

def bg(s, color=BG):
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = color

def _ea(run, font):
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        e = rPr.find(qn(tag))
        if e is None:
            e = rPr.makeelement(qn(tag), {})
            rPr.append(e)
        e.set("typeface", font)

def _latin(run, font):
    run.font.name = font

def text(s, x, y, w, h, content, size=14, color=INK, bold=False, italic=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.12,
         space_after=4, wrap=True):
    """content: str 或 [(txt, {size,color,bold,italic,en}), ...] 或 [[runs...], [runs...]] 多段落"""
    tb = s.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if isinstance(content, str):
        content = [[(content, {})]]
    elif content and isinstance(content[0], tuple):
        content = [content]
    for i, runs in enumerate(content):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        for txt, st in runs:
            r = p.add_run()
            r.text = txt
            sz = st.get("size", size)
            r.font.size = Pt(sz)
            r.font.bold = st.get("bold", bold)
            r.font.italic = st.get("italic", italic)
            r.font.color.rgb = st.get("color", color)
            cn = st.get("cn", BODY_CN)
            en = st.get("en", BODY_EN if st.get("latin") else cn)
            if st.get("serif"):
                cn, en = TITLE_CN, TITLE_EN
            _latin(r, en)
            _ea(r, cn)
    return tb

def rect(s, x, y, w, h, fill=None, line=None, line_w=0.75, shadow=False, round_=False, radius=0.08):
    shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE, x, y, w, h)
    if round_:
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(line_w)
    shp.shadow.inherit = False
    return shp

def hline(s, x, y, w, color=LINE, weight=0.75):
    ln = s.shapes.add_connector(1, x, y, x + w, y)
    ln.line.color.rgb = color
    ln.line.width = Pt(weight)
    ln.shadow.inherit = False
    return ln

def arrow(s, x1, y1, x2, y2, color=ACCENT, weight=1.5):
    ln = s.shapes.add_connector(1, x1, y1, x2, y2)
    ln.line.color.rgb = color
    ln.line.width = Pt(weight)
    ln.shadow.inherit = False
    le = ln.line._get_or_add_ln()
    e = le.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    le.append(e)
    return ln

def picture_fit(s, path, x, y, w, h):
    """把图片等比缩放居中放入 (x,y,w,h) 区域。"""
    iw, ih = Image.open(path).size
    box_r, img_r = w / h, iw / ih
    if img_r > box_r:
        nw, nh = w, int(w / img_r)
    else:
        nh, nw = h, int(h * img_r)
    return s.shapes.add_picture(path, int(x + (w - nw) / 2), int(y + (h - nh) / 2), nw, nh)

PAGE = [0]
def chrome(s, chapter=None, section=None, title=None, page=True):
    """内容页页眉：章节标签 + 大标题 + 页码 + 顶部分隔线。"""
    if chapter:
        text(s, Inches(0.75), Inches(0.42), Inches(9), Inches(0.3),
             [[(chapter, {"size": 11, "color": ACCENT, "bold": True, "latin": True})]])
    if title:
        text(s, Inches(0.75), Inches(0.70), Inches(11.8), Inches(0.75),
             [[(title, {"size": 30, "bold": True, "serif": True})]])
    if page:
        PAGE[0] += 1
        text(s, Inches(12.35), Inches(7.02), Inches(0.6), Inches(0.3),
             [[(f"{PAGE[0]:02d}", {"size": 10, "color": MUTED, "latin": True})]], align=PP_ALIGN.RIGHT)
        text(s, Inches(0.75), Inches(7.02), Inches(5), Inches(0.3),
             [[("M-GBA · 跨尺度数字生命计算架构", {"size": 9, "color": MUTED})]])

def chapter_page(no, title_cn, sub):
    s = slide(); bg(s)
    text(s, Inches(0.9), Inches(1.7), Inches(3), Inches(2.2),
         [[(no, {"size": 120, "color": ACCENT, "bold": True, "latin": True, "serif": True})]])
    hline(s, Inches(0.95), Inches(4.05), Inches(2.2), color=INK, weight=1.5)
    text(s, Inches(0.95), Inches(4.3), Inches(11), Inches(1.0),
         [[(title_cn, {"size": 44, "bold": True, "serif": True})]])
    text(s, Inches(0.95), Inches(5.35), Inches(11), Inches(0.8),
         [[(sub, {"size": 16, "color": MUTED})]])
    return s

def card(s, x, y, w, h, fill=CARD, line=None):
    return rect(s, x, y, w, h, fill=fill, line=line, round_=True, radius=0.055)

# ============================================================ 01 封面
s = slide(); bg(s)
text(s, Inches(0.9), Inches(0.75), Inches(11.5), Inches(0.35),
     [[("M-GBA · MULTI-SCALE GRAPH BIOLOGICAL ARCHITECTURE", {"size": 12, "color": MUTED, "latin": True, "bold": True})]])
hline(s, Inches(0.9), Inches(1.15), Inches(11.53), color=LINE)
text(s, Inches(0.9), Inches(2.25), Inches(11.5), Inches(1.7),
     [[("M-GBA 多尺度数字生命计算架构", {"size": 54, "bold": True, "serif": True})]])
text(s, Inches(0.9), Inches(3.75), Inches(11.5), Inches(0.9),
     [[("让生命的生成", {"size": 26, "serif": True}),
       ("可计算、可复现、可审计", {"size": 26, "serif": True, "color": ACCENT, "bold": True})]])
hline(s, Inches(0.9), Inches(5.35), Inches(11.53), color=LINE)
text(s, Inches(0.9), Inches(5.6), Inches(11.5), Inches(0.4),
     [[("中国国际大学生创新大赛（2026） · 高教主赛道 · 人工智能+ · 本科生创意组", {"size": 14, "color": INK})]])
text(s, Inches(0.9), Inches(6.05), Inches(11.5), Inches(0.4),
     [[("华南理工大学参赛团队", {"size": 14, "color": MUTED})]])

# ============================================================ 02 目录
s = slide(); bg(s)
text(s, Inches(0.9), Inches(0.7), Inches(8), Inches(0.9),
     [[("目录 ", {"size": 40, "bold": True, "serif": True}), ("CONTENTS", {"size": 16, "color": MUTED, "latin": True, "bold": True})]])
toc = [
    ("01", "问题与机遇", "跨尺度鸿沟与 AI for Science 政策窗口"),
    ("02", "五层跨尺度架构", "L0→L4 纵向生成、三类信息流与可替换模型库"),
    ("03", "实验证据与诚实治理", "扰动贯通五层、配对对照标定与负面基线保留"),
    ("04", "应用场景与路线图", "在硅预筛、教学平台、三阶段路线与参赛合规"),
]
y = Inches(1.95)
for no, t, d in toc:
    text(s, Inches(0.9), y, Inches(1.1), Inches(0.9), [[(no, {"size": 34, "color": ACCENT, "bold": True, "latin": True, "serif": True})]])
    text(s, Inches(2.2), y + Inches(0.02), Inches(10), Inches(0.5), [[(t, {"size": 22, "bold": True, "serif": True})]])
    text(s, Inches(2.2), y + Inches(0.55), Inches(10), Inches(0.4), [[(d, {"size": 13, "color": MUTED})]])
    y += Inches(1.06)
    if no != "04":
        hline(s, Inches(0.9), y - Inches(0.14), Inches(11.53), color=LINE)
text(s, Inches(0.9), Inches(6.9), Inches(3), Inches(0.3), [[("M-GBA", {"size": 10, "color": MUTED, "latin": True, "bold": True})]])

# ============================================================ 03 章节页 1
chapter_page("01", "问题与机遇", "从湿实验与黑盒模型的双重痛点，到人工智能赋能科学研究的政策窗口")

# ============================================================ 04 跨尺度鸿沟
s = slide(); bg(s)
chrome(s, "CHAPTER 01 · PROBLEM", title="生命科学的跨尺度鸿沟")
col_y, col_h = Inches(1.75), Inches(4.35)
for i, (head, items) in enumerate([
    ("湿实验范式", [("跨尺度观测难：", "难以在同一实验中连续追踪从微观调控到宏观表型的生成过程"),
                    ("周期成本高：", "实验迭代慢、资源消耗大，策略空间无法充分探索"),
                    ("干预不可遍历：", "剂量、时序等策略组合数量爆炸，湿实验无法穷尽")]),
    ("现有计算模型", [("黑盒：", "端到端模型内部机制不可解释，难获科研与监管信任"),
                      ("缺层间审计：", "无法在轨迹中定位每次跨层转换，依赖事后故事解释"),
                      ("宏观答案直写：", "宏观指标被直接编码进目标函数，而非由局部交互生成")]),
]):
    x = Inches(0.75) + i * Inches(6.05)
    card(s, x, col_y, Inches(5.8), col_h)
    text(s, x + Inches(0.4), col_y + Inches(0.35), Inches(5), Inches(0.5),
         [[(head, {"size": 19, "bold": True, "serif": True})]])
    hline(s, x + Inches(0.4), col_y + Inches(0.95), Inches(5.0), color=LINE)
    yy = col_y + Inches(1.2)
    for k, v in items:
        text(s, x + Inches(0.4), yy, Inches(5.05), Inches(0.95),
             [[(k, {"size": 13.5, "bold": True, "color": ACC_D})], [(v, {"size": 13.5})]],
             space_after=2)
        yy += Inches(1.0)
bar = card(s, Inches(0.75), Inches(6.3), Inches(11.85), Inches(0.62), fill=INK)
text(s, Inches(0.75), Inches(6.3), Inches(11.85), Inches(0.62),
     [[("双重痛点 → 需要一种可运行、可审计的跨尺度计算范式", {"size": 15, "color": RGBColor(0xFA,0xF9,0xF5), "bold": True})]],
     align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 05 政策窗口
s = slide(); bg(s)
chrome(s, "CHAPTER 01 · POLICY", title="政策窗口：AI for Science 进入下半场")
pol = [
    ("国家", "《关于深入实施“人工智能+”行动的意见》", "“人工智能+”科学技术被列为首要任务", "国务院 · 国发〔2025〕11号"),
    ("广东", "《加快推动人工智能赋能科学研究行动方案（2026—2030年）》", "生命科学列为七大重点领域之一", "广东省科技厅 · 2026-06"),
    ("北京", "《加快推进人工智能赋能科学研究实施方案（2026—2028年）》", "构建跨尺度生物分子设计、生成、模拟与优化的模型体系", "北京市教科人才工作领导小组 · 2026-07"),
]
y = Inches(1.75)
for tag, name, point, src in pol:
    card(s, Inches(0.75), y, Inches(11.85), Inches(1.18))
    text(s, Inches(1.05), y + Inches(0.30), Inches(1.2), Inches(0.6),
         [[(tag, {"size": 18, "bold": True, "color": ACCENT})]])
    text(s, Inches(2.35), y + Inches(0.16), Inches(10.1), Inches(0.45),
         [[(name, {"size": 13.5, "bold": True})]])
    text(s, Inches(2.35), y + Inches(0.58), Inches(10.1), Inches(0.4),
         [[(point, {"size": 12.5, "color": ACC_D}), ("    " + src, {"size": 11, "color": MUTED})]])
    y += Inches(1.32)
q = card(s, Inches(0.75), Inches(5.85), Inches(11.85), Inches(1.15), fill=WHITE, line=LINE)
text(s, Inches(1.15), Inches(6.05), Inches(11), Inches(0.55),
     [[("“AI for Science 已进入下半场，重心正从人工智能方法探索，转向科研体系的系统性变革。”",
        {"size": 14.5, "italic": True, "serif": True})]])
text(s, Inches(1.15), Inches(6.58), Inches(11), Inches(0.35),
     [[("—— 鄂维南 院士 · 2026 科学智能大会（国际科技创新中心网络服务平台 2026-08-21）", {"size": 11, "color": MUTED})]])

# ============================================================ 06 章节页 2
chapter_page("02", "五层跨尺度架构", "从基因调控到宏观表型的逐层生成，多智能体与 STEN 只是子问题")

# ============================================================ 07 五层架构图
s = slide(); bg(s)
chrome(s, "CHAPTER 02 · FIVE-SCALE ARCHITECTURE", title="L0→L4 五层纵向生成架构")
layers = [
    ("L4", "有机体宏观表型", "OrganismState"),
    ("L3", "组织、环境场与动态拓扑", "TissueState"),
    ("L2", "细胞个体行为", "CellState / Action"),
    ("L1", "分子 / 蛋白状态", "MolecularState"),
    ("L0", "基因 / 转录调控", "TranscriptState"),
]
bx, bw = Inches(2.1), Inches(6.6)
y = Inches(1.8); bh, gap = Inches(0.82), Inches(0.22)
centers = []
for i, (tag, name, dto) in enumerate(layers):
    top = (i == 0)
    c = card(s, bx, y, bw, bh, fill=INK if top else CARD)
    text(s, bx + Inches(0.35), y, Inches(1.0), bh,
         [[(tag, {"size": 20, "bold": True, "latin": True, "color": ACCENT if top else ACC_D})]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, bx + Inches(1.35), y, Inches(5.1), bh,
         [[(name, {"size": 15, "bold": True, "color": RGBColor(0xFA,0xF9,0xF5) if top else INK})]],
         anchor=MSO_ANCHOR.MIDDLE)
    centers.append(y + bh / 2)
    if i < 4:
        arrow(s, bx + Inches(1.0), y + bh + Inches(0.045), bx + Inches(1.0), y + bh + gap - Inches(0.045), color=ACCENT, weight=1.75)
        dto_map = ["L3→L4：TissueState → OrganismState", "L2→L3：CellAction → TissueState",
                   "L1→L2：MolecularState → CellState / Action", "L0→L1：TranscriptState → MolecularState"]
        text(s, bx + Inches(1.3), y + bh - Inches(0.012), Inches(5.2), Inches(0.26),
             [[(dto_map[i], {"size": 10.5, "color": MUTED})]], anchor=MSO_ANCHOR.MIDDLE)
    y += bh + gap
# 右侧注释
nx = Inches(9.35)
text(s, nx, Inches(2.0), Inches(3.3), Inches(0.4), [[("相邻层契约不可跳过", {"size": 14, "bold": True, "color": ACC_D})]])
hline(s, nx, Inches(2.42), Inches(3.0), color=LINE)
text(s, nx, Inches(2.6), Inches(3.35), Inches(2.4),
     [[("上行是主生成流；L4 只经低频约束反馈，不直接指定 L2 动作。", {"size": 12.5})]], line_spacing=1.35)
text(s, nx, Inches(4.15), Inches(3.35), Inches(1.2),
     [[("概念示意图 · 五层职责与相邻 DTO/Protocol 以项目核心原则为准", {"size": 10.5, "color": MUTED})]], line_spacing=1.3)
# 下行反馈虚线注释
text(s, nx, Inches(5.1), Inches(3.35), Inches(1.2),
     [[("↓ L4→L3 低频约束反馈", {"size": 11.5, "bold": True, "color": MUTED})],
      [("慢于上行、受安全屏障限制", {"size": 10.5, "color": MUTED})]], space_after=2)

# ============================================================ 08 三类信息流
s = slide(); bg(s)
chrome(s, "CHAPTER 02 · INFORMATION FLOWS", title="三类信息流与不跳层协议")
flows = [
    ("↑", "上行生成流 · 主线", "L0 调控 → L1 分子状态 → L2 细胞行为 → L3 组织动力学 → L4 宏观表型；任何 MVP 都必须完整贯通这条路径。"),
    ("◌", "层内交互流", "多智能体表达 L2 细胞个体，STEN 表达 L3 语义通信与组织拓扑；二者均为实现五层递进的子问题，不取代项目本体。"),
    ("↓", "下行约束流", "L4 不直接编写细胞答案，只改变环境压力与资源边界；必须慢于上行、可审计、受安全屏障限制，从不指定 L2 动作。"),
]
y = Inches(1.8)
for sym, head, body in flows:
    card(s, Inches(0.75), y, Inches(11.85), Inches(1.32))
    text(s, Inches(1.1), y + Inches(0.18), Inches(0.8), Inches(0.95),
         [[(sym, {"size": 30, "color": ACCENT, "bold": True, "latin": True})]])
    text(s, Inches(2.05), y + Inches(0.2), Inches(10.2), Inches(0.4),
         [[(head, {"size": 15.5, "bold": True, "serif": True})]])
    text(s, Inches(2.05), y + Inches(0.64), Inches(10.2), Inches(0.6),
         [[(body, {"size": 12.5})]], line_spacing=1.25)
    y += Inches(1.48)
bar = card(s, Inches(0.75), Inches(6.28), Inches(11.85), Inches(0.66), fill=WHITE, line=ACCENT)
text(s, Inches(1.1), Inches(6.28), Inches(11.2), Inches(0.66),
     [[("上行是主线，下行慢于上行且从不指定 L2 动作　—　", {"size": 12.5, "bold": True, "color": ACC_D}),
       ("L4→L3 反馈仅经 FeedbackConstraint 改变资源上限与压力地板，逐 tick 哈希链留痕", {"size": 12, "color": INK})]],
     anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 09 模型库
s = slide(); bg(s)
chrome(s, "CHAPTER 02 · MODEL LIBRARY", title="可控替换的层模型库与双基线哲学")
lib = [
    ("L2", "主动推理策略", "预期自由能最小化（风险+歧义分解、确定性 argmin、无采样）", "五态规则状态机"),
    ("L2", "连续潜状态“虚拟细胞”", "冻结种子派生权重 + 泄漏 tanh 递推，潜状态每 tick 从正式 CellState 重建、无隐藏记忆", "五态规则状态机"),
    ("L3", "受治理动态拓扑 / 冻结权重 GNN", "提案→授权→提交、T1 式边交换、入度守恒；GNN 不改拓扑、不进反馈闭环", "固定有向图"),
    ("L0", "种子化转录噪声 / 冻结权重 MLP", "sha256(seed|cell|time) 派生噪声流，checkpoint 精确恢复；MLP 权重由显式种子派生而非训练", "六节点确定性离散 GRN"),
]
y = Inches(1.72)
for tag, name, desc, base in lib:
    card(s, Inches(0.75), y, Inches(11.85), Inches(1.08))
    text(s, Inches(1.05), y + Inches(0.28), Inches(0.75), Inches(0.5),
         [[(tag, {"size": 16, "bold": True, "color": ACCENT, "latin": True})]])
    text(s, Inches(1.85), y + Inches(0.13), Inches(6.6), Inches(0.4),
         [[(name, {"size": 13.5, "bold": True})]])
    text(s, Inches(1.85), y + Inches(0.52), Inches(6.7), Inches(0.5),
         [[(desc, {"size": 10.5, "color": MUTED})]], line_spacing=1.15)
    text(s, Inches(8.85), y + Inches(0.13), Inches(3.5), Inches(0.35),
         [[("永久基线", {"size": 10, "color": MUTED, "bold": True})]])
    text(s, Inches(8.85), y + Inches(0.45), Inches(3.5), Inches(0.5),
         [[(base, {"size": 12.5, "bold": True, "color": ACC_D})]])
    y += Inches(1.2)
text(s, Inches(0.75), Inches(6.55), Inches(11.85), Inches(0.5),
     [[("双基线哲学：", {"size": 13.5, "bold": True, "color": ACC_D}),
       ("任何新模型先回答六个准入问题，失败可移除而不破坏其他层", {"size": 13.5})]])

# ============================================================ 10 CAR-M 锚定
s = slide(); bg(s)
chrome(s, "CHAPTER 02 · CAR-M ANCHOR", title="CAR-M 真实数据锚定与因果空间扩展")
pts = [
    ("数据锚定：", "752 个样本 GAT 预测去标识聚合，high/low/normal = 323/273/156，代理标签非临床真值"),
    ("纵向贯通：", "63 个 Cell 固定图贯通 CAR 信号程序 L0→L4，21-run 矩阵验证三层消融与 checkpoint 恢复"),
    ("因果空间 L3：", "归一化坐标 + 12×12 压力/资源/信号场 + 半径邻域全部入 trace/checkpoint；无量纲 reference model，非物理扩散"),
    ("外部预注册：", "Wu/Swarbrick Visium 三文件 + Jackson IMC 两文件（约 241MB），Rights 核验 CC BY 4.0 / CC BY 1.0"),
    ("负面基线：", "高剂量炎症上升、负担代理略升，原样保留不为展示调参"),
]
y = Inches(1.85)
for k, v in pts:
    text(s, Inches(0.8), y, Inches(6.4), Inches(0.95),
         [[(k, {"size": 13, "bold": True, "color": ACC_D})], [(v, {"size": 12.5})]],
         space_after=2, line_spacing=1.2)
    y += Inches(0.98)
img = os.path.join(ASSETS, "carm_tumor_microenvironment_concept.png")
fr = rect(s, Inches(7.45), Inches(1.8), Inches(5.15), Inches(3.35), fill=WHITE, line=LINE)
picture_fit(s, img, Inches(7.5), Inches(1.85), Inches(5.05), Inches(3.25))
text(s, Inches(7.45), Inches(5.3), Inches(5.15), Inches(0.6),
     [[("概念示意图（非显微证据） · 代理标签非临床真值 · 冻结基线不变", {"size": 10.5, "color": MUTED})]], line_spacing=1.25)

# ============================================================ 11 章节页 3
chapter_page("03", "实验证据与诚实治理", "一次扰动能否逐层抵达宏观表型？负面结果又如何诚实表述？")

# ============================================================ 12 跨尺度传播（图表）
s = slide(); bg(s)
chrome(s, "CHAPTER 03 · CROSS-SCALE PROPAGATION", title="跨尺度传播：一次扰动贯通五层")
picture_fit(s, os.path.join(CHARTS, "p12_ablation.png"), Inches(0.75), Inches(1.72), Inches(11.85), Inches(4.75))
text(s, Inches(0.75), Inches(6.6), Inches(11.85), Inches(0.45),
     [[("证据结论：场耦合优先。全关与仅移动均保持零效应；以上仅为当前 reference model 内的描述性机制审计。",
        {"size": 12.5, "color": ACC_D, "bold": True})]])

# ============================================================ 13 标定结果（图表）
s = slide(); bg(s)
chrome(s, "CHAPTER 03 · VERIFICATION EVIDENCE", title="标定结果：提升与失败边界同时可见")
picture_fit(s, os.path.join(CHARTS, "p13_calibration.png"), Inches(0.75), Inches(1.72), Inches(9.3), Inches(4.4))
stats = [("356", "工程门禁测试"), ("21-run", "实验矩阵"), ("752", "CAR-M profile 代理样本"), ("0.2076→0.5927", "训练目标提升")]
y = Inches(1.85)
for num, lab in stats:
    text(s, Inches(10.35), y, Inches(2.4), Inches(0.5),
         [[(num, {"size": 17, "bold": True, "color": ACCENT, "latin": True})]], align=PP_ALIGN.LEFT)
    text(s, Inches(10.35), y + Inches(0.42), Inches(2.4), Inches(0.4),
         [[(lab, {"size": 11, "color": MUTED})]])
    y += Inches(0.98)
text(s, Inches(0.75), Inches(6.55), Inches(11.85), Inches(0.5),
     [[("四档 holdout 全部提升：Calm / Injury 由 FAILED → STABLE，Severe / Collapse 仍为 FAILED；冻结搜索协议、失败结果原样保留。",
        {"size": 12, "color": ACC_D, "bold": True})]])

# ============================================================ 14 诚实治理
s = slide(); bg(s)
chrome(s, "CHAPTER 03 · GOVERNANCE", title="可观测、可复现与诚实治理体系")
col1 = [("逐 tick trace：", "记录每次跨层转换事件，不依赖事后解释"),
        ("位级恢复：", "JSON checkpoint 支持确定性断点恢复"),
        ("SHA-256 manifest：", "固定配置、模型与代码版本"),
        ("raw-only 重建：", "报告从冻结 artifact 字节级重建 CSV/SVG/HTML"),
        ("精确复现：", "相同微观配置与种子产出相同轨迹")]
col2 = [("负面基线保留：", "默认 100 tick 结局 FAILED，不为展示调参"),
        ("预注册冻结：", "判据与 holdout 在协议中先行固定"),
        ("五级表述分级：", "contract demonstrator → validated result 逐级晋升"),
        ("ADR 留痕：", "34 份架构决策记录“为什么做、如何回退”"),
        ("fail-closed 门禁：", "数据登记任一条目校验失败即非零退出")]
for i, (head, items) in enumerate([("可观测 · 可复现", col1), ("诚实治理", col2)]):
    x = Inches(0.75) + i * Inches(6.05)
    card(s, x, Inches(1.72), Inches(5.8), Inches(4.7))
    text(s, x + Inches(0.4), Inches(2.0), Inches(5), Inches(0.5),
         [[(head, {"size": 18, "bold": True, "serif": True})]])
    hline(s, x + Inches(0.4), Inches(2.6), Inches(5.0), color=LINE)
    yy = Inches(2.78)
    for k, v in items:
        text(s, x + Inches(0.4), yy, Inches(5.05), Inches(0.75),
             [[(k, {"size": 12, "bold": True, "color": ACC_D}), (v, {"size": 12})]], line_spacing=1.18)
        yy += Inches(0.74)
text(s, Inches(0.75), Inches(6.62), Inches(11.85), Inches(0.45),
     [[("参考模型 ≠ 已验证结论 · 表述分级是项目对评委与读者的承诺", {"size": 13, "bold": True, "color": ACC_D})]])

# ============================================================ 15 章节页 4
chapter_page("04", "应用场景与路线图", "在硅预筛、教学平台、三阶段路线与参赛合规")

# ============================================================ 16 应用一（图表）
s = slide(); bg(s)
chrome(s, "CHAPTER 04 · APPLICATION I", title="应用 I：状态条件干预的时序决策支持")
picture_fit(s, os.path.join(CHARTS, "p16_intervention.png"), Inches(0.75), Inches(1.72), Inches(11.85), Inches(4.55))
text(s, Inches(0.75), Inches(6.5), Inches(11.85), Inches(0.6),
     [[("面向可审计决策，而非疗效预测：", {"size": 12.5, "bold": True, "color": ACC_D}),
       ("用于比较机制、记录 trade-off、辅助下一轮预注册；不输出临床疗效结论。5 条件 × 3 重放 seeds × 60 ticks，不报告 CI 或 p 值。", {"size": 12})]],
     line_spacing=1.25)

# ============================================================ 17 应用二
s = slide(); bg(s)
chrome(s, "CHAPTER 04 · APPLICATION II", title="应用二 · 跨尺度研究范式与教学平台")
apps = [
    ("01", "跨尺度研究范式平台", "五层 DTO/Protocol 冻结契约 + 可替换模型库；新模型按六问准入接入，层内替换不改变五层协议。"),
    ("02", "教学与双创训练", "逐层可观测 trace 与 CAR-M 研究观察台：baseline/干预双画布同 tick 对照、配对 L4 曲线、逐细胞跨层差异与事件审计，适配系统生物学与 AI4S 教学。"),
    ("03", "数据治理标杆", "registry.json 统一登记 + data-check fail-closed 门禁；TCGA 只输出 cohort 聚合；外部数据 Rights 核验 CC BY 4.0 / 1.0，可作科研数据合规示范。"),
    ("04", "可复现科学基础设施", "空虚拟环境 wheel 复现、SHA-256 manifest 固定输出、raw-only 报告链字节级重建 CSV/SVG/HTML。"),
]
y = Inches(1.78)
for no, head, body in apps:
    card(s, Inches(0.75), y, Inches(11.85), Inches(1.08))
    text(s, Inches(1.05), y + Inches(0.24), Inches(0.75), Inches(0.6),
         [[(no, {"size": 20, "bold": True, "color": ACCENT, "latin": True})]])
    text(s, Inches(1.95), y + Inches(0.14), Inches(10.3), Inches(0.4),
         [[(head, {"size": 14.5, "bold": True, "serif": True})]])
    text(s, Inches(1.95), y + Inches(0.53), Inches(10.35), Inches(0.5),
         [[(body, {"size": 11.5, "color": RGBColor(0x44,0x41,0x3B)})]], line_spacing=1.2)
    y += Inches(1.2)
text(s, Inches(0.75), Inches(6.62), Inches(11.85), Inches(0.4),
     [[("五层契约冻结 · 新模型六问准入 · 数据 fail-closed 门禁", {"size": 12.5, "color": MUTED, "bold": True})]])

# ============================================================ 18 路线图
s = slide(); bg(s)
chrome(s, "CHAPTER 04 · ROADMAP", title="三阶段发展路线图")
stages = [
    ("01 · 近期", "外部锚定首验", ["经授权下载 Wu/Jackson 五文件最小集，生成真实 target 并执行首次 reference score",
                                "calibration 选择与一次性 holdout / external validation 均按冻结协议输出后，才允许 L3 参数锚定"]),
    ("02 · 中期", "逐层受控升级", ["L2/L3 模型按六问准入协议在永久基线上隔离替换升级",
                                "开放 autolab-propose 的 LLM 假设提案入口：fail-closed、永不自动执行"]),
    ("03 · 远期", "平台化开放", ["更多细胞治疗场景接入，教学与竞赛训练推广",
                              "论文发表与开源社区，持续以 reference model 与五级表述对外沟通"]),
]
x = Inches(0.75)
for i, (ph, head, items) in enumerate(stages):
    card(s, x, Inches(1.85), Inches(3.75), Inches(4.35))
    text(s, x + Inches(0.35), Inches(2.15), Inches(3.1), Inches(0.4),
         [[(ph, {"size": 12.5, "bold": True, "color": ACCENT})]])
    text(s, x + Inches(0.35), Inches(2.55), Inches(3.1), Inches(0.55),
         [[(head, {"size": 19, "bold": True, "serif": True})]])
    hline(s, x + Inches(0.35), Inches(3.2), Inches(3.05), color=LINE)
    yy = Inches(3.4)
    for it in items:
        text(s, x + Inches(0.35), yy, Inches(3.1), Inches(1.3),
             [[("· ", {"size": 12, "color": ACCENT, "bold": True}), (it, {"size": 11.5})]], line_spacing=1.25)
        yy += Inches(1.35)
    if i < 2:
        arrow(s, x + Inches(3.78), Inches(4.0), x + Inches(4.24), Inches(4.0), color=ACCENT, weight=2.0)
    x += Inches(4.05)
text(s, Inches(0.75), Inches(6.55), Inches(11.85), Inches(0.45),
     [[("每一步都以冻结协议与诚实表述为前提", {"size": 13.5, "bold": True, "color": ACC_D})]])

# ============================================================ 19 合规
s = slide(); bg(s)
chrome(s, "CHAPTER 04 · COMPLIANCE", title="参赛组别、团队构成与合规说明")
blocks = [
    ("组别", [("赛道类别", "高教主赛道“人工智能+”类 · 本科生组创意组"),
              ("阶段", "项目未完成工商等各类登记注册，具较好创意与较成型产品原型")]),
    ("团队", [("构成", "负责人及成员均为全日制在校本专科生，3–15 人，须为实际核心成员"),
              ("名单", "团队成员与分工（待填）")]),
    ("知识产权与数据合规", [("代码", "自主研发，核心仅依赖 Python 标准库"),
              ("数据", "TCGA cohort 去标识聚合；外部空间数据 CC BY 4.0 / CC BY 1.0，不涉密、不涉患者级记录")]),
    ("科学表述合规", [("边界", "不宣称数字生命、DNA 设计或临床预测能力；涌现按五级术语不越级"),
              ("基线", "负面基线原样保留，不为展示效果调参")]),
]
pos = [(0.75, 1.72), (6.8, 1.72), (0.75, 3.85), (6.8, 3.85)]
for (px, py), (head, items) in zip(pos, blocks):
    card(s, Inches(px), Inches(py), Inches(5.8), Inches(1.95))
    text(s, Inches(px + 0.35), Inches(py + 0.2), Inches(5.1), Inches(0.4),
         [[(head, {"size": 15, "bold": True, "serif": True})]])
    hline(s, Inches(px + 0.35), Inches(py + 0.66), Inches(5.1), color=LINE)
    yy = Inches(py + 0.8)
    for k, v in items:
        text(s, Inches(px + 0.35), yy, Inches(5.15), Inches(0.6),
             [[(k + "　", {"size": 11.5, "bold": True, "color": ACC_D}), (v, {"size": 11.5})]], line_spacing=1.18)
        yy += Inches(0.56)
text(s, Inches(0.75), Inches(6.15), Inches(11.85), Inches(0.4),
     [[("依据《关于举办中国国际大学生创新大赛（2026）校赛的通知》", {"size": 11.5, "color": MUTED})]])

# ============================================================ 20 封底
s = slide(); bg(s)
text(s, Inches(0.9), Inches(2.15), Inches(11.5), Inches(1.4),
     [[("让生命的生成 ", {"size": 40, "serif": True, "color": INK}),
       ("可计算 · 可复现 · 可审计", {"size": 40, "serif": True, "bold": True, "color": ACCENT})]])
hline(s, Inches(0.9), Inches(3.7), Inches(3.0), color=ACCENT, weight=2)
text(s, Inches(0.9), Inches(4.0), Inches(11.5), Inches(0.5),
     [[("M-GBA · 跨尺度数字生命计算架构", {"size": 16, "color": INK})]])
text(s, Inches(0.9), Inches(4.6), Inches(11.5), Inches(0.5),
     [[("致谢 · Q&A", {"size": 14, "color": MUTED})]])
hline(s, Inches(0.9), Inches(6.35), Inches(11.53), color=LINE)
text(s, Inches(0.9), Inches(6.55), Inches(11.5), Inches(0.4),
     [[("华南理工大学参赛团队 · 联系方式（待填）", {"size": 12, "color": MUTED})]])

prs.save(OUT)
print("saved:", OUT, "slides:", len(prs.slides.__iter__.__self__._sldIdLst))
