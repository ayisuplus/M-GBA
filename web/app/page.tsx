import Link from 'next/link';
import { SiteHeader } from '@/components/SiteHeader';

const layers = [
  ['L0', '基因 / 转录调控', '可审计的调控与扰动'],
  ['L1', '分子 / 蛋白状态', '正式承担 L0 到 L2 的转换'],
  ['L2', '细胞个体行为', '由分子状态与局部环境共同产生'],
  ['L3', '组织与环境场', '局部通信、空间邻域与动态拓扑'],
  ['L4', '有机体宏观表型', '只从组织状态聚合观察'],
];

export default function Home() {
  return (
    <main className="site-page">
      <SiteHeader active="home" />
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">通用五层平台 · CAR-M 旗舰案例</p>
          <h1>把生命状态的跨尺度传播，变成一间可以操作的实验室</h1>
          <p className="hero-lead">设置受限干预、回放 baseline 与 intervention，并沿 L0→L4 检查每一次状态转换。结果保留配置、seed、digest 与科学边界。</p>
          <div className="hero-actions">
            <Link className="primary-cta" href="/lab">一键进入实验室 <span>→</span></Link>
            <Link className="secondary-cta" href="/evidence">先看证据与边界</Link>
          </div>
          <div className="hero-facts">
            <div><b>356+</b><span>科学与契约门禁</span></div>
            <div><b>3</b><span>冻结比赛实验</span></div>
            <div><b>L0→L4</b><span>相邻层传播</span></div>
          </div>
        </div>
        <div className="hero-visual">
          <div className="hero-grid" />
          <div className="hero-flow" aria-label="L0 到 L4 相邻层传播示意图">
            {layers.map(([code, name], index) => (
              <div className={`hero-flow-node layer-${index}`} key={code}>
                <span>{code}</span>
                <b>{name}</b>
                {index < layers.length - 1 && <i aria-hidden="true">↓</i>}
              </div>
            ))}
          </div>
          <div className="hero-phenotype"><small>L4 HOMEOSTASIS</small><b>0.7559</b><span>冻结回放 state-intervention baseline 终末值 · 非疗效指标</span></div>
        </div>
      </section>

      <section className="home-section">
        <div className="section-heading"><p className="eyebrow">THE RESEARCH OBJECT</p><h2>不是一个“多智能体平台”，而是一条可审计的生成链</h2><p>每一层只通过正式契约与相邻层交互；复杂模型是可替换实现，而不是项目定义。</p></div>
        <div className="layer-story">
          {layers.map(([code, name, description], index) => <article className={`story-layer layer-${index}`} key={code}><span>{code}</span><div><h3>{name}</h3><p>{description}</p></div>{index < layers.length - 1 && <i>↓</i>}</article>)}
        </div>
      </section>

      <section className="home-section flagship-section">
        <div className="section-heading"><p className="eyebrow">FLAGSHIP CASE</p><h2>CAR-M 状态条件序列干预</h2><p>用现有正式协议回答一个具体问题：不同剂量、时机与暴露长度，如何沿五层路径改变宏观代理指标？</p></div>
        <div className="flagship-grid">
          <div className="flagship-card"><small>SHORT TIMING · L4 DISTANCE</small><b>0.006580</b><span>可检测传播，不等于疗效改善</span></div>
          <div className="flagship-card"><small>LONG TIMING · L4 DISTANCE</small><b>0.020899</b><span>代价与收益同时显现</span></div>
          <div className="flagship-card target-card"><small>REAL SPATIAL TARGET</small><b>已生成 · improved</b><span>首次未锚定 → ADR-0043 improved</span></div>
        </div>
        <Link className="inline-cta" href="/lab">用 3 分钟完成一次实验回放 →</Link>
      </section>

      <footer className="site-footer"><div><b>M-GBA</b><span>Cross-Scale Virtual Lab</span></div><p>contract demonstrator / reference model · 不是临床预测或真实数字生命</p><nav><Link href="/lab">实验室</Link><Link href="/evidence">证据</Link><a href="/offline/mgba-carm-demo.html" download>离线 Demo</a></nav></footer>
    </main>
  );
}
