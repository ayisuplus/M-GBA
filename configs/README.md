# 配置索引

M-GBA 0.1.0 的参考运行由以下 JSON 共同冻结：

| 文件 | 用途 |
|---|---|
| `multiscale_demo.json` | 初始 Genome、Cell、局部环境和组织拓扑 |
| `layers/l0_reference_grn.json` | L0 六节点离散 GRN |
| `layers/l1_reference_molecular.json` | L1 翻译、降解和局部信号参数 |
| `layers/l2_reference_cell.json` | L2 五态 Cell 转移和动作参数 |
| `layers/l3_reference_tissue.json` | L3 节点压力、资源和信号更新 |
| `layers/l4_reference_phenotype.json` | L4 指标、窗口与结局阈值 |
| `runner_reference.json` | L0/L4 慢时钟、资源预算和跟踪预算 |
| `experiments/wp8_reference.json` | WP8 的 tick、seed、repair 钳制与层替换 |
| `demo.json` | 独立 L3 STEN smoke 场景 |

参考配置是实验身份的一部分。修改任意参数后应产生新的模型版本或实验 ID，不能将新结果继续标记为 0.1.0 reference baseline。

这些值是无量纲软件参数，没有经过真实生物数据拟合，不应被解读为基因表达量、药物剂量、时间单位或临床阈值。
