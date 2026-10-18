import {
  Activity, BookOpen, Database, History, LayoutDashboard, Search,
  ShieldCheck, Table2, type LucideIcon,
} from 'lucide-react';

export type SectionId = 'overview' | 'workspace' | 'results' | 'trust' | 'history' | 'docs';

const links: { id: SectionId; label: string; icon: LucideIcon }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'workspace', label: 'Query workspace', icon: Search },
  { id: 'results', label: 'Results explorer', icon: Table2 },
  { id: 'trust', label: 'Trust Mode', icon: ShieldCheck },
  { id: 'history', label: 'Query history', icon: History },
  { id: 'docs', label: 'Documentation', icon: BookOpen },
];

export function Navigation({ active, onNavigate }: { active: SectionId; onNavigate: (id: SectionId) => void }) {
  return <aside className="rail" aria-label="Main navigation">
    <a className="brand-mark" href="#overview" aria-label="DataMind overview" onClick={() => onNavigate('overview')}>D<span>·</span></a>
    <nav>
      {links.map(({ id, label, icon: Icon }) => <button
        key={id} className={`rail-link ${active === id ? 'active' : ''}`}
        onClick={() => onNavigate(id)} aria-label={label} aria-current={active === id ? 'page' : undefined}
        title={label}>
        <Icon size={19} strokeWidth={1.8} aria-hidden="true" />
        <span>{label}</span>
      </button>)}
    </nav>
    <div className="rail-bottom"><span className="rail-dot" /><span>Local-first</span></div>
  </aside>;
}

export function TopBar({ model, apiReady }: { model: string; apiReady: boolean | null }) {
  return <header className="topbar">
    <div className="topbar-product"><div className="brand-icon"><Database size={18} /></div><div><strong>DataMind</strong><span>AI analytics intelligence console</span></div></div>
    <div className="topbar-context"><span className="context-label">WORKSPACE</span><span className="context-value">TPC-H · CUSTOMER</span></div>
    <div className="topbar-right"><span className="model-pill"><Activity size={14} />{model} <i>· local Ollama</i></span>
      <span className={`api-pill ${apiReady === true ? 'api-ready' : ''}`}><span />{apiReady === null ? 'API status unknown' : apiReady ? 'API available' : 'API unavailable'}</span>
    </div>
  </header>;
}
