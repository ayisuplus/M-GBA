# M-GBA 创新大赛 PPT · Anthropic 风格重设计

## 交付物

- **`M-GBA创新大赛参赛PPT_Anthropic风格版.pptx`**（20 页，与原版结构、文案完全一致，仅重做视觉与图表）

## 设计规范（Anthropic 品牌气质）

| 元素 | 取值 |
|---|---|
| 背景 | 暖米白 `#FAF9F5`；封底深炭 `#1A1A18` 反白 |
| 正文/标题色 | 深炭 `#1A1A18` |
| 唯一强调色 | 赤土橙 `#D97757`（仅用于章节编号、关键数字、箭头、重点结论） |
| 标题字体 | Georgia / 思源宋体（回退宋体），打印级衬线 |
| 正文字体 | Arial / 微软雅黑 |
| 版式 | 细线分隔、大留白、圆角浅卡片、无阴影无渐变 |

## 图表重绘（真实数据、零编造）

三张数据图全部由 `work/anthropic_charts.py` 直接从 `artifacts/` raw JSON 重算渲染，计算口径逐行对齐权威脚本 `visual_assets/generate_scientific_figures.py`：

- **P12 空间消融**：场耦合 0.048720 / 空间邻域 0.025588 / 移动 0.000898（4 组匹配条件平均绝对 L4 距离），零效应对照保持为零
- **P13 标定 holdout**：四档 mean homeostasis 全部提升，Calm/Injury FAILED→STABLE，Severe/Collapse 仍为 FAILED（失败边界原样呈现）
- **P16 干预时序**：短/长暴露 L4 距离 0.006580 / 0.020899，晚期干预减轻活力/损伤代价但炎症更高

每页图表均标注数据源 artifact 路径与"描述性审计，非统计/疗效证据"合规声明。

## 素材处理

- 保留：P10 CAR-M 肿瘤微环境概念图（真实内容图，已标注"非显微证据"）
- 弃用：全部 AI 生成装饰插图（含"千问AI生成"水印的旧封面/背景/p16 屏幕图）

## 校验记录

- LibreOffice 渲染 PDF → pymupdf 逐页 PNG，20 页逐页人工检查：无文字溢出、无遮挡、无乱码
- 文本关键数值（752、323/273/156、298、21-run、0.2076→0.5927 等）自动核对通过
- 图表数值与 `artifacts/` 重算结果逐位一致

## 待补充（需用户提供）

- P19 团队成员与分工名单
- P20 联系方式

## 复现方式

```bash
# 图表（需隔离 venv）
C:/Users/ayi.dnk/.workbuddy/binaries/python/envs/default/Scripts/python.exe work/anthropic_charts.py
# PPT 构建
C:/Users/ayi.dnk/.workbuddy/binaries/python/envs/default/Scripts/python.exe work/build_pptx.py
```
