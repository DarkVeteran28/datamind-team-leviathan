import { useMemo, useState } from 'react';
import { Check, Copy, Download, Search, Table2 } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { QueryResponse } from '../types/api';

function csvCell(value: unknown): string {
  const text = value == null ? '' : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function exportCsv(columns: string[], rows: unknown[][]): string {
  return [columns.map(csvCell).join(','), ...rows.map(row => row.map(csvCell).join(','))].join('\r\n');
}

function chartRows(result: QueryResponse) {
  const columns = result.columns || [];
  const segmentIndex = columns.findIndex(name => /segment/i.test(name));
  const countIndex = columns.findIndex(name => /count|total|customers/i.test(name) && name !== columns[segmentIndex]);
  if (segmentIndex < 0 || countIndex < 0) return null;
  const data = (result.rows || []).flatMap(row => {
    const rawCount = row[countIndex];
    const count = typeof rawCount === 'number' ? rawCount : typeof rawCount === 'string' && rawCount.trim() !== '' ? Number(rawCount) : NaN;
    return typeof row[segmentIndex] === 'string' && Number.isFinite(count)
      ? [{ segment: row[segmentIndex] as string, count }]
      : [];
  });
  return data.length ? data : null;
}

function CopyCell({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = value == null ? 'NULL' : String(value);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch { setCopied(false); }
  };
  return <button className="cell-copy" onClick={copy} title="Copy cell value" aria-label={`Copy ${text}`}>
    <span>{text}</span>{copied ? <Check size={12} /> : <Copy size={12} />}
  </button>;
}

export function ResultsExplorer({ result }: { result: QueryResponse }) {
  const [filter, setFilter] = useState('');
  const columns = result.columns || [];
  const rows = result.rows || [];
  const filteredRows = useMemo(() => filter.trim()
    ? rows.filter(row => row.some(value => String(value ?? '').toLowerCase().includes(filter.toLowerCase())))
    : rows, [filter, rows]);
  const chart = chartRows(result);
  const sourceName = 'SNOWFLAKE';
  const csv = exportCsv(columns, rows);
  const csvUrl = `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;

  // Intent-gate blocked outcomes: no results to display
  const isMetadata = result.outcome === 'metadata';
  const isIntentUnsupported =
    result.outcome === 'unsupported' && result.intent_classification === 'UNSUPPORTED_BY_DATASET';

  if (isMetadata || isIntentUnsupported) {
    return <section className="panel results-panel" id="results-explorer">
      <div className="panel-heading">
        <div><span className="eyebrow">{sourceName} RESULT SET</span><h2>Results explorer</h2></div>
      </div>
      <div className="empty-state">
        <div className="empty-icon"><Table2 /></div>
        <strong>{isMetadata ? 'No query was executed' : 'Request blocked before execution'}</strong>
        <p>{isMetadata
          ? 'This response was answered from dataset metadata. No database query was made.'
          : 'The intent gate determined this dataset cannot answer the question. No SQL was compiled or executed.'
        }</p>
      </div>
    </section>;
  }

  return <section className="panel results-panel" id="results-explorer">
    <div className="panel-heading"><div><span className="eyebrow">{sourceName} RESULT SET</span><h2>Results explorer</h2></div>
      <div className="results-actions"><span className="rows-pill"><Table2 size={14} />{result.row_count ?? rows.length} rows</span>
        {columns.length > 0 && rows.length > 0 && <a className="button secondary compact" href={csvUrl} download="datamind-results.csv"><Download size={15} />Export CSV</a>}
      </div>
    </div>
    {columns.length > 0 && rows.length > 0 ? <>
      <label className="table-search"><Search size={15} /><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Filter returned rows locally" aria-label="Filter returned rows locally" /><span>Local only · no new query</span></label>
      <div className="table-scroll"><table><thead><tr>{columns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead>
        <tbody>{filteredRows.map((row, ri) => <tr key={ri}>{columns.map((column, ci) => <td key={`${column}-${ci}`} className={typeof row[ci] === 'number' ? 'numeric' : ''}><CopyCell value={row[ci]} /></td>)}</tr>)}</tbody>
      </table></div>
      <div className="table-footer"><span>Showing {filteredRows.length} of {rows.length} returned rows</span><span>Result limit: 100 rows maximum</span></div>
      {chart && <div className="chart-wrap"><div className="chart-title"><span className="eyebrow">DERIVED FROM THIS RESULT</span><h3>Customers by market segment</h3></div>
        <div className="chart" role="img" aria-label="Bar chart of counts by market segment"><ResponsiveContainer width="100%" height="100%"><BarChart data={chart} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#1e3047" vertical={false} /><XAxis dataKey="segment" stroke="#91a2b8" tickLine={false} axisLine={false} /><YAxis stroke="#91a2b8" tickLine={false} axisLine={false} allowDecimals={false} /><Tooltip contentStyle={{ background: '#101a2b', border: '1px solid #29435c', borderRadius: 8, color: '#e9f3fb' }} /><Bar dataKey="count" fill="#56c7d0" radius={[4, 4, 0, 0]} animationDuration={350} />
        </BarChart></ResponsiveContainer></div>
      </div>}
    </> : result.execution?.status === 'succeeded' ? <div className="empty-state"><div className="empty-icon"><Table2 /></div><strong>Query completed with no rows</strong><p>{sourceName} returned an empty result set. No example rows are substituted.</p></div>
      : <div className="empty-state"><div className="empty-icon"><Table2 /></div><strong>No result set available</strong><p>Rows appear here only when the selected backend returns actual results.</p></div>}
  </section>;
}
