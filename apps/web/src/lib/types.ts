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

/** How an assay name was resolved to its OBI term, in fixed display order. */
export type ObiResource =
  | 'exact_original'
  /** Retired: the lexical round that stripped a trailing " assay". Still on 40 stored rows. */
  | 'exact_normalized'
  /** Exact hit on the extractor's technique judgement — the live normalized tier. */
  | 'exact_normalized_llm'
  | 'embedding_llm'
  /** Picked from candidates only the normalized name could retrieve. */
  | 'embedding_llm_normalized'
  | 'unresolved';

export interface AssayObiRow {
  study: string;
  assay: string;
  normalized_name: string;
  sample_type: string;
  readouts: string;
  obi_id: string | null;
  obi_label: string | null;
  resource: ObiResource;
  /** "high" for exact matches, a cosine similarity for LLM-picked ones, null when unresolved. */
  obi_confidence: string | number | null;
}

export interface AssayObiStats {
  total_rows: number;
  papers: number;
  obi_terms: number;
  mapped_rows: number;
  coverage_pct: number;
  by_resource: { resource: ObiResource; count: number }[];
  unresolved_names: string[];
}

export interface AssayObiResponse {
  rows: AssayObiRow[];
  stats: AssayObiStats;
}

// ── the assay extraction workspace ──────────────────────────────────────────
// One paper at a time: what can be run, what a run would cost, what a run is doing, and what
// a run left behind. Everything here except starting a run is free.

/** A paper, by either identifier. The backend accepts one or both. */
export interface PaperRef {
  pubmed_id: string;
  study_accession: string;
}

export interface AssayPaperSummary extends PaperRef {
  paper_source: string;
  paper_title: string | null;
  has_registry: boolean;
  /** How many assays the stored deliverable holds; null when never run. */
  assays: number | null;
  updated_at: string | null;
}

export type AssayRoundName = 'extract' | 'verify' | 'correct' | 'obi' | 'canonicalize';

export interface AssayEstimateRound {
  round: number;
  name: AssayRoundName;
  /** null when the round cannot be sized yet — render "?", never a guess. */
  calls: number | null;
  /** false where the CLI prints "~": sized from the previous run, which this run re-extracts. */
  exact: boolean;
  basis: string;
  assays: number | null;
  rejected: number | null;
  free_matches: number | null;
  /** Round 4: the names the OBI vocabulary misses — the ones that cost. */
  misses: string[];
  entries: number | null;
  groups: number | null;
  /** Round 5: entries that would fold onto one OBI term. */
  folds: { key: string; members: string[] }[];
}

export interface AssayEstimate extends PaperRef {
  paper_source: string;
  paper_title: string;
  source_chars: number;
  registry_dir: string;
  registry_dir_display: string;
  has_registry: boolean;
  has_verification: boolean;
  has_obi: boolean;
  rounds: AssayEstimateRound[];
  /** null unless every round is known — a partial sum is never the bill. */
  total_calls: number | null;
  total_calls_known: boolean;
  caveat: string | null;
}

export interface AssayEvidence {
  section?: string | null;
  sentence_ids?: string[];
  quote?: string | null;
}

/** The deliverable's shape. `name_in_paper` is a list after round 5 and a string before it. */
export interface AssayBenchmarkEntry {
  name_in_paper: string[] | string;
  aliases?: string[] | null;
  source?: string | null;
  evidence?: AssayEvidence | null;
  additional_evidence?: { name_in_paper?: string; evidence?: AssayEvidence }[];
  /** Only on the full ten-field record. */
  normalized_name?: string | null;
  platform?: string | null;
  sample_type?: string | null;
  readouts?: string | null;
}

export interface AssayObiEntry {
  obi_id?: string | null;
  obi_label?: string | null;
  resource?: string | null;
  obi_confidence?: string | number | null;
}

/** Everything a finished run produced, live or read back off disk. */
export interface AssayRunResult {
  study_accession?: string;
  pubmed_id?: string;
  paper_title?: string | null;
  paper_source?: string | null;
  assays: Record<string, AssayBenchmarkEntry>;
  /** Present only on a live result; the stored read exposes it as `benchmark`. */
  benchmark?: Record<string, AssayBenchmarkEntry>;
  /** null when round 4 was skipped or failed — not the same as "found nothing". */
  obi?: Record<string, AssayObiEntry> | null;
  quote_check?: Record<string, unknown> | null;
  verification?: Record<string, unknown> | null;
  corrections?: Record<string, unknown> | null;
  merges?: Record<string, unknown> | null;
  dropped?: Record<string, { reason?: string }>;
  rounds?: Record<string, Record<string, unknown>>;
  contract_warnings?: string[];
  meta?: {
    llm_calls?: number;
    registry_path?: string;
    benchmark_path?: string;
    obi_path?: string | null;
    note?: string;
  };
}

export interface AssayRegistryResponse extends AssayRunResult {
  benchmark: Record<string, AssayBenchmarkEntry>;
  updated_at: string | null;
  registry_dir_display: string;
  files: Record<string, string>;
}

export type AssayJobState = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

export interface AssayRoundProgress {
  state?: 'running' | 'done' | 'skipped' | 'failed';
  calls?: number;
  done?: number;
  total?: number;
  item?: string;
  verdict?: string;
  assays?: number;
  dropped?: number;
  [key: string]: unknown;
}

export interface AssayJobProgress {
  rounds: Partial<Record<AssayRoundName, AssayRoundProgress>>;
  calls: number;
  current: AssayRoundName | null;
}

export interface AssayJob extends PaperRef {
  id: string;
  state: AssayJobState;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  estimate: AssayEstimate | null;
  acknowledged_calls: number | null;
  /** The estimate moved between the gate and the run. Recorded, never blocking. */
  estimate_drift: { acknowledged: number; estimated: number | null } | null;
  progress: AssayJobProgress;
  result: AssayRunResult | null;
  error: string | null;
  cancel_requested: boolean;
}

/**
 * Every reason not to trust an entry, as one flat list.
 *
 * CLAUDE.md requires each of these be reported rather than summarised, so they are collected
 * into one shape and rendered by one `.map` — a panel that groups, counts or paginates is how
 * one of them quietly stops being shown.
 */
export type FindingKind =
  | 'WARNING'
  | 'REVIEW'
  | 'REJECT'
  | 'DROPPED'
  | 'MERGED'
  | 'UNMAPPED'
  | 'CORRECT FAILED'
  | 'OBI FAILED'
  | 'QUOTE MISSING'
  | 'SOURCE MISMATCH';

export interface Finding {
  kind: FindingKind;
  /** The assay the finding is about, or '' for a run-level one. */
  subject: string;
  detail: string;
  /** REVIEW/REJECT only: the field verdicts the record verdict was derived from. */
  fields?: { field: string; verdict: string; reason: string }[];
}

/** The result of adding a paper to the corpus. `created` is false when it was already there. */
export interface AssayPaperAddResult {
  created: boolean;
  paper: AssayPaperSummary;
  message: string;
}

/** One paper a typed identifier could mean. Extends the corpus summary, so it is usable
 *  anywhere an AssayPaperSummary is — including estimate, run and registry calls. */
export interface PaperCandidate extends AssayPaperSummary {
  /** From study_pubmed. Differs from `paper_title` (parsed from the XML), and is the only one
   *  that exists for a paper not yet fetched — so it is what a disambiguation list shows. */
  title: string | null;
  journal: string | null;
  year: number | null;
  authors: string | null;
  doi: string | null;
  /** False when the pair came from a filename rather than from ImmPort. */
  in_db: boolean;
  /** False when ImmPort's pubmed_id for this study is not a PubMed ID — "TBD", "Not
   *  Applicable" or a PMC id. The study is shown but cannot be run. */
  usable: boolean;
  unusable_reason: string | null;
  has_xml: boolean;
  /** A run already under way for this paper. Adopt it; never start a second. */
  active_job_id: string | null;
}

export interface ResolveResponse {
  query: string;
  shape: 'pubmed_id' | 'study_accession' | 'pmc_id';
  normalized: string;
  pmc_id: string | null;
  pubmed_id: string;
  study_accession: string;
  candidates: PaperCandidate[];
  total: number;
  source: 'db' | 'local' | 'db+local' | 'none';
  /** The ImmPort database could not be reached; only local files were consulted. */
  degraded: boolean;
  warning: string | null;
  resolved_via: string;
  /** Set only when `candidates` is empty. */
  reason: string | null;
}

/** Whether ImmPort records an experiment for a corpus assay. */
export type ImmportStatus = 'matched' | 'absent' | 'no_experiments' | 'unknown_study';

export interface AssayImmportRow {
  study: string;
  study_accession: string;
  assay: string;
  experiment_accession: string | null;
  /** ImmPort's own name for the technique. Null unless matched. */
  measurement_technique: string | null;
  /** "SQL" for a free match, "LLM" when the resolver was asked. */
  method: string | null;
  status: ImmportStatus;
  study_experiments: number;
}

export interface AssayImmportStats {
  total: number;
  matched: number;
  absent: number;
  no_experiments: number;
  unknown_study: number;
  /** One model call each — the only rows a paid resolve pass could change. */
  resolvable: number;
  studies_without_experiments: string[];
}

export interface AssayImmportResponse {
  rows: AssayImmportRow[];
  stats: AssayImmportStats;
  degraded: boolean;
  warning: string | null;
}
