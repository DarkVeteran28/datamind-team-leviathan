import { ArrowUpRight, BookOpen, Database, ExternalLink, Github, ShieldCheck } from 'lucide-react';

const resources = [
  { label: 'GitHub repository', href: 'https://github.com/ZERODAY-2026/Leviathan', icon: Github },
  { label: 'Project README', href: 'https://github.com/ZERODAY-2026/Leviathan/blob/main/README.md', icon: BookOpen },
  { label: 'Dataset attribution', href: 'https://github.com/ZERODAY-2026/Leviathan/blob/main/DATASETS.md', icon: Database },
  { label: 'Evaluation evidence', href: 'https://github.com/ZERODAY-2026/Leviathan/blob/main/docs/EVALUATION_EVIDENCE.md', icon: ShieldCheck },
  { label: 'Snowflake Query History', href: 'https://docs.snowflake.com/en/user-guide/ui-query-history', icon: ExternalLink },
  { label: 'Snowflake sample datasets', href: 'https://docs.snowflake.com/en/user-guide/sample-data', icon: Database },
  { label: 'Ollama documentation', href: 'https://docs.ollama.com/', icon: ExternalLink },
];

export function Resources() {
  return <section className="panel resources-panel" id="documentation">
    <div className="panel-heading"><div><span className="eyebrow">REFERENCE</span><h2>Documentation & resources</h2></div></div>
    <div className="resource-grid">{resources.map(({ label, href, icon: Icon }) => <a className="resource-link" key={href} href={href} target="_blank" rel="noreferrer">
      <Icon size={18} /><span>{label}</span><ArrowUpRight size={14} className="resource-arrow" />
    </a>)}</div>
    <p className="microcopy">New tabs open the official project and vendor documentation. DataMind does not access your authenticated Snowsight session.</p>
  </section>;
}
