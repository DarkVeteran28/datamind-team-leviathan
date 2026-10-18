export type CheckStatus = 'passed' | 'failed' | 'skipped' | 'not_run' | string;

export interface EvidenceCheck {
  name?: string;
  status?: CheckStatus;
  detail?: string;
}

export interface StageEvidence {
  status?: CheckStatus;
  checks?: EvidenceCheck[];
}

export interface ClarificationOption {
  label?: string;
  column?: string;
  direction?: string;
}

export interface QueryResponse {
  answer: string;
  sql?: string | null;
  sql_parameters?: unknown[];
  query_plan?: Record<string, unknown> | null;
  plan_validation?: StageEvidence;
  outcome?: string;
  columns?: string[];
  rows?: unknown[][];
  query_id?: string | null;
  assumptions?: string[];
  warnings?: string[];
  row_count?: number;
  validation?: StageEvidence;
  execution?: StageEvidence;
  verification?: StageEvidence;
  clarification?: {
    required?: boolean;
    question?: string | null;
    options?: ClarificationOption[];
  };
}

export interface QueryRequest {
  question: string;
}

export interface HistoryEntry {
  id: string;
  question: string;
  timestamp: string;
  result: QueryResponse;
}
