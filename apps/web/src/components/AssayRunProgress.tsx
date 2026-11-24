'use client';

import { useEffect, useState } from 'react';
import type { AssayJob, AssayRoundName, AssayRoundProgress } from '@/lib/types';

interface Props {
  job: AssayJob;
  onCancel: () => void;
  cancelling?: boolean;
}

const ROUNDS: { name: AssayRoundName; label: string }[] = [
  { name: 'extract', label: 'extract' },
  { name: 'verify', label: 'verify' },
  { name: 'correct', label: 'correct' },
  { name: 'obi', label: 'OBI map' },
  { name: 'canonicalize', label: 'canonicalize' },
  { name: 'judge', label: 'judge folds' },
  // Runs in parallel with the six rounds above, not after them.
  { name: 'data_availability', label: 'data repositories' },
];

function elapsed(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt) return '';
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((end - new Date(startedAt).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function dotClass(round: AssayRoundProgress | undefined): string {
  switch (round?.state) {
    case 'done':
      return 'bg-emerald-600';
    case 'running':
      return 'bg-emerald-500 animate-pulse';
    case 'failed':
      return 'bg-rose-500';
    case 'skipped':
      return 'bg-gray-200';
    default:
      return 'bg-gray-200';
  }
}

/**
 * What a round can honestly say about itself.
 *
 * Only round 2 reports a position: correct_registry gathers its field calls and reports nothing
 * until they all return, and the OBI mapper runs in a worker thread. So those two show a total
 * and no bar. A synthetic bar would be a number the backend never produced.
 */
function roundDetail(name: AssayRoundName, round: AssayRoundProgress | undefined): string {
  if (!round) return 'queued';
  if (round.state === 'skipped') return 'skipped';
  if (round.state === 'failed') return 'failed — rounds before it are intact on disk';
  const calls = round.calls != null ? `${round.calls} call${round.calls === 1 ? '' : 's'}` : '';
  if (round.state === 'done') {
    if (name === 'extract') return `${calls} · ${round.assays} assays`;
    if (name === 'correct' && round.dropped) return `${calls} · ${round.dropped} set aside`;
    if (name === 'data_availability' && typeof round.repositories === 'number') {
      return `${calls} · ${round.repositories} repositor${round.repositories === 1 ? 'y' : 'ies'}`;
    }
    return calls || 'done';
  }
  if (name === 'verify' && round.total) return `${round.done ?? 0}/${round.total} assays`;
  if (round.total) return `${round.total} to do`;
  return 'running…';
}

/**
 * The live view of a paid run.
 *
 * It keeps ticking while the tab is open, but the run does not depend on it: the chain is on a
 * task server-side, so closing the tab does not stop the spending, and that is the honest thing
 * to show rather than a progress bar that implies the browser is driving.
 */
export default function AssayRunProgress({ job, onCancel, cancelling }: Props) {
  const [, tick] = useState(0);
  const live = job.state === 'queued' || job.state === 'running';

  // The elapsed clock is the only thing here that changes without a poll.
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [live]);

  return (
    <section className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <header className="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-medium text-gray-700">
            {live ? 'Running' : `Run ${job.state}`}
          </h2>
          <p className="text-xs text-gray-400 font-mono mt-0.5">
            {job.study_accession} · {job.pubmed_id}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 tabular-nums">
            {job.progress.calls} call{job.progress.calls === 1 ? '' : 's'} spent
            {job.started_at ? ` · ${elapsed(job.started_at, job.finished_at)}` : ''}
          </span>
          {live && (
            <button
              onClick={onCancel}
              disabled={cancelling}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60"
            >
              {cancelling ? 'Stopping…' : 'Stop'}
            </button>
          )}
        </div>
      </header>

      <ol className="px-4 py-3 space-y-2">
        {ROUNDS.map(({ name, label }, index) => {
          const round = job.progress.rounds[name];
          const showBar = name === 'verify' && round?.state === 'running' && !!round.total;
          return (
            <li key={name} className="flex items-center gap-3 text-xs">
              <span className="text-gray-300 tabular-nums w-3">{index + 1}</span>
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotClass(round)}`} />
              <span
                className={`w-24 flex-shrink-0 font-medium ${
                  round?.state === 'skipped' ? 'text-gray-400 line-through' : 'text-gray-800'
                }`}
              >
                {label}
              </span>
              <span className="text-gray-500 flex-shrink-0">{roundDetail(name, round)}</span>
              {showBar && (
                <span className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden max-w-[160px]">
                  <span
                    className="block h-full bg-emerald-500 transition-all"
                    style={{ width: `${(100 * (round.done ?? 0)) / (round.total || 1)}%` }}
                  />
                </span>
              )}
              {round?.state === 'running' && !showBar && (
                <span className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden max-w-[160px]">
                  {/* No position to show: this round reports nothing until it returns. */}
                  <span className="block h-full w-1/3 bg-emerald-300 animate-pulse" />
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {live && (
        <footer className="px-4 py-2.5 border-t border-gray-200 bg-gray-50">
          <p className="text-xs text-gray-500">
            Stopping does not refund: calls already sent are already billed, and the files this
            run has written stay on disk. The run continues if you close this tab.
          </p>
        </footer>
      )}

      {job.estimate_drift && (
        <footer className="px-4 py-2.5 border-t border-gray-200 bg-amber-50">
          <p className="text-xs text-amber-800">
            The estimate moved between the gate and the run: you approved{' '}
            {job.estimate_drift.acknowledged}, the run was sized at{' '}
            {job.estimate_drift.estimated ?? 'unknown'}. Rounds 2 and 3 are sized from the
            previous run, so this is expected rather than wrong.
          </p>
        </footer>
      )}
    </section>
  );
}
