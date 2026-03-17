import type { AgentResponse } from './types';

const BASE = '/backend';

export async function runAgentUpload(file: File): Promise<AgentResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${BASE}/agent/run-upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail: string }).detail || 'Request failed');
  }

  return res.json() as Promise<AgentResponse>;
}

export async function runAgentText(message: string): Promise<AgentResponse> {
  const res = await fetch(`${BASE}/agent/run-text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail: string }).detail || 'Request failed');
  }

  return res.json() as Promise<AgentResponse>;
}

export async function fetchLog(): Promise<string> {
  const res = await fetch(`${BASE}/agent/log`);
  if (!res.ok) return '';
  return res.text();
}
