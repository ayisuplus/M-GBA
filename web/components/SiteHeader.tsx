import Link from 'next/link';

export function SiteHeader({ active }: { active?: 'home' | 'lab' | 'evidence' }) {
  return (
    <header className="topbar">
      <Link className="brand" href="/">
        <span className="brand-mark">M</span>
        <span><b>M-GBA</b><small>Cross-Scale Virtual Lab</small></span>
      </Link>
      <nav aria-label="主导航">
        <Link className={active === 'home' ? 'active' : ''} href="/">项目首页</Link>
        <Link className={active === 'lab' ? 'active' : ''} href="/lab">实验工作台</Link>
        <Link className={active === 'evidence' ? 'active' : ''} href="/evidence">证据与边界</Link>
      </nav>
      <div className="model-chip"><i /> reference model <span>v0.2</span></div>
    </header>
  );
}
