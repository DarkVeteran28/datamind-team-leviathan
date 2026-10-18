export type CheckStatus = 'passed' | 'failed' | 'skipped' | 'not_run' | string;

export interface EvidenceCheck {
  name?: string;
  status?: CheckStatus;
  detail?: string;
}

export interface StageEvidence {
  status?: CheckStatus;
  checks?: EvidenceCheck[];
  engine?: string;
  dataset_id?: string;
}

export interface ClarificationOption {
  label?: string;
  column?: string;
  direction?: string;
}

export interface QueryResponse {
  answer: string;
  dataset_id?: string;
  plan_source?: string;
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
  dataset_id?: string;
}

export interface DatasetField {
  type: string;
  unit?: string;
  description?: string;
}

export interface DatasetMetadata {
  id: string;
  name: string;
  description: string;
  availability: string;
  fields: Record<string, DatasetField>;
  units?: Record<string, string>;
  license?: string;
  attribution?: string;
  source_url?: string;
  documentation_url?: string;
  repository_url?: string;
  default?: boolean;
}

export interface DatasetCatalogResponse {
  default_dataset_id: string;
  datasets: DatasetMetadata[];
}

export interface HistoryEntry {
  id: string;
  question: string;
  timestamp: string;
  result: QueryResponse;
}
