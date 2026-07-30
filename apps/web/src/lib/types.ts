export interface Subject {
  subject_accession: string;
  biosample_accession?: string;
  expsample_accession?: string;
  [key: string]: unknown;
}

export interface SubjectResult {
  group_id: number;
  group_name?: string;
  arm_accession?: string;
  experiment_accession?: string;
  tissue_type?: string;
  condition?: string;
  resolvers: Record<string, string>;
  comparison: unknown[];
  subjects: Subject[];
  skipped?: boolean;
  error?: string;
}

export interface Comparison {
  contrast: [number, number];
  finding: string;
}

// Superlative assertion over several contrasts or groups ("the maximum change
// occurred on day 1"). `over`/`winner` index into `comparison` when scope is
// 'contrast', and hold group_ids when scope is 'group'.
export interface Ranking {
  type: 'argmax' | 'argmin';
  scope: 'contrast' | 'group';
  metric: string;
  over: number[];
  winner: number;
  finding: string;
}

export interface ClaimResult {
  claim_id: number;
  claim_text: string;
  source: Record<string, unknown>;
  study_design?: string;
  comparison: Comparison[];
  ranking?: Ranking[];
  subject_results: SubjectResult[];
  error?: string;
}

export interface PaperClaim {
  claim_id: string;
  claim_text: string;
  sources: Array<{ type: string; section?: string; quote?: string; ref?: string }>;
}

export interface FailedFieldCount {
  field: string;
  count: number;
}

export interface CompletnessSummary {
  total_claims: number;
  claims_with_failures: number;
  failed_groups: number;
  data_gap_groups?: number;
  failed_fields: FailedFieldCount[];
}

export interface DataGap {
  group_id: number;
  cohort?: string;
  assay_method?: string;
  time_point?: string;
  arm_accession?: string;
  experiment_accession?: string;
  reason: string;
}

export interface ResolutionFailure {
  field: string;
  original_value: string;
  tried: string;
  result: string;
  immport_candidates?: Record<string, string>[];
}

export interface GroupFailures {
  group_id: number;
  failures: ResolutionFailure[];
}

export interface ClaimSource {
  section?: string;
  quote?: string;
  ref?: string;
  [key: string]: unknown;
}

export interface ClaimFailures {
  claim_id: number | null;
  claim_text: string;
  source?: ClaimSource;
  sources?: ClaimSource[];
  claim_failures?: ResolutionFailure[];
  groups: GroupFailures[];
  data_gaps?: DataGap[];
}

export interface AgentResponse {
  study_accession: string;
  // PDF + question path: step-1 claim sentences
  paper_claims: PaperClaim[];
  // Chat / plain-text path
  subject_results: SubjectResult[];
  // PDF-only path
  claims: ClaimResult[];
  // Clarification request or pdf_upload_required from backend
  type?: string;
  question?: string;
  pubmed_id?: string;
  // ImmPort field resolution completeness
  completeness?: CompletnessSummary;
  // Multi-paper response: one entry per paper when a study maps to multiple papers
  papers?: AgentResponse[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  filename?: string;
  result?: AgentResponse;
  error?: string;
  isLoading?: boolean;
}

export interface RunRecord {
  id: string;
  filename: string;
  study_accession: string;
  timestamp: string;
  result?: AgentResponse;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
}
