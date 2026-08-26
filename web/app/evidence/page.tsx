import type { Metadata } from 'next';
import Link from 'next/link';
import { SiteHeader } from '@/components/SiteHeader';

export const metadata: Metadata = {
  title: '证据与边界',
  description: 'M-GBA 比赛版网站的模型身份、证据等级、复现方法与数据来源。',
};

const boundaries = [
  ['模型身份', '当前主运行链是 contract demonstrator / reference model，不是临床级生物模型。'],
  ['因果边界', 'L0→L4 主生成流只发生在相邻层；L4 不能直接指定 L2 行为。'],
  ['结果解释', '终点距离与曲线差值描述模型内效应，不能直接解释为疗效、机制真值或统计显著性。'],
  ['群体动力学', 'direction / intensity / polarization 是 activation-stress reference proxy；状态转换不是物理相变、涌现证明或机制验证。'],
  ['空间边界', '组织画布是显示投影；空间 L3 是无量纲 reference model，不是空间组学重建。'],
  ['真实 Target', 'Wu / Jackson 真实空间聚合 Target 尚未生成；合成 fixture 只验证管线。'],
];

export default function EvidencePage() {
  return (
    <main className="site-page evidence-page">
      <SiteHeader active="evidence" />
      <section className="evidence-hero"><p className="eyebrow">EVIDENCE BEFORE CLAIMS</p><h1>每个结果，都要能回答“它从哪里来、能说明什么、不能说明什么”</h1><p>工作台显示 experiment ID、seed、model version、history digest、bundle digest 和原始协议摘要。网页只观察和调度，不进入模型 tick 循环。</p></section>
      <section className="evidence-grid">
        <article className="evidence-panel"><span className="panel-kicker">01 · SCIENTIFIC BOUNDARY</span><h2>主张边界</h2><div className="claim-table">{boundaries.map(([name, value]) => <div key={name}><b>{name}</b><p>{value}</p></div>)}</div></article>
        <article className="evidence-panel"><span className="panel-kicker">02 · REPRODUCIBILITY</span><h2>复现路径</h2><div className="repro-card"><code>mgba collective-analyze --input RUN.json --output collective.json</code><p>只从正式 raw trace 重算群体状态、合格转换、个体 archetype 与 L4 时间关联。</p></div><div className="repro-card"><code>mgba lab-export --output-dir web/public/lab-data</code><p>同一冻结输入生成字节级一致的 catalog、bundle 与 SHA-256 manifest。</p></div><div className="repro-card"><code>python -m unittest tests.test_collective_dynamics tests.test_lab -v</code><p>验证阈值边界、驻留时间、cohort 完整性、onset 前零差异与 digest。</p></div><a className="secondary-cta" href="/offline/mgba-carm-demo.html" download>下载完全离线 Demo</a></article>
        <article className="evidence-panel wide"><span className="panel-kicker">03 · PROVENANCE</span><h2>数据与模型来源</h2><div className="provenance-row"><div><b>CAR-M profile</b><span>旧 752 个 TCGA-BRCA GAT 代理预测的去标识聚合，不是临床真值。</span></div><div><b>群体观察器 0.1</b><span>冻结阈值：方向 ±0.15、强度 0.04/0.16、极化 0.09、最短驻留 3 ticks；没有拟合 Ising/Glauber 模型。</span></div><div><b>状态条件实验</b><span>固定 seed 42、60 ticks、工程巨噬细胞 signal_expression 的预注册 schedule。</span></div><div><b>空间锚点计划</b><span>Wu/Swarbrick Visium 与 Jackson IMC 仅用于生成链外的 L3 聚合统计锚定。</span></div></div></article>
      </section>
      <section className="evidence-action"><div><b>准备好检查一次完整传播了吗？</b><span>在同一 tick 对照 baseline 与 intervention，再从相图转换点检查对应 L4 观测。</span></div><Link className="primary-cta" href="/lab">进入实验室 →</Link></section>
    </main>
  );
}
