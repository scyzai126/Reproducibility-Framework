'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import AssayBenchmarkView from './AssayBenchmarkView';
import AssayEstimateCard from './AssayEstimateCard';
import AssayFindingsPanel from './AssayFindingsPanel';
import AssayPaperPicker from './AssayPaperPicker';
import AssayRunProgress from './AssayRunProgress';
import {
  ActiveRunError,
  JobGoneError,
  cancelAssayRun,
  estimateAssayRun,
  fetchAssayJob,
  fetchAssayPapers,
  fetchAssayRegistry,
  startAssayRun,
} from '@/lib/api';
import { collectFindings } from '@/lib/findings';
import type {
  AssayEstimate,
  AssayJob,
  AssayPaperSummary,
  AssayRegistryResponse,
  PaperRef,
} from '@/lib/types';

const JOB_KEY = 'assay_extract_job';
const POLL_MS = 1_500;
const POLL_BACKOFF_MS = 3_000;
/** After this many consecutive transport failures, say so rather than polling on in silence. */
const LOST_CONTACT_AFTER = 5;

type Stored = { jobId: string; pubmed_id: string; study_accession: string };

function readStoredJob(): Stored | null {
  try {
    const raw = localStorage.getItem(JOB_KEY);
    return raw ? (JSON.parse(raw) as Stored) : null;
  } catch {
    return null;
  }
}

function writeStoredJob(value: Stored | null) {
  try {
    if (value) localStorage.setItem(JOB_KEY, JSON.stringify(value));
    else localStorage.removeItem(JOB_KEY);
  } catch {
    // A browser that refuses storage costs us the resume, not the run.
  }
}

function isTerminal(job: AssayJob | null): boolean {
  return !!job && (job.state === 'done' || job.state === 'error' || job.state === 'cancelled');
}

function Notice({ tone, children }: { tone: 'gray' | 'amber' | 'rose'; children: React.ReactNode }) {
  const tones = {
    gray: 'border-gray-200 bg-gray-50 text-gray-600',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    rose: 'border-rose-200 bg-rose-50 text-rose-700',
  };
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>
  );
}

/**
 * Pick a paper, see what a run costs, run it, read the result.
 *
 * The shape of this component follows CLAUDE.md's cost rule: everything it does on its own is
 * free — listing papers, reading what a previous run left on disk, asking for an estimate — and
 * the single paid action sits behind an explicit confirmation on the estimate card. A paper is
 * never re-run because a page loaded.
 */
export default function AssayExtractPanel() {
  const [papers, setPapers] = useState<AssayPaperSummary[]>([]);
  const [paper, setPaper] = useState<AssayPaperSummary | null>(null);
  const [estimate, setEstimate] = useState<AssayEstimate | null>(null);
  const [registry, setRegistry] = useState<AssayRegistryResponse | null>(null);
  const [job, setJob] = useState<AssayJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lostContact, setLostContact] = useState(false);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failures = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  }, []);

  /** Load what a previous run left. Free, so it is safe to do on selection. */
  const loadRegistry = useCallback(async (ref: PaperRef) => {
    try {
      setRegistry(await fetchAssayRegistry(ref));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  /**
   * Poll one job to a terminal state.
   *
   * A `setTimeout` re-armed after each response rather than a `setInterval`, so a slow reply
   * cannot stack requests on a single-process dev server. Transport failures widen the interval
   * and are reported after a few in a row — never abandoned, because the run is spending money
   * whether or not the browser is watching.
   */
  const poll = useCallback((jobId: string) => {
    stopPolling();
    const step = async () => {
      try {
        const next = await fetchAssayJob(jobId);
        failures.current = 0;
        setLostContact(false);
        setJob(next);
        if (isTerminal(next)) {
          writeStoredJob(null);
          // Whatever the run wrote is now the paper's stored result, terminal state or not:
          // a cancelled run usually leaves rounds 1-3 complete.
          void loadRegistry({
            pubmed_id: next.pubmed_id,
            study_accession: next.study_accession,
          });
          return;
        }
        pollTimer.current = setTimeout(step, POLL_MS);
      } catch (err) {
        if (err instanceof JobGoneError) {
          // The normal case under `uvicorn --reload`, not an edge one.
          writeStoredJob(null);
          setJob(null);
          setNotice(
            'That run’s progress was lost when the backend restarted — anything it wrote is ' +
              'still on disk, and is shown below.'
          );
          return;
        }
        failures.current += 1;
        if (failures.current >= LOST_CONTACT_AFTER) setLostContact(true);
        pollTimer.current = setTimeout(step, POLL_BACKOFF_MS);
      }
    };
    void step();
  }, [loadRegistry, stopPolling]);

  // On mount: the paper list, and any run this browser was watching before a refresh.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchAssayPapers();
        if (cancelled) return;
        setPapers(list);

        const stored = readStoredJob();
        if (stored) {
          const match = list.find(
            (p) =>
              p.pubmed_id === stored.pubmed_id && p.study_accession === stored.study_accession
          );
          if (match) {
            setPaper(match);
            void loadRegistry(match);
          }
          poll(stored.jobId);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadRegistry, poll]);

  useEffect(() => stopPolling, [stopPolling]);

  const selectPaper = useCallback(
    async (next: AssayPaperSummary) => {
      stopPolling();
      setPaper(next);
      setEstimate(null);
      setRegistry(null);
      setJob(null);
      setError(null);
      setNotice(null);
      setLostContact(false);
      const ref = { pubmed_id: next.pubmed_id, study_accession: next.study_accession };
      await loadRegistry(ref);
      try {
        setEstimate(await estimateAssayRun(ref));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [loadRegistry, stopPolling]
  );

  /** The only thing on this page that spends. Reached solely from the estimate card. */
  const confirmRun = useCallback(async () => {
    if (!paper || !estimate) return;
    setStarting(true);
    setError(null);
    setNotice(null);
    const ref = { pubmed_id: paper.pubmed_id, study_accession: paper.study_accession };
    try {
      const started = await startAssayRun(ref, estimate.total_calls);
      setJob(started);
      writeStoredJob({ jobId: started.id, ...ref });
      poll(started.id);
    } catch (err) {
      if (err instanceof ActiveRunError && err.jobId) {
        // Adopt it. Starting a second run would buy the same answer twice.
        setNotice('A run was already under way for this paper, so this is that one.');
        writeStoredJob({ jobId: err.jobId, ...ref });
        poll(err.jobId);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setStarting(false);
    }
  }, [estimate, paper, poll]);

  const stopRun = useCallback(async () => {
    if (!job) return;
    setCancelling(true);
    try {
      setJob(await cancelAssayRun(job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCancelling(false);
    }
  }, [job]);

  // The live result when there is one, otherwise whatever is on disk. Both carry the same
  // findings, so a result does not depend on having watched the run that produced it.
  const running = job?.state === 'running' || job?.state === 'queued';
  const result = job?.result ?? registry ?? null;
  const benchmark = job?.result
    ? job.result.assays
    : registry?.benchmark ?? {};
  const notCanonical = (result?.rounds?.obi as { source?: string } | undefined)?.source === 'failed';
  const showEstimate = estimate && !job;

  if (loading) {
    return <p className="text-sm text-gray-400">Loading papers…</p>;
  }

  return (
    <div className="space-y-4">
      <AssayPaperPicker
        papers={papers}
        value={paper}
        onSelect={selectPaper}
        disabled={running}
      />

      {error && <Notice tone="rose">{error}</Notice>}
      {notice && <Notice tone="gray">{notice}</Notice>}
      {lostContact && (
        <Notice tone="amber">
          Lost contact with the backend. The run may still be going — its calls are being paid
          for either way. Still trying.
        </Notice>
      )}

      {showEstimate && (
        <AssayEstimateCard estimate={estimate} onConfirm={confirmRun} busy={starting} />
      )}

      {job && <AssayRunProgress job={job} onCancel={stopRun} cancelling={cancelling} />}

      {job?.state === 'error' && (
        <Notice tone="rose">
          {job.error} — the registry on disk is unchanged by the rounds that did not run.
        </Notice>
      )}

      {isTerminal(job) && estimate && (
        <div>
          <button
            onClick={() => {
              setJob(null);
              writeStoredJob(null);
            }}
            className="text-xs text-emerald-700 hover:text-emerald-900 hover:underline"
          >
            ← Back to the estimate
          </button>
        </div>
      )}

      {result && (
        <>
          <AssayFindingsPanel findings={collectFindings(result)} />
          <AssayBenchmarkView
            benchmark={benchmark}
            registry={result.assays}
            obi={result.obi}
            notCanonical={notCanonical}
            meta={
              job?.result?.meta ?? {
                benchmark_path: registry?.files?.benchmark,
                registry_path: registry?.files?.assays,
                obi_path: registry?.files?.obi,
              }
            }
          />
        </>
      )}

      {paper && !result && !job && (
        <Notice tone="gray">
          This paper has no stored registry yet — the estimate above is what a first run would
          cost.
        </Notice>
      )}
    </div>
  );
}
