import type {
  AgentResponse,
  AssayEstimate,
  DataAvailabilityCorpusResponse,
  DataAvailabilityResult,
  AssayImmportResponse,
  AssayJob,
  AssayObiResponse,
  AssayObiRow,
  AssayPaperAddResult,
  AssayPaperSummary,
  AssayRegistryResponse,
  PaperRef,
  ResolveResponse,
} from './types';

const BASE = '/backend';
// A chat message can start a full paper run (v8 extraction: 13 LLM calls, then grouping).
const CHAT_TIMEOUT_MS = 900_000;
const PAPER_TIMEOUT_MS = 900_000;

async function parseErrorDetail(res: Response): Promise<string> {
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    return body.detail || res.statusText || 'Request failed';
  }
  const text = await res.text().catch(() => '');
  return text || res.statusText || 'Request failed';
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    if (err instanceof TypeError) {
      throw new Error('Network error: backend is unreachable. Check API server and NEXT_PUBLIC_BACKEND_ORIGIN.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function runAgentUpload(file: File, question?: string): Promise<AgentResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (question && question.trim()) {
    formData.append('question', question.trim());
  }

  const res = await fetchWithTimeout(`${BASE}/agent/run-paper`, {
    method: 'POST',
    body: formData,
  }, PAPER_TIMEOUT_MS);

  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }

  return res.json() as Promise<AgentResponse>;
}

export async function runAgentText(message: string): Promise<AgentResponse> {
  const res = await fetchWithTimeout(`${BASE}/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }, CHAT_TIMEOUT_MS);

  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }

  return res.json() as Promise<AgentResponse>;
}

export async function fetchLog(): Promise<string> {
  const res = await fetch(`${BASE}/agent/log`);
  if (!res.ok) return '';
  return res.text();
}

export async function fetchAssayObi(): Promise<AssayObiResponse> {
  // A file read on the backend, not an LLM call — keep the timeout short.
  const res = await fetchWithTimeout(`${BASE}/agent/assay-obi`, {}, 15_000);

  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }

  return res.json() as Promise<AssayObiResponse>;
}

// ── the assay extraction workspace ──────────────────────────────────────────
// Every call here returns immediately: the long work now happens behind a job, so none of these
// needs the paper endpoint's minutes-long timeout, and next.config's proxyTimeout stops
// mattering for this page.

const ASSAY_TIMEOUT_MS = 20_000;

/** The backend no longer remembers this run — it restarted. The files it wrote are still there. */
export class JobGoneError extends Error {}

/** A run is already under way for this paper. Adopt it; do not start a second one. */
export class ActiveRunError extends Error {
  constructor(message: string, readonly jobId: string | null) {
    super(message);
  }
}

/**
 * PMC has no open-access record (404) or will not serve the full text (422). Not worth
 * retrying: the way forward is uploading the paper's PDF.
 */
export class PaperNotDownloadableError extends Error {}

async function getJson<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = ASSAY_TIMEOUT_MS
): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, init, timeoutMs);
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json() as Promise<T>;
}

function paperQuery(paper: PaperRef): string {
  return new URLSearchParams({
    pubmed_id: paper.pubmed_id,
    study_accession: paper.study_accession,
  }).toString();
}

export async function fetchAssayPapers(): Promise<AssayPaperSummary[]> {
  const body = await getJson<{ papers: AssayPaperSummary[] }>('/agent/assay-papers');
  return body.papers;
}

/** What a run would cost. Free — this is the gate, and asking must never spend. */
export async function estimateAssayRun(paper: PaperRef): Promise<AssayEstimate> {
  return getJson<AssayEstimate>('/agent/assays/estimate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(paper),
  });
}

/** What a previous run left on disk, or null when there is none. Free. */
export async function fetchAssayRegistry(paper: PaperRef): Promise<AssayRegistryResponse | null> {
  const res = await fetchWithTimeout(
    `${BASE}/agent/assays/registry?${paperQuery(paper)}`, {}, ASSAY_TIMEOUT_MS);
  // Not an error: most papers have simply never been run.
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<AssayRegistryResponse>;
}

/**
 * One paper's rows in the Corpus table's shape — benchmark pairing and paper link included —
 * built by the same backend function as the corpus file. Empty when never run. Free.
 */
export async function fetchAssayTable(paper: PaperRef): Promise<AssayObiRow[]> {
  const res = await fetchWithTimeout(
    `${BASE}/agent/assays/table?${paperQuery(paper)}`, {}, ASSAY_TIMEOUT_MS);
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return ((await res.json()) as { rows: AssayObiRow[] }).rows;
}

/** Where a paper's data lives, as a previous run wrote it; null when never run. Free. */
export async function fetchDataAvailability(paper: PaperRef): Promise<DataAvailabilityResult | null> {
  const res = await fetchWithTimeout(
    `${BASE}/agent/data-availability?${paperQuery(paper)}`, {}, ASSAY_TIMEOUT_MS);
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<DataAvailabilityResult | null>;
}

/** Every paper's stored data repositories, keyed `<PMID>_<SDY>` like the corpus rows. A file read. */
export async function fetchDataAvailabilityCorpus(): Promise<DataAvailabilityCorpusResponse> {
  return getJson<DataAvailabilityCorpusResponse>('/agent/data-availability/corpus', {}, 15_000);
}

/**
 * Start a run. **This is the only call on the page that spends money.**
 *
 * `acknowledgedCalls` is the number the estimate card showed, echoed back — the backend refuses
 * without it. Pass null only when the estimate itself reported the total as unknown.
 */
export async function startAssayRun(
  paper: PaperRef,
  acknowledgedCalls: number | null
): Promise<AssayJob> {
  const res = await fetchWithTimeout(`${BASE}/agent/assays/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...paper,
      acknowledged_calls: acknowledgedCalls,
      acknowledged_unknown: acknowledgedCalls === null,
    }),
  }, ASSAY_TIMEOUT_MS);

  if (res.status === 409) {
    const detail = await parseErrorDetail(res);
    // The id is in the message so the caller can adopt the run rather than buy the answer twice.
    const found = detail.match(/job ([0-9a-f]{32})/);
    throw new ActiveRunError(detail, found ? found[1] : null);
  }
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<AssayJob>;
}

export async function fetchAssayJob(jobId: string): Promise<AssayJob> {
  const res = await fetchWithTimeout(
    `${BASE}/agent/assays/runs/${jobId}`, {}, ASSAY_TIMEOUT_MS);
  if (res.status === 404) throw new JobGoneError(await parseErrorDetail(res));
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<AssayJob>;
}

/** Stop a run. Free to ask; what it already spent stays spent. */
export async function cancelAssayRun(jobId: string): Promise<AssayJob> {
  return getJson<AssayJob>(`/agent/assays/runs/${jobId}/cancel`, { method: 'POST' });
}

/**
 * Add a paper to the corpus by PubMed ID. Free — two NCBI requests, no model calls.
 *
 * A longer timeout than the other free calls: this is two round trips to NCBI rather than a
 * local file read. The backend distinguishes 404 (no open-access record), 422 (in PMC but not
 * as usable full text) and 502 (NCBI unreachable), and each detail says what to do about it —
 * so the caller should surface the message rather than replacing it with its own.
 */
export async function addAssayPaper(
  paper: PaperRef,
  force = false
): Promise<AssayPaperAddResult> {
  const res = await fetchWithTimeout(`${BASE}/agent/assay-papers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...paper, force }),
  }, 30_000);
  if (res.status === 404 || res.status === 422) {
    throw new PaperNotDownloadableError(await parseErrorDetail(res));
  }
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<AssayPaperAddResult>;
}

/** Add a paper PMC will not serve by uploading its PDF. Free: it is only stored. */
export async function uploadAssayPaper(
  paper: PaperRef,
  file: File,
  force = false
): Promise<AssayPaperAddResult> {
  const form = new FormData();
  form.append('pubmed_id', paper.pubmed_id);
  form.append('study_accession', paper.study_accession);
  form.append('force', String(force));
  form.append('file', file);
  return getJson<AssayPaperAddResult>('/agent/assay-papers/upload', {
    method: 'POST',
    body: form,
  }, 120_000);
}

/**
 * One identifier -> every paper it could mean. Free.
 *
 * Returns a list and never picks: SDY212 has six papers and PubMed ID 26682988 belongs to five
 * studies, so zero, one and six candidates are all ordinary answers. Only a string that is not
 * an identifier at all throws (400).
 */
export async function resolvePaper(query: string): Promise<ResolveResponse> {
  return getJson<ResolveResponse>('/agent/assays/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
}

/**
 * Whether ImmPort records an experiment for each corpus assay.
 *
 * The same resolver the query builder uses — SQL first, then one LLM call per row SQL cannot
 * place, cached server-side — so an assay this calls present is one a claim query would find. Kept a separate call from the assay table rather than folded
 * into it, so the table still renders when ImmPort is unreachable.
 */
export async function fetchAssayImmport(): Promise<AssayImmportResponse> {
  // An uncached corpus sweep makes one sequential model call per row SQL misses.
  return getJson<AssayImmportResponse>('/agent/assay-immport', {}, 600_000);
}

/** Ask the resolver about rows the free pass could not place. **One model call per row.** */
export async function resolveAssayImmport(
  rows: unknown[],
  acknowledgedCalls: number
): Promise<AssayImmportResponse> {
  return getJson<AssayImmportResponse>('/agent/assay-immport/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows, acknowledged_calls: acknowledgedCalls }),
  }, 600_000);
}

/** Does ImmPort register experiments for these specific assays? SQL, then the cached LLM fallback. */
export async function checkAssayImmport(rows: unknown[]): Promise<AssayImmportResponse> {
  return getJson<AssayImmportResponse>('/agent/assay-immport/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows }),
  }, 600_000);
}
