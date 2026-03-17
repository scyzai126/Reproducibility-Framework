export interface SubjectResult {
  group_id: string;
  group_name: string;
  arm_accession: string;
  experiment_accession: string;
  tissue_type: string;
  condition: string;
  subjects: Record<string, unknown>[];
  error?: string;
}

export interface AgentResponse {
  study_accession: string;
  subject_results: SubjectResult[];
}

export interface RunRecord {
  id: string;
  timestamp: string;
  filename: string;
  study_accession: string;
  result: AgentResponse;
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

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
}
