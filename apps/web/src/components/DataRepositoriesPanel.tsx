'use client';

import { useEffect, useState } from 'react';
import { fetchDataAvailability } from '@/lib/api';
import type { DataAvailabilityResult, DataRepository } from '@/lib/types';

function size(bytes: number | null | undefined): string {
  if (bytes == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let n = bytes;
  let unit = 0;
  while (n >= 1024 && unit < units.length - 1) {
    n /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${n} B` : `${n.toFixed(1)} ${units[unit]}`;
}

function Lines({ label, lines, tone }: { label: string; lines?: string[]; tone: string }) {
  if (!lines?.length) return null;
  // Every line, flat — the same rule as the assay findings: a failure one click away is unread.
  return (
    <ul className="space-y-0.5">
      {lines.map((line, i) => (
        <li key={i} className={`text-[11px] leading-snug ${tone}`}>
          <span className="font-medium">{label}</span> {line}
        </li>
      ))}
    </ul>
  );
}

function RepositoryRow({ repo }: { repo: DataRepository }) {
  const download = repo.download?.https || repo.download?.ftp;
  return (
    <tr className="border-b border-gray-100 last:border-0 align-top">
      <td className="px-3 py-2 text-gray-900 whitespace-nowrap">{repo.repository}</td>
      <td className="px-3 py-2 font-mono whitespace-nowrap">
        {repo.landing_page ? (
          <a href={repo.landing_page} target="_blank" rel="noopener noreferrer"
             className="text-emerald-700 hover:underline">
            {repo.accession}
          </a>
        ) : (
          repo.accession
        )}
      </td>
      <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{repo.access ?? '—'}</td>
      <td className="px-3 py-2 text-gray-500 tabular-nums whitespace-nowrap">
        {repo.file_count != null ? `${repo.file_count} files · ${size(repo.total_size_bytes)}` : '—'}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {download ? (
          <a href={download} target="_blank" rel="noopener noreferrer"
             className="text-emerald-700 hover:underline">
            download folder
          </a>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-[11px] text-amber-700 max-w-[260px]">{repo.review ?? ''}</td>
    </tr>
  );
}

/**
 * Where the paper's own data lives: the repositories the data-availability step found and
 * confirmed. Given `result` (a run that just finished) it shows that; otherwise it reads what a
 * previous run stored, for free.
 */
export default function DataRepositoriesPanel({
  pubmedId,
  studyAccession,
  result,
}: {
  pubmedId: string;
  studyAccession: string;
  result?: DataAvailabilityResult | null;
}) {
  const [stored, setStored] = useState<DataAvailabilityResult | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (result !== undefined) return;
    fetchDataAvailability({ pubmed_id: pubmedId, study_accession: studyAccession })
      .then(setStored)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [pubmedId, studyAccession, result]);

  const data = result !== undefined ? result : stored;
  const repos = data?.data_repositories ?? [];
  const unconfirmed = data?.unconfirmed ?? [];

  return (
    <section className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <header className="px-4 py-3 border-b border-gray-100 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-gray-900">Data repositories</h3>
        <span className="text-xs text-gray-400">
          where this study deposited its own data
          {data?.llm_calls != null && ` · ${data.llm_calls} call${data.llm_calls === 1 ? '' : 's'}`}
        </span>
      </header>
      <div className="px-4 py-3 space-y-3">
        {error && <p className="text-xs text-rose-700">{error}</p>}
        {data === undefined && !error && <p className="text-xs text-gray-400">Loading…</p>}
        {data === null && (
          <p className="text-xs text-gray-400">
            Not looked for yet — the next run of this paper finds its data repositories too.
          </p>
        )}
        {data?.error && (
          <p className="text-xs text-rose-700">
            The data step failed: {data.error}. The assays from the same run are unaffected.
          </p>
        )}
        {data && !data.error && repos.length === 0 && (
          <p className="text-xs text-gray-500">No repository holding this study&apos;s own data was confirmed.</p>
        )}
        {repos.length > 0 && (
          <div className="overflow-x-auto border border-gray-200 rounded-lg">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr className="text-left text-gray-500">
                  <th className="px-3 py-2 font-medium">Repository</th>
                  <th className="px-3 py-2 font-medium">Accession</th>
                  <th className="px-3 py-2 font-medium">Access</th>
                  <th className="px-3 py-2 font-medium">Files</th>
                  <th className="px-3 py-2 font-medium">Download</th>
                  <th className="px-3 py-2 font-medium">Review</th>
                </tr>
              </thead>
              <tbody>
                {repos.map((repo) => (
                  <RepositoryRow key={`${repo.repository}-${repo.accession}`} repo={repo} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {unconfirmed.length > 0 && (
          <div>
            <p className="text-[11px] font-medium text-gray-500 mb-1">
              Named as deposited, but the repository could not confirm:
            </p>
            <ul className="space-y-0.5">
              {unconfirmed.map((u) => (
                <li key={`${u.repository}-${u.accession}`} className="text-[11px] text-gray-500">
                  <span className="font-mono">{u.repository} {u.accession}</span>
                  {u.status && ` — ${u.status}`}
                  {u.detail && `: ${u.detail}`}
                </li>
              ))}
            </ul>
          </div>
        )}
        <Lines label="REVIEW" lines={data?.reviews} tone="text-amber-700" />
        <Lines label="WARNING" lines={data?.warnings} tone="text-amber-700" />
        <Lines label="DROPPED" lines={data?.dropped} tone="text-gray-500" />
        <Lines label="NOTE" lines={data?.notes} tone="text-gray-400" />
      </div>
    </section>
  );
}
