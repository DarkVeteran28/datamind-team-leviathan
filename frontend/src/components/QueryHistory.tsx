import { Clock3, History, RotateCcw, Trash2 } from 'lucide-react';
import type { HistoryEntry } from '../types/api';
import { StatusBadge } from './StatusBadge';

function outcome(entry: HistoryEntry) {
  if (entry.result.outcome === 'unsupported' || entry.result.outcome === 'rejected' || entry.result.outcome === 'failed') return entry.result.outcome;
  if (entry.result.clarification?.required) return 'skipped';
  if (entry.result.execution?.status) return entry.result.execution.status;
  if (entry.result.validation?.status === 'rejected') return 'rejected';
  return 'unknown';
}

export function QueryHistory({ entries, onReview, onClear }: {
  entries: HistoryEntry[]; onReview: (entry: HistoryEntry) => void; onClear: () => void;
}) {
  return <section className="panel history-panel" id="query-history">
    <div className="panel-heading"><div><span className="eyebrow">CURRENT BROWSER SESSION ONLY</span><h2>Query history</h2></div>
      {entries.length > 0 && <button className="button ghost compact" onClick={onClear}><Trash2 size={15} />Clear history</button>}
    </div>
    {entries.length === 0 ? <div className="empty-state small"><div className="empty-icon"><History /></div><strong>No questions in this session</strong><p>Submitted questions and returned outcomes appear here without disk persistence.</p></div> : <div className="history-list">
      {entries.map(entry => <article className="history-item" key={entry.id}>
        <div className="history-icon"><Clock3 size={16} /></div><div className="history-main"><strong>{entry.question}</strong><span>{new Date(entry.timestamp).toLocaleString()}</span></div>
        <div className="history-meta"><StatusBadge status={outcome(entry)} /><span>{entry.result.row_count ?? '—'} rows</span><code>{entry.result.query_id || (entry.result.clarification?.required ? 'Clarification' : 'No query ID')}</code></div>
        {entry.result.clarification?.required && <span className="history-clarify">Clarification requested</span>}
        <button className="icon-button review-button" onClick={() => onReview(entry)} aria-label={`Review previous result for ${entry.question}`} title="Review stored result"><RotateCcw size={15} /></button>
      </article>)}
    </div>}
  </section>;
}
