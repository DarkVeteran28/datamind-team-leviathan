import { motion, useReducedMotion } from 'framer-motion';
import { Check, CircleHelp, Shield } from 'lucide-react';
import type { EvidenceCheck, QueryResponse, StageEvidence } from '../types/api';
import { StatusBadge } from './StatusBadge';

const caveats = {
  validation: 'Passing means the query met implemented policy checks. It does not establish that the SQL answers the user’s intent.',
  execution: 'A successful execution means Snowflake ran the query. It does not validate the interpretation.',
  verification: 'This engine checks result consistency, not semantic correctness or natural-language accuracy.',
};

function EvidenceStage({ title, evidence, caveat, unavailable = false }: {
  title: string; evidence?: StageEvidence; caveat: string; unavailable?: boolean;
}) {
  const status = unavailable ? 'not_available' : evidence?.status || 'not_available';
  const checks = evidence?.checks;
  return <div className="evidence-stage">
    <div className="evidence-stage-head"><div className="stage-icon"><Shield size={16} /></div><div className="stage-title"><strong>{title}</strong><span>{unavailable ? 'Backend does not expose a separate status for this stage.' : caveat}</span></div><StatusBadge status={status} /></div>
    {!unavailable && (!evidence ? <p className="evidence-empty">Not available</p> : checks?.length ? <div className="check-list">
      {checks.map((check: EvidenceCheck, i) => <div className="check-row" key={`${check.name || 'check'}-${i}`}>
        <span className="check-name">{check.name || 'Unnamed check'}</span>
        <StatusBadge status={check.status} />
        <span className="check-detail">{check.detail || 'Not available'}</span>
      </div>)}
    </div> : <p className="evidence-empty">{checks ? 'No checks were recorded.' : 'Not available'}</p>)}
    {!unavailable && title === 'Result consistency verification' && checks?.some(check => check.name === 'semantic_correctness' && check.status === 'not_run') && <p className="semantic-note"><CircleHelp size={14} /> Semantic correctness: Not run. Consistency checks do not prove the query captured user intent.</p>}
  </div>;
}

export function TrustPanel({ result, question }: { result: QueryResponse; question: string }) {
  const reduceMotion = useReducedMotion();
  const clarification = result.clarification?.required;
  const steps = [
    { number: '01', title: 'Question received', status: question ? 'passed' : 'not_available' },
    { number: '02', title: 'Gemma query-plan generation', status: 'not_available' },
    { number: '03', title: 'Typed plan validation', status: result.plan_validation?.status || 'not_available' },
    { number: '04', title: 'SQL policy validation', status: result.validation?.status || 'not_available' },
    { number: '05', title: 'Snowflake execution', status: result.execution?.status || 'not_available' },
    { number: '06', title: 'Result consistency', status: result.verification?.status || 'not_available' },
  ];
  return <section className="panel trust-panel" id="trust-mode">
    <div className="panel-heading"><div><span className="eyebrow">EVIDENCE WORKSPACE</span><h2>Trust Mode</h2></div><span className="trust-mark"><Shield size={15} /> Auditable response</span></div>
    {clarification && <div className="clarification-callout"><strong>Clarification requested</strong><p>{result.clarification?.question || result.answer}</p><p>No SQL was executed and no query ID was created for this response. Use a supported option in the response card above to continue.</p></div>}
    <div className="pipeline-track" aria-label="Pipeline stage status">
      {steps.map((step, index) => <motion.div key={step.number} className="pipeline-step"
        initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0 : 0.2, delay: reduceMotion ? 0 : index * 0.04 }}>
        <span className="step-num">{step.number}</span><strong>{step.title}</strong><StatusBadge status={step.status} />
        {index < steps.length - 1 && <span className="step-connector" />}
      </motion.div>)}
    </div>
    <p className="microcopy">Generation status is unavailable because the backend does not return a separate model-generation evidence field.</p>
    <div className="evidence-grid">
      <EvidenceStage title="Typed query-plan validation" evidence={result.plan_validation} caveat="Passing means the plan used supported fields, operations, typed filters, and a bounded result limit." />
      <EvidenceStage title="SQL policy validation" evidence={result.validation} caveat={caveats.validation} />
      <EvidenceStage title="Snowflake execution" evidence={result.execution} caveat={caveats.execution} />
      <EvidenceStage title="Result consistency verification" evidence={result.verification} caveat={caveats.verification} />
    </div>
    {result.query_plan && <details className="plan-inspection"><summary>Inspect typed query plan</summary><pre>{JSON.stringify(result.query_plan, null, 2)}</pre></details>}
    <div className="trust-footnote"><Check size={15} /><span>Result consistency is not a semantic accuracy benchmark. Review the SQL, assumptions, returned rows, and query ID.</span></div>
  </section>;
}
