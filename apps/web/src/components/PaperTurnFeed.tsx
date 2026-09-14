'use client';

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import PaperTurn from './PaperTurn';
import {
  ActiveRunError,
  addAssayPaper,
  cancelAssayRun,
  estimateAssayRun,
  fetchAssayRegistry,
  resolvePaper,
  startAssayRun,
} from '@/lib/api';
import {
  type PaperTurn as Turn,
  type RetryStep,
  readStoredTurns,
  turnPaper,
  turnsReducer,
  writeStoredTurns,
} from '@/lib/turns';
import type { AssayJob, PaperCandidate } from '@/lib/types';

/**
 * Whether a run whose cost cannot be sized starts without a confirmation.
 *
 * `estimate_run` reports an unknown total exactly when no stored registry exists to size rounds
 * 2 and 3 from — which is every first run of every new paper, the case this page exists for. So
 * with this on, most submissions here begin spending on one click. It is one constant on purpose:
 * flipping it to false makes every run wait at the estimate card, which shows "?" per round and
 * a button that sends `acknowledged_unknown`.
 */
const AUTO_START_WHEN_UNKNOWN = true;

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Type one identifier, get its assay registry.
 *
 * The feed owns the turns and performs every side effect; `lib/turns.ts` owns the transitions
 * and is pure. Each turn walks resolve → (choose) → fetch → estimate → run on its own, so two
 * papers can be in flight at once — the backend refuses a second run of the *same* paper with a
 * 409, which is adopted rather than retried.
 */
export default function PaperTurnFeed() {
  const [turns, dispatch] = useReducer(turnsReducer, []);
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  const hydrated = useRef(false);

  // Only what redraws a header is stored; results and estimates are re-fetched, and every one of
  // those reads is free. See lib/turns.ts.
  useEffect(() => {
    if (!hydrated.current) return;
    writeStoredTurns(turns);
  }, [turns]);

  /** Re-attach to whatever was going when the page was last open. */
  useEffect(() => {
    const stored = readStoredTurns();
    hydrated.current = true;
    if (stored.length === 0) return;

    // Only a run still in flight: everything else is history, and the job behind a running turn
    // is spending whether or not this tab is open. Filtered on read as well as on write, so rows
    // stored before the feed stopped keeping history do not come back for one load.
    const restore = stored.filter((row) => row.kind === 'running');
    if (restore.length === 0) return;

    (async () => {
      for (const row of restore) {
        if (!row.pubmed_id || !row.study_accession) continue;
        const id = row.id;
        dispatch({ type: 'submit', id, query: row.query });
        try {
          // Re-resolved rather than restored: it refreshes `active_job_id`, so a run started in
          // another tab is adopted instead of started again.
          const resolution = await resolvePaper(row.query);
          dispatch({ type: 'resolved', id, resolution });
          const paper = resolution.candidates.find(
            (c) => c.pubmed_id === row.pubmed_id && c.study_accession === row.study_accession
          );
          if (!paper) continue;
          if (row.kind === 'running' && row.jobId) {
            dispatch({ type: 'choose', id, paper });
            dispatch({ type: 'fetched', id, paper });
            dispatch({
              type: 'estimated', id,
              estimate: await estimateAssayRun(paper),
              registry: null,
            });
            dispatch({ type: 'started', id, jobId: row.jobId, adopted: true });
          } else if (row.kind === 'done') {
            dispatch({ type: 'choose', id, paper });
            dispatch({ type: 'fetched', id, paper });
            dispatch({
              type: 'estimated', id,
              estimate: await estimateAssayRun(paper),
              registry: await fetchAssayRegistry(paper),
            });
          } else {
            await prepare(id, paper, { autoStart: false });
          }
        } catch {
          // A turn that cannot be rebuilt is dropped rather than shown half-restored.
          dispatch({ type: 'reset', id });
        }
      }
    })();
    // Runs once; `prepare` is stable enough for a one-shot hydration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Any turn already running this exact paper — the second double-spend guard. */
  const runningJobFor = useCallback(
    (paper: PaperCandidate): string | null => {
      for (const turn of turns) {
        if (turn.phase.kind !== 'running') continue;
        const other = turnPaper(turn);
        if (
          other?.pubmed_id === paper.pubmed_id &&
          other?.study_accession === paper.study_accession
        ) {
          return turn.phase.jobId;
        }
      }
      return null;
    },
    [turns]
  );

  /** Fetch the XML if needed, then price the run. Both free. */
  const prepare = useCallback(
    async (id: string, paper: PaperCandidate, opts: { autoStart: boolean }) => {
      const adopted = paper.active_job_id ?? runningJobFor(paper);
      if (adopted) {
        dispatch({ type: 'choose', id, paper });
        dispatch({ type: 'fetched', id, paper });
        dispatch({ type: 'started', id, jobId: adopted, adopted: true });
        return;
      }

      dispatch({ type: 'choose', id, paper });
      if (!paper.has_xml) {
        try {
          await addAssayPaper(paper);
        } catch (err) {
          // The backend's own wording: abstract-only, paywalled and unreachable are three
          // different problems, and only the last is worth retrying.
          const text = message(err);
          dispatch({
            type: 'failed', id, message: text,
            retry: text.includes('could not reach NCBI') ? 'fetch' : null,
          });
          return;
        }
      }

      dispatch({ type: 'fetched', id, paper });
      try {
        const [estimate, registry] = await Promise.all([
          estimateAssayRun(paper),
          fetchAssayRegistry(paper),
        ]);
        dispatch({ type: 'estimated', id, estimate, registry });
        if (opts.autoStart && AUTO_START_WHEN_UNKNOWN && !estimate.total_calls_known) {
          await run(id, paper, null);
        }
      } catch (err) {
        dispatch({ type: 'failed', id, message: message(err), retry: 'estimate' });
      }
    },
    [runningJobFor]
  );

  /** The only thing on this page that spends. */
  const run = useCallback(
    async (id: string, paper: PaperCandidate, acknowledged: number | null) => {
      setBusy(id);
      try {
        const job = await startAssayRun(paper, acknowledged);
        dispatch({ type: 'started', id, jobId: job.id, adopted: false });
      } catch (err) {
        if (err instanceof ActiveRunError && err.jobId) {
          dispatch({ type: 'started', id, jobId: err.jobId, adopted: true });
        } else {
          dispatch({ type: 'failed', id, message: message(err), retry: 'run' });
        }
      } finally {
        setBusy(null);
      }
    },
    []
  );

  const submit = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text) return;
      setInputError(null);
      setQuery('');
      const id = crypto.randomUUID();
      dispatch({ type: 'submit', id, query: text, replace: true });

      let resolution;
      try {
        resolution = await resolvePaper(text);
      } catch (err) {
        // A string that is not an identifier is a typo, not a turn worth keeping.
        dispatch({ type: 'reset', id });
        setInputError(message(err));
        setQuery(text);
        return;
      }
      dispatch({ type: 'resolved', id, resolution });
      if (resolution.candidates.length === 1) {
        await prepare(id, resolution.candidates[0], { autoStart: true });
      }
    },
    [prepare]
  );

  const retry = useCallback(
    async (turn: Turn, step: RetryStep) => {
      const paper = turn.phase.kind === 'error' ? turn.phase.paper : null;
      if (step === 'resolve' || !paper) {
        await submit(turn.query);
        dispatch({ type: 'reset', id: turn.id });
        return;
      }
      // Never re-issues a paid run on its own: a retry returns to the gate.
      await prepare(turn.id, paper, { autoStart: false });
    },
    [prepare, submit]
  );

  const stop = useCallback(async (turn: Turn) => {
    if (turn.phase.kind !== 'running') return;
    setCancelling(turn.id);
    try {
      dispatch({ type: 'job', id: turn.id, job: await cancelAssayRun(turn.phase.jobId) });
    } catch (err) {
      dispatch({ type: 'notice', id: turn.id, text: message(err) });
    } finally {
      setCancelling(null);
    }
  }, []);

  const inFlight = turns.filter((t) => t.phase.kind === 'running').length;

  return (
    // Auto-height, no scroll container of its own: this sits above the corpus picker on the
    // Extract tab, and a fixed-height box here would hide everything below it behind an inner
    // scrollbar. The page scrolls as one.
    <div className="space-y-4">
      <div className="border border-gray-200 rounded-xl px-4 py-3">
        {inFlight > 0 && (
          <p className="text-xs text-gray-500 mb-2">
            {inFlight} run{inFlight === 1 ? '' : 's'} in progress — each one is spending model
            calls.
          </p>
        )}
        {inputError && <p className="text-xs text-rose-700 mb-2">{inputError}</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit(query);
          }}
          className="flex gap-2"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="PubMed ID, study accession, or PMC id…"
            className="flex-1 px-4 py-2.5 text-sm border border-gray-200 rounded-xl text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-emerald-400"
          />
          <button
            type="submit"
            disabled={!query.trim()}
            className="px-4 py-2.5 text-sm font-medium rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Extract
          </button>
        </form>
        {turns.length === 0 && (
          <p className="text-xs text-gray-400 mt-2">
            The paper’s full text is fetched from PubMed Central if it isn’t already here, then
            the assay registry is built from it.{' '}
            <span className="font-mono">34252919 · SDY2189 · PMC8761119</span>
          </p>
        )}
      </div>

      <div className="space-y-6">
        {/* Newest first, so a new turn appears directly under the box you just typed into and
            nothing has to scroll. Display order only — the reducer and localStorage stay
            chronological, because persistence trims with slice(-MAX_TURNS) and reversing the
            stored array would discard the newest turns instead of the oldest. */}
        {[...turns].reverse().map((turn) => (
          <PaperTurn
            key={turn.id}
            turn={turn}
            busy={busy === turn.id}
            cancelling={cancelling === turn.id}
            onChoose={(paper) => void prepare(turn.id, paper, { autoStart: true })}
            onConfirm={() => {
              // The phase is re-read here rather than captured, so a stale closure cannot start
              // a run from anywhere but the card that showed the price.
              if (turn.phase.kind !== 'awaiting_confirm') return;
              void run(turn.id, turn.phase.paper, turn.phase.estimate.total_calls);
            }}
            onCancel={() => void stop(turn)}
            onRetry={(step) => void retry(turn, step)}
            onJob={(job: AssayJob) => dispatch({ type: 'job', id: turn.id, job })}
            onJobGone={() => {
              const paper = turnPaper(turn);
              if (!paper) return;
              void fetchAssayRegistry(paper).then((registry) =>
                dispatch({ type: 'job_gone', id: turn.id, registry })
              );
            }}
            onLostContact={(lost) => dispatch({ type: 'lost_contact', id: turn.id, lost })}
          />
        ))}
      </div>
    </div>
  );
}
