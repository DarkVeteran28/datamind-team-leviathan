import { motion, useReducedMotion } from 'framer-motion';
import { Check, CircleHelp, Database, Shield } from 'lucide-react';
import type { EvidenceCheck, QueryResponse, StageEvidence } from '../types/api';
import { StatusBadge } from './StatusBadge';

const caveats = {
  intent: 'Deterministic concept check against registered dataset capabilities. Runs before any LLM call or database execution.',
  validation: 'Passing means the query met implemented policy checks. It does not establish that the SQL answers the user\u2019s intent.',
  execution: 'A successful execution means the selected engine returned results. It does not validate the interpretation.',
  verification: 'This engine checks result consistency, not semantic correctness or natural-language accuracy.',
};

const intentOutcomeLabels: Record<string, string> = {
  ANSWERABLE: 'passed',
  AMBIGUOUS: 'not_run',
  UNSUPPORTED_BY_DATASET: 'failed',
  DATASET_METADATA: 'passed',
  UNSAFE_OR_INVALID: 'failed',
  not_run: 'not_run',
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

function IntentGateStage({ intentClassification, missingConcepts }: {
  intentClassification?: string; missingConcepts?: string[];
}) {
  const classification = intentClassification || 'not_run';
  const badgeStatus = intentOutcomeLabels[classification] || 'not_run';
  const labels: Record<string, string> = {
    ANSWERABLE: 'Answerable \u2014 proceed to planning',
    AMBIGUOUS: 'Ambiguous \u2014 clarification requested',
    UNSUPPORTED_BY_DATASET: 'Unsupported \u2014 dataset lacks required concepts',
    DATASET_METADATA: 'Dataset metadata \u2014 answered from registry',
    UNSAFE_OR_INVALID: 'Unsafe or invalid \u2014 rejected',
    not_run: 'Not run',
  };
  const label = labels[classification] || classification;
  return <div className="evidence-stage">
    <div className="evidence-stage-head">
      <div className="stage-icon"><Database size={16} /></div>
      <div className="stage-title">
        <strong>Semantic intent gate</strong>
        <span>{caveats.intent}</span>
      </div>
      <StatusBadge status={badgeStatus} />
    </div>
    <div className="check-list">
      <div className="check-row">
        <span className="check-name">classification</span>
        <StatusBadge status={badgeStatus} />
        <span className="check-detail">{label}</span>
      </div>
      {missingConcepts && missingConcepts.length > 0 && (
        <div className="check-row">
          <span className="check-name">missing concepts</span>
          <StatusBadge status="failed" />
          <span className="check-detail">{missingConcepts.join(', ')}</span>
        </div>
      )}
    </div>
  </div>;
}

export function TrustPanel({ result, question }: { result: QueryResponse; question: string }) {
  const reduceMotion = useReducedMotion();
  const clarification = result.clarification?.required;
  const isUnsupported = result.outcome === 'unsupported' && result.intent_classification === 'UNSUPPORTED_BY_DATASET';
  const isMetadata = result.outcome === 'metadata';
  const planTitle = result.plan_source === 'ollama' ? 'Gemma query-plan generation'
    : result.plan_source === 'deterministic_rule' ? 'Deterministic intent mapping' : 'Query-plan generation';
  const planStatus = result.plan_source === 'ollama' || result.plan_source === 'deterministic_rule'
    ? 'passed' : 'not_run';
  const executionTitle = 'Snowflake execution';
  const engineTitle = result.execution?.engine ? `${result.execution.engine} execution` : 'Snowflake execution';

  // Intent gate status for pipeline track
  const intentBadge = intentOutcomeLabels[result.intent_classification || 'not_run'] || 'not_run';

  const steps = [
    { number: '01', title: 'Question received', status: question ? 'passed' : 'not_available' },
    { number: '02', title: 'Semantic intent gate', status: intentBadge },
    { number: '03', title: planTitle, status: isUnsupported || isMetadata ? 'not_run' : planStatus },
    { number: '04', title: 'Typed plan validation', status: isUnsupported || isMetadata ? 'not_run' : (result.plan_validation?.status || 'not_available') },
    { number: '05', title: 'SQL policy validation', status: isUnsupported || isMetadata ? 'not_run' : (result.validation?.status || 'not_available') },
    { number: '06', title: engineTitle, status: isUnsupported || isMetadata ? 'not_run' : (result.execution?.status || 'not_available') },
    { number: '07', title: 'Result consistency', status: isUnsupported || isMetadata ? 'not_run' : (result.verification?.status || 'not_available') },
  ];

  return <section className="panel trust-panel" id="trust-mode">
    <div className="panel-heading"><div><span className="eyebrow">EVIDENCE WORKSPACE</span><h2>Trust Mode</h2></div><span className="trust-mark"><Shield size={15} /> Auditable response</span></div>
    {clarification && !isUnsupported && <div className="clarification-callout"><strong>Clarification requested</strong><p>{result.clarification?.question || result.answer}</p><p>No SQL was executed and no query ID was created for this response. Use a supported option in the response card above to continue.</p></div>}
    {isUnsupported && <div className="clarification-callout clarification-unsupported"><strong>Dataset mismatch — no execution</strong><p>{result.answer}</p>{result.missing_concepts && result.missing_concepts.length > 0 && <p>Missing: <strong>{result.missing_concepts.join(', ')}</strong>. No SQL was compiled or executed for this request.</p>}</div>}
    {isMetadata && <div className="clarification-callout clarification-metadata"><strong>Dataset metadata — answered from registry</strong><p>This response was built from registered dataset metadata. No LLM planning call or database query was made.</p></div>}
    <div className="pipeline-track" aria-label="Pipeline stage status">
      {steps.map((step, index) => <motion.div key={step.number} className="pipeline-step"
        initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0 : 0.2, delay: reduceMotion ? 0 : index * 0.04 }}>
        <span className="step-num">{step.number}</span><strong>{step.title}</strong><StatusBadge status={step.status} />
        {index < steps.length - 1 && <span className="step-connector" />}
      </motion.div>)}
    </div>
    <p className="microcopy">Intent: {result.intent_classification || 'not run'}. Plan source: {result.plan_source || 'not run'}. Dataset: {result.dataset_id || 'tpch_customer'}.</p>
    <div className="evidence-grid">
      <IntentGateStage intentClassification={result.intent_classification} missingConcepts={result.missing_concepts} />
      <EvidenceStage title="Typed query-plan validation" evidence={result.plan_validation} caveat="Passing means the plan used supported fields, operations, typed filters, and a bounded result limit." />
      <EvidenceStage title="Dataset capability match" evidence={result.capability_match} caveat="Passing means the request mapped to the selected dataset's registered capabilities; it does not prove the plan captured every detail." />
      <EvidenceStage title="SQL policy validation" evidence={result.validation} caveat={caveats.validation} />
      <EvidenceStage title={executionTitle} evidence={result.execution} caveat={caveats.execution} />
      <EvidenceStage title="Result consistency verification" evidence={result.verification} caveat={caveats.verification} />
    </div>
    {result.query_plan && <details className="plan-inspection"><summary>Inspect typed query plan</summary><pre>{JSON.stringify(result.query_plan, null, 2)}</pre></details>}
    <div className="trust-footnote"><Check size={15} /><span>Result consistency is not a semantic accuracy benchmark. Review the dataset, SQL, assumptions, returned rows, and Snowflake query ID when present.</span></div>
  </section>;
}
