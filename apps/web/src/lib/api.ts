import type { AgentResponse, AssayObiResponse } from './types';

const BASE = '/backend';
const CHAT_TIMEOUT_MS = 120_000;
const PAPER_TIMEOUT_MS = 420_000;

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
