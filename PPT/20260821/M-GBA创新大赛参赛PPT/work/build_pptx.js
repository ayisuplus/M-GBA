const { PptxGenJS, path, fs, SLIDE_W, SLIDE_H, imgOpts, gradientMaskB64 } = require("./build_header.js");

const C = { canvas: "0A0A0F", layer2: "12121A", card: "1A1A24", ink: "FAFAFA", accent: "F59E0B", zinc: "71717A", edge: "26262E" };
const FONTS = { display: "微软雅黑", body: "微软雅黑", mono: "Courier New" };
const FS = { display: 48, h1: 30, h2: 22, body: 14, small: 12, label: 12 };
const R = 0.17;

const IMGMAP = (() => { try { return JSON.parse(fs.readFileSync(path.join(__dirname, "img_map.json"), "utf8")); } catch (e) { return {}; } })();
function imgPath(key) { const m = IMGMAP[key]; if (!m || m.failed || !m.src) return null; const p = path.resolve(__dirname, m.src); return fs.existsSync(p) ? p : null; }

const deck = new PptxGenJS();
deck.layout = "LAYOUT_WIDE";
deck.title = `M-GBA 多尺度数字生命计算架构`;
deck.author = `华南理工大学参赛团队`;

function contentBg(s) {
  const p = imgPath("bg_content");
  if (p) { s.background = { path: p }; s.addShape("rect", { x: 0, y: 0, w: SLIDE_W, h: SLIDE_H, fill: { color: C.canvas, transparency: 15 }, line: { type: "none" } }); }
  else {
    s.background = { color: C.canvas };
    orb(s, 11.2, -0.8, 2.6);
  }
}
function orb(s, cx, cy, r) {
  const layers = [[r, 96], [r * 0.66, 92], [r * 0.36, 86]];
  for (const [rr, tr] of layers) {
    s.addShape("ellipse", { x: cx - rr, y: cy - rr, w: rr * 2, h: rr * 2, fill: { color: C.accent, transparency: tr }, line: { type: "none" } });
  }
}
function glass(s, x, y, w, h, opts = {}) {
  s.addShape("roundRect", { x, y, w, h, rectRadius: R, fill: { color: C.card, transparency: opts.solid ? 0 : 40 }, line: { color: "FFFFFF", width: 1, transparency: 92 } });
}
function glow(s, x, y, w, h) {
  s.addShape("roundRect", { x, y, w, h, rectRadius: R, fill: { type: "none" }, line: { color: C.accent, width: 1, transparency: 72 }, shadow: { type: "outer", blur: 24, offset: 0, angle: 0, color: C.accent, opacity: 0.22 } });
}
function header(s, kicker, title) {
  s.addText(kicker, { x: 0.7, y: 0.42, w: 9, h: 0.32, fontFace: FONTS.mono, fontSize: FS.label, charSpacing: 2, color: C.accent, margin: 0, valign: "top" });
  s.addText(title, { x: 0.7, y: 0.78, w: 11.9, h: 0.62, fontFace: FONTS.display, fontSize: FS.h1, bold: true, color: C.ink, margin: 0, valign: "top" });
  s.addShape("rect", { x: 0.72, y: 1.46, w: 0.9, h: 0.045, fill: { color: C.accent }, line: { type: "none" } });
}
function foot(s, n, note) {
  if (note) s.addText(note, { x: 0.7, y: 7.02, w: 9.5, h: 0.3, fontFace: FONTS.mono, fontSize: 11, color: C.zinc, margin: 0, valign: "middle" });
  s.addText(String(n).padStart(2, "0"), { x: SLIDE_W - 1.4, y: 7.02, w: 0.7, h: 0.3, fontFace: FONTS.mono, fontSize: 11, color: C.zinc, align: "right", margin: 0, valign: "middle" });
}
function bulletRuns(s, items, x, y, w, h, extra = {}) {
  s.addText(items, { x, y, w, h, fontFace: FONTS.body, fontSize: FS.body, color: C.ink, margin: 0, valign: "top", lineSpacingMultiple: 1.3, paraSpaceAfter: 8, ...extra });
}

// ═══ P1 封面 ═══
{
  const s = deck.addSlide();
  const cov = imgPath("cover_main");
  if (cov) {
    s.background = { path: cov };
    s.addImage({ data: gradientMaskB64({ w: 1280, h: 418, color: C.canvas, dir: "bottom", stops: [[0, 1], [0.5, 0.78], [1, 0]] }), x: 0, y: SLIDE_H * 0.42, w: SLIDE_W, h: SLIDE_H * 0.58 });
    s.addImage({ data: gradientMaskB64({ w: 1024, h: 928, color: C.canvas, dir: "right", stops: [[0, 0.92], [0.55, 0.45], [1, 0]] }), x: 0, y: 0, w: SLIDE_W * 0.62, h: SLIDE_H });
  } else {
    s.background = { color: C.canvas };
    orb(s, 9.6, 1.6, 3.2);
    orb(s, 3.2, 5.8, 2.2);
  }
  s.addText(`M-GBA · MULTI-SCALE GRAPH BIOLOGICAL ARCHITECTURE`, { x: 0.9, y: 3.0, w: 10, h: 0.34, fontFace: FONTS.mono, fontSize: 13, charSpacing: 2, color: C.accent, margin: 0 });
  s.addShape("ellipse", { x: 0.94, y: 2.62, w: 0.12, h: 0.12, fill: { color: C.accent }, line: { type: "none" }, shadow: { type: "outer", blur: 18, offset: 0, angle: 0, color: C.accent, opacity: 0.5 } });
  s.addText(`M-GBA 多尺度数字生命计算架构`, { x: 0.9, y: 3.44, w: 11.5, h: 1.0, fontFace: FONTS.display, fontSize: 46, bold: true, color: C.ink, margin: 0, charSpacing: -1 });
  s.addText(`让生命的生成可计算、可复现、可审计`, { x: 0.92, y: 4.52, w: 10, h: 0.5, fontFace: FONTS.body, fontSize: 20, color: C.ink, margin: 0 });
  s.addShape("rect", { x: 0.94, y: 5.35, w: 11.5, h: 0.012, fill: { color: "FFFFFF", transparency: 88 }, line: { type: "none" } });
  s.addText(`中国国际大学生创新大赛（2026） · 高教主赛道 · 人工智能+ · 本科生创意组`, { x: 0.9, y: 5.6, w: 9, h: 0.34, fontFace: FONTS.body, fontSize: 13, color: C.zinc, margin: 0 });
  s.addText(`华南理工大学参赛团队`, { x: 0.9, y: 5.98, w: 9, h: 0.34, fontFace: FONTS.body, fontSize: 13, color: C.zinc, margin: 0 });
}

// ═══ P2 目录 ═══
{
  const s = deck.addSlide();
  contentBg(s);
  s.addText(`目录 · CONTENTS`, { x: 0.7, y: 0.6, w: 8, h: 0.6, fontFace: FONTS.display, fontSize: 28, bold: true, color: C.ink, margin: 0 });
  s.addShape("rect", { x: 0.72, y: 1.28, w: 0.9, h: 0.045, fill: { color: C.accent }, line: { type: "none" } });
  const items = [
    ["01", `问题与机遇`, `跨尺度鸿沟与 AI for Science 政策窗口`],
    ["02", `五层跨尺度架构`, `L0→L4 纵向生成、三类信息流与可替换模型库`],
    ["03", `实验证据与诚实治理`, `扰动贯通五层、配对对照标定与负面基线保留`],
    ["04", `应用场景与路线图`, `在硅预筛、教学平台、三阶段路线与参赛合规`],
  ];
  let y = 1.85;
  for (const [no, t, d] of items) {
    s.addText(no, { x: 0.8, y: y - 0.12, w: 1.3, h: 0.95, fontFace: FONTS.mono, fontSize: 40, bold: true, color: C.accent, margin: 0, valign: "middle" });
    s.addText(t, { x: 2.3, y: y, w: 7.5, h: 0.5, fontFace: FONTS.display, fontSize: 22, bold: true, color: C.ink, margin: 0, valign: "top" });
    s.addText(d, { x: 2.3, y: y + 0.52, w: 8.6, h: 0.4, fontFace: FONTS.body, fontSize: 13, color: C.zinc, margin: 0, valign: "top" });
    s.addShape("rect", { x: 0.8, y: y + 1.06, w: 10.3, h: 0.012, fill: { color: "FFFFFF", transparency: 88 }, line: { type: "none" } });
    y += 1.28;
  }
  s.addText(`M-GBA`, { x: 11.3, y: 2.2, w: 1.6, h: 4.6, fontFace: FONTS.mono, fontSize: 30, color: C.zinc, align: "center", valign: "middle", charSpacing: 6, margin: 0 });
  s.addShape("rect", { x: 12.05, y: 1.9, w: 0.012, h: 5.0, fill: { color: "FFFFFF", transparency: 88 }, line: { type: "none" } });
}

// ═══ P3 章节页 第一章 ═══
{
  const s = deck.addSlide();
  s.background = { color: C.layer2 };
  orb(s, 10.6, 1.4, 2.8);
  s.addText(`01`, { x: 8.6, y: 3.4, w: 4.2, h: 3.4, fontFace: FONTS.mono, fontSize: 150, bold: true, color: C.card, align: "right", margin: 0, valign: "bottom" });
  s.addText(`第一章 · CHAPTER 01`, { x: 0.9, y: 2.6, w: 8, h: 0.36, fontFace: FONTS.mono, fontSize: 13, charSpacing: 2, color: C.accent, margin: 0 });
  s.addText(`问题与机遇`, { x: 0.9, y: 3.1, w: 9, h: 1.0, fontFace: FONTS.display, fontSize: 44, bold: true, color: C.ink, margin: 0 });
  s.addShape("rect", { x: 0.94, y: 4.25, w: 1.2, h: 0.05, fill: { color: C.accent }, line: { type: "none" } });
  s.addText(`从湿实验与黑盒模型的双重痛点，到人工智能赋能科学研究的政策窗口`, { x: 0.9, y: 4.55, w: 9.5, h: 0.5, fontFace: FONTS.body, fontSize: 15, color: C.zinc, margin: 0 });
}

// ═══ P4 跨尺度鸿沟（双栏对比） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 01 · PROBLEM`, `生命科学的跨尺度鸿沟`);
  const cols = [
    [`湿实验范式`, [
      [`跨尺度观测难：`, `难以在同一实验中连续追踪从微观调控到宏观表型的生成过程`],
      [`周期成本高：`, `实验迭代慢、资源消耗大，策略空间无法充分探索`],
      [`干预不可遍历：`, `剂量、时序等策略组合数量爆炸，湿实验无法穷尽`],
    ]],
    [`现有计算模型`, [
      [`黑盒：`, `端到端模型内部机制不可解释，难获科研与监管信任`],
      [`缺层间审计：`, `无法在轨迹中定位每次跨层转换，依赖事后故事解释`],
      [`宏观答案直写：`, `宏观指标被直接编码进目标函数，而非由局部交互生成`],
    ]],
  ];
  const xs = [0.7, 6.95];
  cols.forEach(([t, rows], i) => {
    glass(s, xs[i], 1.85, 5.68, 4.55);
    s.addText(t, { x: xs[i] + 0.45, y: 2.15, w: 4.8, h: 0.5, fontFace: FONTS.display, fontSize: 19, bold: true, color: C.accent, margin: 0, valign: "top" });
    s.addShape("rect", { x: xs[i] + 0.47, y: 2.72, w: 0.7, h: 0.03, fill: { color: C.accent, transparency: 40 }, line: { type: "none" } });
    const runs = [];
    rows.forEach(([k, v], j) => {
      runs.push({ text: k, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } });
      runs.push({ text: v, options: { color: C.zinc, breakLine: j < rows.length - 1 } });
    });
    bulletRuns(s, runs, xs[i] + 0.45, 3.0, 4.8, 3.2);
  });
  s.addShape("rect", { x: 6.63, y: 2.2, w: 0.012, h: 3.9, fill: { color: "FFFFFF", transparency: 85 }, line: { type: "none" } });
  foot(s, 4, `双重痛点 → 需要一种可运行、可审计的跨尺度计算范式`);
}

// ═══ P5 政策窗口（图标行 3 + 引言） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 01 · POLICY`, `政策窗口：AI for Science 进入下半场`);
  const pol = [
    [`国家`, `《关于深入实施“人工智能+”行动的意见》`, `“人工智能+”科学技术被列为首要任务`, `国务院 · 国发〔2025〕11号`],
    [`广东`, `《加快推动人工智能赋能科学研究行动方案（2026—2030年）》`, `生命科学列为七大重点领域之一`, `广东省科技厅 · 2026-06`],
    [`北京`, `《加快推进人工智能赋能科学研究实施方案（2026—2028年）》`, `构建跨尺度生物分子设计、生成、模拟与优化的模型体系`, `北京市教科人才工作领导小组 · 2026-07`],
  ];
  pol.forEach(([tag, name, point, src], i) => {
    const x = 0.7 + i * 4.06;
    glass(s, x, 1.9, 3.8, 3.35);
    s.addText(tag, { x: x + 0.35, y: 2.15, w: 2.0, h: 0.34, fontFace: FONTS.mono, fontSize: 12, charSpacing: 2, color: C.accent, margin: 0, valign: "top" });
    s.addText(name, { x: x + 0.35, y: 2.55, w: 3.1, h: 1.25, fontFace: FONTS.display, fontSize: 14.5, bold: true, color: C.ink, margin: 0, valign: "top", lineSpacingMultiple: 1.25 });
    s.addText(point, { x: x + 0.35, y: 3.85, w: 3.1, h: 0.85, fontFace: FONTS.body, fontSize: 12.5, color: C.zinc, margin: 0, valign: "top", lineSpacingMultiple: 1.3 });
    s.addText(src, { x: x + 0.35, y: 4.72, w: 3.1, h: 0.3, fontFace: FONTS.mono, fontSize: 10.5, color: C.zinc, margin: 0, valign: "top" });
  });
  glass(s, 0.7, 5.6, 11.93, 1.25);
  s.addShape("rect", { x: 0.7, y: 5.6, w: 0.05, h: 1.25, fill: { color: C.accent }, line: { type: "none" } });
  s.addText([
    { text: `“AI for Science 已进入下半场，重心正从人工智能方法探索，转向科研体系的系统性变革。”`, options: { color: C.ink, fontSize: 15, breakLine: true } },
    { text: `—— 鄂维南 院士 · 2026 科学智能大会（国际科技创新中心网络服务平台 2026-08-21）`, options: { color: C.zinc, fontSize: 11.5 } },
  ], { x: 1.1, y: 5.78, w: 11.2, h: 0.95, fontFace: FONTS.body, margin: 0, valign: "middle", lineSpacingMultiple: 1.35 });
  foot(s, 5);
}

// ═══ P6 章节页 第二章 ═══
{
  const s = deck.addSlide();
  s.background = { color: C.layer2 };
  orb(s, 2.6, 6.2, 2.6);
  s.addText(`02`, { x: 8.6, y: 3.4, w: 4.2, h: 3.4, fontFace: FONTS.mono, fontSize: 150, bold: true, color: C.card, align: "right", margin: 0, valign: "bottom" });
  s.addText(`第二章 · CHAPTER 02`, { x: 0.9, y: 2.6, w: 8, h: 0.36, fontFace: FONTS.mono, fontSize: 13, charSpacing: 2, color: C.accent, margin: 0 });
  s.addText(`五层跨尺度架构`, { x: 0.9, y: 3.1, w: 9, h: 1.0, fontFace: FONTS.display, fontSize: 44, bold: true, color: C.ink, margin: 0 });
  s.addShape("rect", { x: 0.94, y: 4.25, w: 1.2, h: 0.05, fill: { color: C.accent }, line: { type: "none" } });
  s.addText(`从基因调控到宏观表型的逐层生成，多智能体与 STEN 只是子问题`, { x: 0.9, y: 4.55, w: 9.8, h: 0.5, fontFace: FONTS.body, fontSize: 15, color: C.zinc, margin: 0 });
}

// ═══ P7 五层纵向生成架构 ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 02 · ARCHITECTURE`, `L0→L4 五层纵向生成架构`);
  const layers = [
    [`L0`, `基因与转录调控`, `细胞具有什么潜在能力，哪些能力正在表达？`, `TranscriptState`],
    [`L1`, `分子与蛋白状态`, `当前表达形成了哪些受体、酶和信号能力？`, `MolecularState`],
    [`L2`, `细胞个体`, `分子状态如何改变细胞感知、状态转换和行为？`, `CellState · CellAction`],
    [`L3`, `组织与语义拓扑`, `局部细胞行为如何改变相互作用网络和微环境？`, `TissueState · 场`],
    [`L4`, `有机体宏观表型`, `组织状态最终形成什么整体稳定性、功能或失衡？`, `OrganismState`],
  ];
  s.addShape("rect", { x: 1.34, y: 2.15, w: 0.02, h: 4.15, fill: { color: C.accent, transparency: 55 }, line: { type: "none" } });
  layers.forEach(([no, name, q, dto], i) => {
    const y = 1.95 + i * 0.88;
    s.addShape("ellipse", { x: 1.24, y: y + 0.18, w: 0.22, h: 0.22, fill: { color: C.accent }, line: { type: "none" }, shadow: { type: "outer", blur: 14, offset: 0, angle: 0, color: C.accent, opacity: 0.35 } });
    s.addText([
      { text: no + `  `, options: { bold: true, color: C.accent, fontFace: FONTS.mono, fontSize: 15 } },
      { text: name, options: { bold: true, color: C.ink, fontSize: 16 } },
    ], { x: 1.75, y: y + 0.05, w: 3.3, h: 0.5, margin: 0, valign: "middle", fontFace: FONTS.display });
    s.addText(q, { x: 5.15, y: y + 0.05, w: 4.7, h: 0.5, fontFace: FONTS.body, fontSize: 12.5, color: C.zinc, margin: 0, valign: "middle", lineSpacingMultiple: 1.2 });
    s.addText(dto, { x: 9.95, y: y + 0.05, w: 2.7, h: 0.5, fontFace: FONTS.mono, fontSize: 11.5, color: C.accent, align: "right", margin: 0, valign: "middle" });
    if (i < 4) s.addShape("rect", { x: 5.15, y: y + 0.66, w: 7.5, h: 0.008, fill: { color: "FFFFFF", transparency: 90 }, line: { type: "none" } });
  });
  glass(s, 0.7, 6.5, 11.93, 0.5);
  s.addText(`硬约束：每层只消费下层显式输出，禁止跳层读取“上帝参数”（L2 不得绕过 L1 直读基因值）`, { x: 1.0, y: 6.5, w: 11.3, h: 0.5, fontFace: FONTS.body, fontSize: 13, bold: true, color: C.accent, margin: 0, valign: "middle" });
  foot(s, 7);
}

// ═══ P8 三类信息流 ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 02 · INFORMATION FLOWS`, `三类信息流与不跳层协议`);
  const flows = [
    [`↑`, `上行生成流 · 主线`, `L0 调控 → L1 分子状态 → L2 细胞行为 → L3 组织动力学 → L4 宏观表型；任何 MVP 都必须完整贯通这条路径。`],
    [`◌`, `层内交互流`, `多智能体表达 L2 细胞个体，STEN 表达 L3 语义通信与组织拓扑；二者均为实现五层递进的子问题，不取代项目本体。`],
    [`↓`, `下行约束流`, `L4 不直接编写细胞答案，只改变环境压力与资源边界；必须慢于上行、可审计、受安全屏障限制，从不指定 L2 动作。`],
  ];
  flows.forEach(([g, t, d], i) => {
    const x = 0.7 + i * 4.06;
    glass(s, x, 1.9, 3.8, 3.3, i === 0 ? {} : {});
    if (i === 0) glow(s, x, 1.9, 3.8, 3.3);
    s.addShape("ellipse", { x: x + 0.35, y: 2.2, w: 0.52, h: 0.52, fill: { color: C.card }, line: { color: C.accent, width: 1, transparency: 45 } });
    s.addText(g, { x: x + 0.35, y: 2.2, w: 0.52, h: 0.52, fontFace: FONTS.mono, fontSize: 18, color: C.accent, align: "center", valign: "middle", margin: 0 });
    s.addText(t, { x: x + 0.35, y: 2.92, w: 3.1, h: 0.45, fontFace: FONTS.display, fontSize: 16, bold: true, color: C.ink, margin: 0, valign: "top" });
    s.addText(d, { x: x + 0.35, y: 3.45, w: 3.1, h: 1.6, fontFace: FONTS.body, fontSize: 12.5, color: C.zinc, margin: 0, valign: "top", lineSpacingMultiple: 1.35 });
  });
  glass(s, 0.7, 5.65, 11.93, 1.15);
  s.addText(`上行是主线，下行慢于上行且从不指定 L2 动作`, { x: 0.7, y: 5.78, w: 11.93, h: 0.5, fontFace: FONTS.display, fontSize: 18, bold: true, color: C.ink, align: "center", margin: 0, valign: "middle" });
  s.addText(`L4→L3 反馈仅经 FeedbackConstraint 改变资源上限与压力地板，逐 tick 哈希链留痕`, { x: 1.2, y: 6.28, w: 10.9, h: 0.4, fontFace: FONTS.body, fontSize: 12, color: C.zinc, align: "center", margin: 0, valign: "top" });
  foot(s, 8);
}

// ═══ P9 层模型库 2×2 ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 02 · MODEL LIBRARY`, `可控替换的层模型库与双基线哲学`);
  const cells = [
    [`L2`, `主动推理策略`, `预期自由能最小化（风险+歧义分解、确定性 argmin、无采样）`, `五态规则状态机`],
    [`L2`, `连续潜状态“虚拟细胞”`, `冻结种子派生权重 + 泄漏 tanh 递推，潜状态每 tick 从正式 CellState 重建、无隐藏记忆`, `五态规则状态机`],
    [`L3`, `受治理动态拓扑 / 冻结权重 GNN`, `提案→授权→提交、T1 式边交换、入度守恒；GNN 不改拓扑、不进反馈闭环`, `固定有向图`],
    [`L0`, `种子化转录噪声 / 冻结权重 MLP`, `sha256(seed|cell|time) 派生噪声流，checkpoint 精确恢复；MLP 权重由显式种子派生而非训练`, `六节点确定性离散 GRN`],
  ];
  cells.forEach(([tag, t, v, b], i) => {
    const x = 0.7 + (i % 2) * 6.12;
    const y = 1.85 + Math.floor(i / 2) * 2.28;
    glass(s, x, y, 5.86, 2.08);
    s.addText(tag, { x: x + 0.35, y: y + 0.22, w: 0.7, h: 0.36, fontFace: FONTS.mono, fontSize: 12, bold: true, color: C.accent, align: "center", valign: "middle", margin: 0, fill: { color: C.edge } });
    s.addText(t, { x: x + 1.2, y: y + 0.2, w: 4.3, h: 0.4, fontFace: FONTS.display, fontSize: 15.5, bold: true, color: C.ink, margin: 0, valign: "middle" });
    s.addText(v, { x: x + 0.35, y: y + 0.72, w: 5.16, h: 0.8, fontFace: FONTS.body, fontSize: 11.5, color: C.zinc, margin: 0, valign: "top", lineSpacingMultiple: 1.25 });
    s.addShape("rect", { x: x + 0.35, y: y + 1.55, w: 5.16, h: 0.008, fill: { color: "FFFFFF", transparency: 88 }, line: { type: "none" } });
    s.addText([
      { text: `永久基线  `, options: { color: C.zinc, fontSize: 11 } },
      { text: b, options: { color: C.accent, fontSize: 11.5, bold: true } },
    ], { x: x + 0.35, y: y + 1.62, w: 5.16, h: 0.32, fontFace: FONTS.body, margin: 0, valign: "top" });
  });
  glass(s, 0.7, 6.42, 11.93, 0.55);
  s.addText(`双基线哲学：任何新模型先回答六个准入问题，失败可移除而不破坏其他层`, { x: 1.0, y: 6.42, w: 11.3, h: 0.55, fontFace: FONTS.body, fontSize: 13, bold: true, color: C.ink, margin: 0, valign: "middle" });
  foot(s, 9);
}

// ═══ P10 CAR-M 数据锚定（数据卡 + 要点，无图布局） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 02 · CAR-M ANCHOR`, `CAR-M 真实数据锚定与因果空间扩展`);
  const carImg = imgOpts("p10_carm", 0.7, 1.9, 4.7, 4.7);
  if (carImg) {
    s.addShape("roundRect", { x: 0.7, y: 1.9, w: 4.7, h: 4.7, rectRadius: R, fill: { color: C.card }, line: { color: "FFFFFF", width: 1, transparency: 90 } });
    s.addImage(carImg);
  }
  const runs = [
    { text: `数据锚定：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `752 个样本 GAT 预测去标识聚合，high/low/normal = 323/273/156，代理标签非临床真值`, options: { color: C.zinc, breakLine: true } },
    { text: `纵向贯通：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `63 个 Cell 固定图贯通 CAR 信号程序 L0→L4，21-run 矩阵验证三层消融与 checkpoint 恢复`, options: { color: C.zinc, breakLine: true } },
    { text: `因果空间 L3：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `归一化坐标 + 12×12 压力/资源/信号场 + 半径邻域全部入 trace/checkpoint；无量纲 reference model，非物理扩散`, options: { color: C.zinc, breakLine: true } },
    { text: `外部预注册：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `Wu/Swarbrick Visium 三文件 + Jackson IMC 两文件（约 241MB），Rights 核验 CC BY 4.0 / CC BY 1.0`, options: { color: C.zinc, breakLine: true } },
    { text: `负面基线：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `高剂量炎症上升、负担代理略升，原样保留不为展示调参`, options: { color: C.zinc } },
  ];
  bulletRuns(s, runs, 5.75, 1.95, 6.88, 4.6, { fontSize: 12.5, lineSpacingMultiple: 1.35, paraSpaceAfter: 9, valign: "middle" });
  foot(s, 10, `代理标签非临床真值 · 固定图基线与冻结矩阵不变`);
}

// ═══ P11 章节页 第三章 ═══
{
  const s = deck.addSlide();
  s.background = { color: C.layer2 };
  orb(s, 10.8, 6.0, 2.7);
  s.addText(`03`, { x: 8.6, y: 3.4, w: 4.2, h: 3.4, fontFace: FONTS.mono, fontSize: 150, bold: true, color: C.card, align: "right", margin: 0, valign: "bottom" });
  s.addText(`第三章 · CHAPTER 03`, { x: 0.9, y: 2.6, w: 8, h: 0.36, fontFace: FONTS.mono, fontSize: 13, charSpacing: 2, color: C.accent, margin: 0 });
  s.addText(`实验证据与诚实治理`, { x: 0.9, y: 3.1, w: 10, h: 1.0, fontFace: FONTS.display, fontSize: 44, bold: true, color: C.ink, margin: 0 });
  s.addShape("rect", { x: 0.94, y: 4.25, w: 1.2, h: 0.05, fill: { color: C.accent }, line: { type: "none" } });
  s.addText(`一次扰动能否逐层抵达宏观表型？负面结果又如何诚实表述？`, { x: 0.9, y: 4.55, w: 10, h: 0.5, fontFace: FONTS.body, fontSize: 15, color: C.zinc, margin: 0 });
}

// ═══ P12 跨尺度传播（柱状图 + 洞察） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 03 · CROSS-SCALE PROPAGATION`, `跨尺度传播：一次扰动贯通五层`);
  s.addChart(deck.charts.BAR, [{
    name: `描述性主效应（L4 距离）`,
    labels: [`场耦合`, `空间邻域`, `移动`],
    values: [0.04872, 0.025588, 0.000898],
  }], {
    x: 0.7, y: 1.8, w: 7.3, h: 4.5, barDir: "col",
    chartColors: [C.accent],
    chartArea: { fill: { color: C.card }, roundedCorners: true },
    catAxisLabelColor: C.zinc, valAxisLabelColor: C.zinc,
    catAxisLabelFontSize: 12, valAxisLabelFontSize: 10,
    valGridLine: { color: C.edge, size: 0.5 }, catGridLine: { style: "none" },
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: C.ink, dataLabelFontSize: 11,
    showLegend: false, showTitle: false,
  });
  glass(s, 8.3, 1.8, 4.33, 4.5);
  s.addText(`当前杠杆点在场耦合与邻域，而非移动`, { x: 8.65, y: 2.1, w: 3.65, h: 0.9, fontFace: FONTS.display, fontSize: 17, bold: true, color: C.ink, margin: 0, valign: "top", lineSpacingMultiple: 1.25 });
  s.addShape("rect", { x: 8.67, y: 3.12, w: 0.7, h: 0.03, fill: { color: C.accent }, line: { type: "none" } });
  const runs = [
    { text: `跨层可定位：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `WP8 验证一次 L0 修复表达敲低依次改变 L1/L2/L3/L4，每次跨层转换可在轨迹中定位`, options: { color: C.zinc, breakLine: true } },
    { text: `零效应负对照：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `2×2×2 机制审计中全关与仅移动均为 L3/L4 零效应，效应并非来自移动本身`, options: { color: C.zinc } },
  ];
  bulletRuns(s, runs, 8.65, 3.4, 3.65, 2.7, { fontSize: 12 });
  foot(s, 12, `CAR-M 空间 L3 机制审计 · 20 tick 描述性主效应，非统计检验或疗效证据`);
}

// ═══ P13 对照替换与标定（大数字卡 ×4） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 03 · CONTROLLED EXPERIMENTS`, `对照替换与参数标定实验`);
  const cards = [
    [`0.2076→0.5927`, `L2 标定训练得分`, `四档 holdout 全部提升，判定 generalized`, true],
    [`298`, `自动化测试项`, `覆盖五层契约、冻结矩阵与实验协议`, false],
    [`21`, `CAR-M 冻结矩阵 run`, `7 条件 × 3 seed，raw trace 全保存`, false],
    [`752`, `TCGA-BRCA 聚合样本`, `去标识化聚合 profile，非患者级记录`, false],
  ];
  cards.forEach(([n, l, d, hot], i) => {
    const x = 0.7 + i * 3.03;
    glass(s, x, 1.9, 2.83, 2.55);
    if (hot) glow(s, x, 1.9, 2.83, 2.55);
    s.addText(n, { x: x + 0.22, y: 2.15, w: 2.4, h: 0.95, fontFace: FONTS.display, fontSize: n.length > 8 ? 24 : 34, bold: true, color: hot ? C.accent : C.ink, margin: 0, valign: "top" });
    s.addText(l, { x: x + 0.22, y: 3.15, w: 2.4, h: 0.4, fontFace: FONTS.body, fontSize: 12, bold: true, color: C.ink, margin: 0, valign: "top" });
    s.addText(d, { x: x + 0.22, y: 3.55, w: 2.4, h: 0.75, fontFace: FONTS.body, fontSize: 10.5, color: C.zinc, margin: 0, valign: "top", lineSpacingMultiple: 1.25 });
  });
  const runs = [
    { text: `单层归因：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `配对对照矩阵强制两个 runner 仅在单一层不同，跨层效应可归因到具体层；标定采用预注册搜索（sha256 种子扫描 + 坐标细化，参考向量恒为首评点），结果不进入冻结协议`, options: { color: C.zinc, breakLine: true } },
    { text: `克制表述：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `E3 多种子噪声集合按预注册判据分级，出现 emergence_candidate 时严格按五级术语表述，不越级宣称已验证的涌现`, options: { color: C.zinc } },
  ];
  bulletRuns(s, runs, 0.7, 4.85, 11.93, 1.8, { fontSize: 13 });
  foot(s, 13);
}

// ═══ P14 可观测可复现 vs 诚实治理（双栏） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 03 · GOVERNANCE`, `可观测、可复现与诚实治理体系`);
  const mk = (items) => {
    const runs = [];
    items.forEach(([k, v], j) => {
      runs.push({ text: k, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } });
      runs.push({ text: v, options: { color: C.zinc, breakLine: j < items.length - 1 } });
    });
    return runs;
  };
  glass(s, 0.7, 1.85, 5.68, 4.6);
  s.addText(`可观测 · 可复现`, { x: 1.15, y: 2.1, w: 4.8, h: 0.45, fontFace: FONTS.display, fontSize: 18, bold: true, color: C.accent, margin: 0, valign: "top" });
  bulletRuns(s, mk([
    [`逐 tick trace：`, `记录每次跨层转换事件，不依赖事后解释`],
    [`位级恢复：`, `JSON checkpoint 支持确定性断点恢复`],
    [`SHA-256 manifest：`, `固定配置、模型与代码版本`],
    [`raw-only 重建：`, `报告从冻结 artifact 字节级重建 CSV/SVG/HTML`],
    [`精确复现：`, `相同微观配置与种子产出相同轨迹`],
  ]), 1.15, 2.8, 4.8, 3.4, { fontSize: 13, lineSpacingMultiple: 1.45, paraSpaceAfter: 10 });
  glass(s, 6.95, 1.85, 5.68, 4.6);
  s.addText(`诚实治理`, { x: 7.4, y: 2.1, w: 4.8, h: 0.45, fontFace: FONTS.display, fontSize: 18, bold: true, color: C.accent, margin: 0, valign: "top" });
  bulletRuns(s, mk([
    [`负面基线保留：`, `默认 100 tick 结局 FAILED，不为展示调参`],
    [`预注册冻结：`, `判据与 holdout 在协议中先行固定`],
    [`五级表述分级：`, `contract demonstrator → validated result 逐级晋升`],
    [`ADR 留痕：`, `29 份架构决策记录“为什么做、如何回退”`],
    [`fail-closed 门禁：`, `数据登记任一条目校验失败即非零退出`],
  ]), 7.4, 2.8, 4.8, 3.4, { fontSize: 13, lineSpacingMultiple: 1.45, paraSpaceAfter: 10 });
  s.addShape("rect", { x: 6.63, y: 2.2, w: 0.012, h: 3.9, fill: { color: C.accent, transparency: 55 }, line: { type: "none" } });
  foot(s, 14, `参考模型 ≠ 已验证结论 · 表述分级是项目对评委与读者的承诺`);
}

// ═══ P15 章节页 第四章 ═══
{
  const s = deck.addSlide();
  s.background = { color: C.layer2 };
  orb(s, 2.4, 1.4, 2.4);
  s.addText(`04`, { x: 8.6, y: 3.4, w: 4.2, h: 3.4, fontFace: FONTS.mono, fontSize: 150, bold: true, color: C.card, align: "right", margin: 0, valign: "bottom" });
  s.addText(`第四章 · CHAPTER 04`, { x: 0.9, y: 2.6, w: 8, h: 0.36, fontFace: FONTS.mono, fontSize: 13, charSpacing: 2, color: C.accent, margin: 0 });
  s.addText(`应用场景与路线图`, { x: 0.9, y: 3.1, w: 10, h: 1.0, fontFace: FONTS.display, fontSize: 44, bold: true, color: C.ink, margin: 0 });
  s.addShape("rect", { x: 0.94, y: 4.25, w: 1.2, h: 0.05, fill: { color: C.accent }, line: { type: "none" } });
  s.addText(`在硅预筛、教学平台、三阶段路线与参赛合规`, { x: 0.9, y: 4.55, w: 10, h: 0.5, fontFace: FONTS.body, fontSize: 15, color: C.zinc, margin: 0 });
}

// ═══ P16 应用一（左要点 + 右大数字卡，无图布局） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 04 · APPLICATION I`, `应用一 · 细胞治疗的在硅预筛与机制审计`);
  s.addText(`定位：干湿闭环的在硅预筛助手与机制审计台，辅助缩小湿实验的剂量/时序搜索空间，不宣称疗效预测。`, { x: 0.7, y: 1.85, w: 6.2, h: 0.9, fontFace: FONTS.body, fontSize: 13.5, bold: true, color: C.ink, margin: 0, valign: "top", lineSpacingMultiple: 1.35 });
  const runs = [
    { text: `状态条件序列对照：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `同一批工程化巨噬细胞施加等剂量、等暴露次数的 early/late L0 脉冲，晚期条件在 onset 前与 baseline 逐层零差异`, options: { color: C.zinc, breakLine: true } },
    { text: `timing trade-off：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `晚期干预减轻 vitality/damage 代价但提高 inflammation，全部条件 RECOVERED`, options: { color: C.zinc, breakLine: true } },
    { text: `2×2×2 机制审计：`, options: { bold: true, color: C.ink, bullet: { code: "25CF", color: C.accent }, breakLine: false } },
    { text: `movement×field×topology 全关与仅移动均为零效应负对照，定位场耦合为当前最大杠杆点`, options: { color: C.zinc } },
  ];
  bulletRuns(s, runs, 0.7, 2.85, 6.4, 2.5, { fontSize: 12.5 });
  const cards = [[`0.006580`, `short timing contrast`], [`0.020899`, `long timing contrast`], [`0.048720`, `场耦合主效应`]];
  cards.forEach(([n, a], i) => {
    const x = 0.7 + i * 2.17;
    glass(s, x, 5.55, 2.02, 1.05);
    if (i === 2) glow(s, x, 5.55, 2.02, 1.05);
    s.addText(n, { x: x + 0.12, y: 5.63, w: 1.78, h: 0.55, fontFace: FONTS.display, fontSize: 17, bold: true, color: C.accent, margin: 0, valign: "middle" });
    s.addText(a, { x: x + 0.12, y: 6.16, w: 1.78, h: 0.35, fontFace: FONTS.body, fontSize: 9.5, color: C.zinc, margin: 0, valign: "top" });
  });
  const scrImg = imgOpts("p16_screen", 7.6, 1.85, 4.7, 4.7);
  if (scrImg) {
    s.addShape("roundRect", { x: 7.6, y: 1.85, w: 4.7, h: 4.7, rectRadius: R, fill: { color: C.card }, line: { color: "FFFFFF", width: 1, transparency: 90 } });
    s.addImage(scrImg);
    s.addText(`在硅仿真观察台 · baseline/干预同 tick 对照`, { x: 7.6, y: 6.62, w: 4.7, h: 0.3, fontFace: FONTS.mono, fontSize: 10, color: C.zinc, align: "center", margin: 0, valign: "top" });
  }
  foot(s, 16, `reference-rule trade-off · 描述性数值，非统计或疗效证据`);
}

// ═══ P17 应用二 2×2 ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 04 · APPLICATION II`, `应用二 · 跨尺度研究范式与教学平台`);
  const cells = [
    [`01`, `跨尺度研究范式平台`, `五层 DTO/Protocol 冻结契约 + 可替换模型库；新模型按六问准入接入，层内替换不改变五层协议。`],
    [`02`, `教学与双创训练`, `逐层可观测 trace 与 CAR-M 研究观察台：baseline/干预双画布同 tick 对照、配对 L4 曲线、逐细胞跨层差异与事件审计，适配系统生物学与 AI4S 教学。`],
    [`03`, `数据治理标杆`, `registry.json 统一登记 + data-check fail-closed 门禁；TCGA 只输出 cohort 聚合；外部数据 Rights 核验 CC BY 4.0 / 1.0，可作科研数据合规示范。`],
    [`04`, `可复现科学基础设施`, `空虚拟环境 wheel 复现、SHA-256 manifest 固定输出、raw-only 报告链字节级重建 CSV/SVG/HTML。`],
  ];
  cells.forEach(([no, t, d], i) => {
    const x = 0.7 + (i % 2) * 6.12;
    const y = 1.85 + Math.floor(i / 2) * 2.42;
    glass(s, x, y, 5.86, 2.22);
    s.addShape("ellipse", { x: x + 0.35, y: y + 0.28, w: 0.5, h: 0.5, fill: { color: C.card }, line: { color: C.accent, width: 1, transparency: 40 } });
    s.addText(no, { x: x + 0.35, y: y + 0.28, w: 0.5, h: 0.5, fontFace: FONTS.mono, fontSize: 13, bold: true, color: C.accent, align: "center", valign: "middle", margin: 0 });
    s.addText(t, { x: x + 1.05, y: y + 0.32, w: 4.4, h: 0.45, fontFace: FONTS.display, fontSize: 16, bold: true, color: C.ink, margin: 0, valign: "middle" });
    s.addText(d, { x: x + 0.35, y: y + 1.0, w: 5.16, h: 1.05, fontFace: FONTS.body, fontSize: 11.5, color: C.zinc, margin: 0, valign: "top", lineSpacingMultiple: 1.3 });
  });
  foot(s, 17, `五层契约冻结 · 新模型六问准入 · 数据 fail-closed 门禁`);
}

// ═══ P18 三阶段路线图（横向时间轴） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 04 · ROADMAP`, `三阶段发展路线图`);
  s.addShape("rect", { x: 1.6, y: 3.55, w: 10.1, h: 0.02, fill: { color: C.accent, transparency: 50 }, line: { type: "none" } });
  const stages = [
    [`近期`, `外部锚定首验`, [
      `经授权下载 Wu/Jackson 五文件最小集，生成真实 target 并执行首次 reference score`,
      `calibration 选择与一次性 holdout / external validation 均按冻结协议输出后，才允许 L3 参数锚定`,
    ]],
    [`中期`, `逐层受控升级`, [
      `L2/L3 模型按六问准入协议在永久基线上隔离替换升级`,
      `开放 autolab-propose 的 LLM 假设提案入口：fail-closed、永不自动执行`,
    ]],
    [`远期`, `平台化开放`, [
      `更多细胞治疗场景接入，教学与竞赛训练推广`,
      `论文发表与开源社区，持续以 reference model 与五级表述对外沟通`,
    ]],
  ];
  stages.forEach(([tag, t, items], i) => {
    const cx = 2.35 + i * 4.35;
    s.addShape("ellipse", { x: cx - 0.14, y: 3.42, w: 0.28, h: 0.28, fill: { color: C.accent }, line: { type: "none" }, shadow: { type: "outer", blur: 20, offset: 0, angle: 0, color: C.accent, opacity: 0.4 } });
    s.addText(`0${i + 1} · ${tag}`, { x: cx - 1.6, y: 2.55, w: 3.2, h: 0.4, fontFace: FONTS.mono, fontSize: 13, charSpacing: 1, color: C.accent, align: "center", margin: 0, valign: "middle" });
    s.addText(t, { x: cx - 1.8, y: 2.95, w: 3.6, h: 0.42, fontFace: FONTS.display, fontSize: 17, bold: true, color: C.ink, align: "center", margin: 0, valign: "middle" });
    glass(s, cx - 1.8, 3.95, 3.6, 2.6);
    const runs = [];
    items.forEach((v, j) => runs.push({ text: v, options: { color: C.zinc, bullet: { code: "25CF", color: C.accent }, breakLine: j < items.length - 1 } }));
    bulletRuns(s, runs, cx - 1.55, 4.2, 3.1, 2.15, { fontSize: 11.5 });
  });
  foot(s, 18, `每一步都以冻结协议与诚实表述为前提`);
}

// ═══ P19 参赛组别与合规（分组定义列表） ═══
{
  const s = deck.addSlide();
  contentBg(s);
  header(s, `CHAPTER 04 · COMPLIANCE`, `参赛组别、团队构成与合规说明`);
  const groups = [
    [`组别`, [[`赛道类别`, `高教主赛道“人工智能+”类 · 本科生组创意组`], [`阶段`, `项目未完成工商等各类登记注册，具较好创意与较成型产品原型`]]],
    [`团队`, [[`构成`, `负责人及成员均为全日制在校本专科生，3–15 人，须为实际核心成员`], [`名单`, `团队成员与分工（待填）`]]],
    [`知识产权与数据合规`, [[`代码`, `自主研发，核心仅依赖 Python 标准库`], [`数据`, `TCGA cohort 去标识聚合；外部空间数据 CC BY 4.0 / CC BY 1.0，不涉密、不涉患者级记录`]]],
    [`科学表述合规`, [[`边界`, `不宣称数字生命、DNA 设计或临床预测能力；涌现按五级术语不越级`], [`基线`, `负面基线原样保留，不为展示效果调参`]]],
  ];
  let y = 1.8;
  groups.forEach(([g, rows]) => {
    s.addText(g, { x: 0.7, y, w: 4.2, h: 0.42, fontFace: FONTS.display, fontSize: 15.5, bold: true, color: C.accent, margin: 0, valign: "top" });
    s.addShape("rect", { x: 0.72, y: y + 0.5, w: 0.6, h: 0.03, fill: { color: C.accent, transparency: 45 }, line: { type: "none" } });
    rows.forEach(([k, v], j) => {
      const ry = y + 0.68 + j * 0.36;
      s.addText(k, { x: 0.7, y: ry, w: 1.5, h: 0.34, fontFace: FONTS.body, fontSize: 12, bold: true, color: C.ink, margin: 0, valign: "top" });
      s.addText(v, { x: 2.3, y: ry, w: 10.3, h: 0.34, fontFace: FONTS.body, fontSize: 12, color: C.zinc, margin: 0, valign: "top" });
    });
    s.addShape("rect", { x: 0.7, y: y + 1.48, w: 11.93, h: 0.008, fill: { color: "FFFFFF", transparency: 90 }, line: { type: "none" } });
    y += 1.3;
  });
  foot(s, 19, `依据《关于举办中国国际大学生创新大赛（2026）校赛的通知》`);
}

// ═══ P20 结尾 ═══
{
  const s = deck.addSlide();
  s.background = { color: C.canvas };
  orb(s, 6.66, 2.2, 3.4);
  s.addText(`让生命的生成`, { x: 1.5, y: 2.5, w: 10.33, h: 0.8, fontFace: FONTS.display, fontSize: 34, bold: true, color: C.ink, align: "center", margin: 0, valign: "middle" });
  s.addText([
    { text: `可计算`, options: { bold: true, color: C.accent, fontSize: 40 } },
    { text: ` · `, options: { color: C.zinc, fontSize: 40 } },
    { text: `可复现`, options: { bold: true, color: C.accent, fontSize: 40 } },
    { text: ` · `, options: { color: C.zinc, fontSize: 40 } },
    { text: `可审计`, options: { bold: true, color: C.accent, fontSize: 40 } },
  ], { x: 1.0, y: 3.35, w: 11.33, h: 0.9, fontFace: FONTS.display, align: "center", margin: 0, valign: "middle", charSpacing: 1 });
  s.addText(`M-GBA · 跨尺度数字生命计算架构`, { x: 2, y: 4.5, w: 9.33, h: 0.4, fontFace: FONTS.body, fontSize: 14, color: C.zinc, align: "center", margin: 0, valign: "middle" });
  s.addShape("rect", { x: 5.9, y: 5.2, w: 1.5, h: 0.012, fill: { color: "FFFFFF", transparency: 85 }, line: { type: "none" } });
  s.addText(`致谢 · Q&A`, { x: 3, y: 5.5, w: 7.33, h: 0.4, fontFace: FONTS.mono, fontSize: 14, charSpacing: 3, color: C.ink, align: "center", margin: 0, valign: "middle" });
  s.addText(`华南理工大学参赛团队 · 联系方式（待填）`, { x: 2.5, y: 6.1, w: 8.33, h: 0.35, fontFace: FONTS.body, fontSize: 11.5, color: C.zinc, align: "center", margin: 0, valign: "middle" });
}

// 末尾页署名 + 输出
{
  const lastSlide = deck.slides[deck.slides.length - 1];
  lastSlide.addText(`千问AI生成`, { x: SLIDE_W - 3.1, y: 0.14, w: 2.9, h: 0.34, align: "right", valign: "middle", margin: 0, fontFace: FONTS.body, fontSize: 12, color: "71717A" });
}

deck.writeFile({ fileName: path.join(__dirname, "..", "M-GBA创新大赛参赛PPT.pptx") });
