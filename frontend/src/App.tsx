import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import {
  ArrowDown, ArrowRight, ArrowUpRight, Check, CircleAlert, Clipboard,
  Database, LoaderCircle, Search, ShieldCheck, Sparkles,
} from 'lucide-react';
import { Navigation, TopBar, type SectionId } from './components/Navigation';
import { QueryHistory } from './components/QueryHistory';
import { ResultsExplorer } from './components/ResultsExplorer';
import { Resources } from './components/Resources';
import { SqlPanel } from './components/SqlPanel';
import { StatusBadge } from './components/StatusBadge';
import { TrustPanel } from './components/TrustPanel';
import { checkApiProcess, submitQuestion } from './lib/api';
import type { HistoryEntry, QueryResponse } from './types/api';
import './styles.css';

const MODEL = import.meta.env.VITE_DATAMIND_MODEL || 'gemma3:4b';
const DATASET = 'SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER';
const EXAMPLES = [
  'Show the five customers with the highest account balances.',
  'Count customers by market segment.',
  'Show customers in the BUILDING market segment.',
  'Who are the best customers?',
];
const navTargets: Record<SectionId, string> = {
  overview: 'overview', workspace: 'query-workspace', results: 'results-explorer',
  trust: 'trust-mode', history: 'query-history', docs: 'documentation',
};

function queryOutcome(result?: QueryResponse): string {
  if (!result) return 'unknown';
  if (result.clarification?.required) return 'skipped';
  if (result.execution?.status) return result.execution.status;
  if (result.validation?.status === 'rejected') return 'rejected';
  return 'unknown';
}

function QueryReceipt({ result }: { result: QueryResponse }) {
  const [copied, setCopied] = useState(false);
  const queryId = result.query_id;
  const copy = async () => {
    if (!queryId) return;
    try {
      await navigator.clipboard.writeText(queryId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch { setCopied(false); }
  };
  if (!queryId) {
    const reason = result.clarification?.required ? 'Clarification was requested before SQL generation.'
      : result.validation?.status === 'rejected' ? 'SQL validation rejected the proposal before execution.'
        : result.execution?.status === 'failed' ? 'Snowflake execution failed; a query ID may be unavailable.'
          : result.sql ? 'This response does not include a query ID.' : 'No SQL or query ID was produced.';
    return <div className="receipt unavailable"><span className="receipt-icon"><CircleAlert size={17} /></span><div><strong>No execution receipt</strong><p>{reason}</p></div></div>;
  }
  return <div className="receipt"><span className="receipt-icon"><Database size={17} /></span><div className="receipt-main"><span className="eyebrow">SNOWFLAKE QUERY ID</span><code>{queryId}</code><p>Open Snowsight → Monitoring → Query History and search this ID to verify the SQL recorded by Snowflake.</p><a href="https://docs.snowflake.com/en/user-guide/ui-query-history" target="_blank" rel="noreferrer">Query History documentation <ArrowUpRight size={13} /></a></div>
    <button className="icon-button" onClick={copy} aria-label="Copy query ID" title="Copy query ID">{copied ? <Check size={16} /> : <Clipboard size={16} />}</button>
  </div>;
}

function AnswerCard({ result, question }: { result: QueryResponse; question: string }) {
  const clarification = result.clarification?.required === true;
  const failed = result.execution?.status === 'failed' || result.verification?.status === 'failed' || result.validation?.status === 'rejected';
  return <motion.section className={`answer-card ${clarification ? 'answer-clarification' : failed ? 'answer-warning' : 'answer-result'}`}
    initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24 }}>
    <div className="answer-topline"><span className="eyebrow">RESPONSE FOR</span><span className="response-question">{question}</span><StatusBadge status={queryOutcome(result)} /></div>
    {clarification ? <div className="clarification-content"><h3>One detail before I query</h3><p>{result.clarification?.question || result.answer}</p>
      <div className="choice-list">{result.clarification?.options?.map((option, index) => <span className="choice-chip" key={`${option.label}-${index}`}>{option.label || 'Option unavailable'}</span>)}</div>
      <span className="microcopy">No SQL was executed and no Snowflake query ID was created for this response. Selecting an option does not submit a new query yet; clarify in the question box and submit again.</span>
    </div> : <><h3>{result.answer || 'No answer text was returned.'}</h3>
      {result.assumptions?.length ? <p className="answer-assumption">Interpretation: {result.assumptions.join(' · ')}</p> : null}
    </>}
    {(result.warnings || []).map((warning, index) => <p className="response-warning" key={`${warning}-${index}`}><CircleAlert size={14} />{warning}</p>)}
  </motion.section>;
}

function Overview({ onAsk }: { onAsk: () => void }) {
  return <section className="overview-section" id="overview">
    <div className="overview-copy"><span className="eyebrow"><Sparkles size={13} /> AI ANALYTICS INTELLIGENCE CONSOLE</span>
      <h1>Ask your data.<br /><span>Verify every answer.</span></h1>
      <p>DataMind turns a plain-language question into a validated Snowflake query, then returns the actual rows with evidence you can inspect.</p>
      <button className="button primary" onClick={onAsk}>Open query workspace <ArrowRight size={16} /></button>
    </div>
    <div className="overview-visual" aria-label="DataMind query pipeline overview">
      <div className="visual-orbit orbit-one" /><div className="visual-orbit orbit-two" />
      <div className="visual-core"><div className="visual-core-icon"><Database size={23} /></div><strong>DataMind</strong><span>TRUST CONSOLE</span></div>
      <div className="orbit-label orbit-label-top"><span className="orbit-dot cyan" />Gemma 3 4B</div>
      <div className="orbit-label orbit-label-right"><span className="orbit-dot blue" />SQL policy</div>
      <div className="orbit-label orbit-label-bottom"><span className="orbit-dot green" />Snowflake rows</div>
      <div className="orbit-label orbit-label-left"><span className="orbit-dot amber" />Evidence</div>
    </div>
    <div className="scope-strip"><div><span className="scope-icon"><Database size={16} /></span><span><small>SUPPORTED DATASET</small><strong>{DATASET}</strong></span></div><span className="scope-divider" /><div><span className="scope-icon"><ShieldCheck size={16} /></span><span><small>POLICY SCOPE</small><strong>One table · four columns · 100-row maximum</strong></span></div></div>
    <div className="pipeline-summary"><div className="summary-title"><span className="eyebrow">HOW IT WORKS</span><h2>From question to evidence</h2></div>
      {[['01', 'Gemma', 'Proposes SQL locally'], ['02', 'Validator', 'Applies read-only policy'], ['03', 'Snowflake', 'Runs approved query'], ['04', 'Trust Mode', 'Checks result consistency']].map(([n, name, description], i) => <div className="summary-step" key={n}><span>{n}</span><strong>{name}</strong><small>{description}</small>{i < 3 && <ArrowRight size={14} />}</div>)}
    </div>
  </section>;
}

export default function App() {
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [apiReady, setApiReady] = useState<boolean | null>(null);
  const inFlight = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => { void checkApiProcess().then(setApiReady); }, []);

  const navigate = (section: SectionId) => {
    setActiveSection(section);
    document.getElementById(navTargets[section])?.scrollIntoView?.({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
  };

  const submit = async (event?: { preventDefault: () => void }) => {
    event?.preventDefault();
    if (inFlight.current) return;
    const trimmed = question.trim();
    if (!trimmed) {
      setError('Enter a question before analyzing the data.');
      inputRef.current?.focus();
      return;
    }
    inFlight.current = true;
    setLoading(true);
    setError('');
    try {
      const response = await submitQuestion(trimmed);
      const entry: HistoryEntry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        question: trimmed,
        timestamp: new Date().toISOString(),
        result: response,
      };
      setResult(response);
      setLastQuestion(trimmed);
      setHistory(current => [entry, ...current].slice(0, 20));
      setApiReady(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The DataMind request failed.');
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  const review = (entry: HistoryEntry) => {
    setResult(entry.result);
    setLastQuestion(entry.question);
    setQuestion(entry.question);
    navigate('results');
  };

  return <div className="app-shell">
    <Navigation active={activeSection} onNavigate={navigate} />
    <div className="app-frame">
      <TopBar model={MODEL} apiReady={apiReady} />
      <main>
        <motion.div initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reduceMotion ? 0 : 0.25 }}>
          <Overview onAsk={() => { navigate('workspace'); inputRef.current?.focus(); }} />

          <section className="workspace-section panel" id="query-workspace">
            <div className="section-heading"><div><span className="eyebrow">QUERY WORKSPACE</span><h2>What would you like to know?</h2><p>Ask in everyday language. Gemma proposes SQL; policy checks decide what may run.</p></div><span className="workspace-badge"><span className="pulse-dot" />Ready for a question</span></div>
            <form onSubmit={submit}>
              <label htmlFor="question-input" className="sr-only">Ask your data</label>
              <div className={`composer ${loading ? 'is-loading' : ''}`}>
                <textarea id="question-input" ref={inputRef} value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={onKeyDown}
                  placeholder="e.g. Count customers by market segment…" rows={3} maxLength={2000} aria-describedby="composer-hint" disabled={loading} />
                <div className="composer-footer"><span id="composer-hint">Enter submits · Shift+Enter for a new line</span><button type="submit" className="button primary submit-button" disabled={loading || !question.trim()}>
                  {loading ? <><LoaderCircle className="spin" size={16} />Analyzing</> : <>Analyze data <ArrowRight size={16} /></>}
                </button></div>
              </div>
            </form>
            {error && <div className="error-banner" role="alert"><CircleAlert size={16} /><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
            {loading && <div className="loading-line" role="status"><span className="loading-bar" />Waiting for the local model and Snowflake response. No simulated progress is shown.</div>}
            <div className="example-prompts"><span className="eyebrow">TRY A QUESTION</span><div>{EXAMPLES.map(example => <button key={example} className="prompt-chip" onClick={() => { setQuestion(example); setError(''); }}>{example}</button>)}</div></div>
          </section>

          <AnimatePresence mode="wait">
            {result ? <motion.div key={`${lastQuestion}-${history.length}`} initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: reduceMotion ? 0 : 0.22 }} className="response-workspace">
              <div className="result-overview" id="results-overview"><div><span className="eyebrow">LATEST RESPONSE</span><h2>Answer & evidence</h2></div><div className="overview-metrics">
                <div><small>ROWS RETURNED</small><strong>{result.row_count ?? result.rows?.length ?? '—'}</strong></div>
                <div><small>VALIDATION</small><StatusBadge status={result.validation?.status} /></div>
                <div><small>EXECUTION</small><StatusBadge status={result.execution?.status} /></div>
                <div><small>CONSISTENCY</small><StatusBadge status={result.verification?.status} /></div>
              </div></div>
              <AnswerCard result={result} question={lastQuestion} />
              <ResultsExplorer result={result} />
              <QueryReceipt result={result} />
              <SqlPanel result={result} />
              <TrustPanel result={result} question={lastQuestion} />
              <section className="panel notes-panel"><div className="notes-columns"><div><span className="eyebrow">ASSUMPTIONS</span>{result.assumptions?.length ? <ul>{result.assumptions.map((item, i) => <li key={`${item}-${i}`}>{item}</li>)}</ul> : <p className="muted">No assumptions were returned.</p>}</div>
                <div><span className="eyebrow">WARNINGS</span>{result.warnings?.length ? <ul className="warning-list">{result.warnings.map((item, i) => <li key={`${item}-${i}`}>{item}</li>)}</ul> : <p className="muted">No warnings were returned.</p>}</div></div></section>
            </motion.div> : <div className="before-query"><div className="before-icon"><Search size={22} /></div><div><strong>Your results will appear here</strong><span>Ask a supported question to see returned rows, SQL, query ID, and Trust Mode evidence.</span></div><ArrowDown size={16} /></div>}
          </AnimatePresence>

          <QueryHistory entries={history} onReview={review} onClear={() => setHistory([])} />
          <Resources />
          <footer><span>DataMind · Local-first data answers</span><span>Safety policy: one table · SELECT only · max 100 rows</span></footer>
        </motion.div>
      </main>
    </div>
  </div>;
}
