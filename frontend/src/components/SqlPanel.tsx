import { useState } from 'react';
import { Check, Copy, ChevronDown, ChevronUp } from 'lucide-react';
import type { QueryResponse } from '../types/api';
import { StatusBadge } from './StatusBadge';

const keywords = new Set(['select', 'from', 'where', 'group', 'by', 'order', 'limit', 'desc', 'asc', 'as', 'and', 'or', 'not', 'null', 'is', 'in', 'having', 'distinct', 'case', 'when', 'then', 'else', 'end']);

function highlightSql(sql: string) {
  const tokens = sql.split(/(\b[A-Za-z_][A-Za-z0-9_]*\b|'(?:''|[^'])*'|\b\d+(?:\.\d+)?\b|--[^\n]*)/g);
  return tokens.map((token, index) => {
    if (/^--/.test(token)) return <span className="sql-comment" key={index}>{token}</span>;
    if (/^'/.test(token)) return <span className="sql-string" key={index}>{token}</span>;
    if (/^\d/.test(token)) return <span className="sql-number" key={index}>{token}</span>;
    if (keywords.has(token.toLowerCase())) return <span className="sql-keyword" key={index}>{token}</span>;
    return <span key={index}>{token}</span>;
  });
}

export function SqlPanel({ result }: { result: QueryResponse }) {
  const [expanded, setExpanded] = useState(true);
  const [copied, setCopied] = useState(false);
  const sql = result.sql;
  const rejected = result.validation?.status === 'rejected';
  const engine = result.execution?.engine === 'local dataset' ? 'local SQLite' : 'Snowflake';
  const copy = async () => {
    if (!sql || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch { setCopied(false); }
  };

  return <section className="panel sql-panel" id="sql-inspection">
    <div className="panel-heading"><div><span className="eyebrow">INSPECTABLE QUERY</span><h2>SQL inspection</h2></div>
      <div className="panel-actions">
        {sql && <StatusBadge status={rejected ? 'rejected' : result.validation?.status} />}
        <button className="icon-button" onClick={() => setExpanded(!expanded)} aria-label={expanded ? 'Collapse SQL' : 'Expand SQL'}>{expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button>
      </div>
    </div>
    {!sql ? <p className="muted">No SQL was generated for this response.</p> : <>
      <p className={`sql-label ${rejected ? 'text-amber' : ''}`}>{rejected ? 'Query proposal · rejected before execution' : result.validation?.status === 'passed' ? `Validated SQL · submitted to ${engine}` : 'SQL proposal · execution not established'}</p>
      {expanded && <div className="sql-code-wrap"><pre className="line-numbers" aria-hidden="true">{sql.split('\n').map((_, i) => `${i + 1}`).join('\n')}</pre><pre className="sql-code"><code>{highlightSql(sql)}</code></pre></div>}
      <div className="sql-footer"><span>{result.execution?.status === 'succeeded' ? 'Execution succeeded' : rejected ? 'Not executed' : 'Execution status shown in Trust Mode'}</span><button className="text-button" onClick={copy} disabled={!expanded}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Copied' : 'Copy SQL'}</button></div>
      {result.sql_parameters?.length ? <div className="sql-parameters"><span className="eyebrow">BOUND FILTER VALUES</span><div>{result.sql_parameters.map((value, index) => <code key={index}>?{index + 1} = {value == null ? 'NULL' : String(value)}</code>)}</div></div> : null}
      <p className="microcopy">Dataset-specific allowlist · maximum 100 returned rows</p>
    </>}
  </section>;
}
