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
  error?: string;
}

export interface Comparison {
  contrast: [number, number];
  finding: string;
}

export interface ClaimResult {
  claim_id: number;
  claim_text: string;
  source: Record<string, unknown>;
  study_design?: string;
  comparison: Comparison[];
  subject_results: SubjectResult[];
  error?: string;
}

export interface PaperClaim {
  claim_id: string;
  claim_text: string;
  sources: Array<{ type: string; section?: string; quote?: string; ref?: string }>;
}

export interface AgentResponse {
  study_accession: string;
  // PDF + question path: step-1 claim sentences
  paper_claims: PaperClaim[];
  // Chat / plain-text path
  subject_results: SubjectResult[];
  // PDF-only path
  claims: ClaimResult[];
  // Clarification request from backend
  type?: string;
  question?: string;
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
