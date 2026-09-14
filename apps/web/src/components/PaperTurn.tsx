'use client';

import AssayBenchmarkView from './AssayBenchmarkView';
import AssayRunSummary from './AssayRunSummary';
import AssayEstimateCard from './AssayEstimateCard';
import AssayFindingsPanel from './AssayFindingsPanel';
import AssayRunProgress from './AssayRunProgress';
import PaperCandidates from './PaperCandidates';
import { collectFindings } from '@/lib/findings';
import { useJobPoll } from '@/lib/useJobPoll';
import type { PaperTurn as Turn, RetryStep } from '@/lib/turns';
import type { AssayJob, PaperCandidate } from '@/lib/types';

interface Props {
  turn: Turn;
  onChoose: (paper: PaperCandidate) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onRetry: (step: RetryStep) => void;
  onJob: (job: AssayJob) => void;
  onJobGone: () => void;
  onLostContact: (lost: boolean) => void;
  busy?: boolean;
  cancelling?: boolean;
}

function Step({ tone = 'gray', children }: { tone?: 'gray' | 'emerald'; children: React.ReactNode }) {
  return (
    <p className={`text-xs ${tone === 'emerald' ? 'text-emerald-700' : 'text-gray-500'}`}>
      {children}
    </p>
  );
}

function paperLabel(paper: PaperCandidate): string {
  return `${paper.study_accession} · ${paper.pubmed_id}`;
}

/**
 * One submitted identifier and everything that happened to it.
 *
 * The phase decides what renders; every result view is a component already shipped for the
 * Extract tab, so a run reached from here and one reached from there show the same thing. The
 * job poll lives in this component rather than the feed so each turn owns one timer, cleaned up
 * by its own unmount — which is what makes several runs at once need no coordination.
 */
export default function PaperTurn({
  turn, onChoose, onConfirm, onCancel, onRetry, onJob, onJobGone, onLostContact,
  busy, cancelling,
}: Props) {
  const phase = turn.phase;

  useJobPoll(phase.kind === 'running' ? phase.jobId : null, {
    onJob,
    onGone: onJobGone,
    onLostContact,
  });

  return (
    <article className="space-y-2">
      {/* What was typed, echoed back — the "user bubble". */}
      <div className="flex justify-end">
        <span className="px-3 py-1.5 rounded-2xl bg-gray-100 text-sm text-gray-800 font-mono">
          {turn.query}
        </span>
      </div>

      <div className="space-y-2">
        {phase.kind === 'resolving' && <Step>Looking up {turn.query}…</Step>}

        {phase.kind === 'choosing' && (
          <PaperCandidates
            resolution={phase.resolution}
            onChoose={onChoose}
            disabled={busy}
          />
        )}

        {phase.kind === 'fetching' && (
          <>
            <Step tone="emerald">
              {paperLabel(phase.paper)} — {phase.paper.title ?? phase.paper.paper_title ?? ''}
            </Step>
            <Step>Fetching the paper’s full text from PubMed Central… (free)</Step>
          </>
        )}

        {phase.kind === 'estimating' && (
          <>
            <Step tone="emerald">
              {paperLabel(phase.paper)} — {phase.paper.title ?? phase.paper.paper_title ?? ''}
            </Step>
            <Step>Working out what a run would cost. This is free.</Step>
          </>
        )}

        {phase.kind === 'awaiting_confirm' && (
          <>
            <Step tone="emerald">
              {paperLabel(phase.paper)} — {phase.paper.title ?? phase.paper.paper_title ?? ''}
            </Step>
            <AssayEstimateCard estimate={phase.estimate} onConfirm={onConfirm} busy={busy} />
            {phase.registry && (
              <>
                <Step>A previous run of this paper is already on disk:</Step>
                <AssayRunSummary
                  result={phase.registry}
                  pubmedId={phase.paper.pubmed_id}
                  studyAccession={phase.paper.study_accession}
                />
                <AssayFindingsPanel findings={collectFindings(phase.registry)} />
                <AssayBenchmarkView
                  benchmark={phase.registry.benchmark}
                  registry={phase.registry.assays}
                  obi={phase.registry.obi}
                  meta={{
                    benchmark_path: phase.registry.files?.benchmark,
                    registry_path: phase.registry.files?.assays,
                    obi_path: phase.registry.files?.obi,
                  }}
                />
              </>
            )}
          </>
        )}

        {phase.kind === 'running' && (
          <>
            {phase.adopted && (
              <Step>A run was already under way for this paper, so this is that one.</Step>
            )}
            {phase.job ? (
              <AssayRunProgress job={phase.job} onCancel={onCancel} cancelling={cancelling} />
            ) : (
              <Step>Starting…</Step>
            )}
            {turn.lostContact && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5">
                <p className="text-xs text-amber-800">
                  Lost contact with the backend. The run may still be going — its calls are being
                  paid for either way. Still trying.
                </p>
              </div>
            )}
          </>
        )}

        {phase.kind === 'done' && (
          <>
            {phase.job?.state === 'cancelled' && (
              <Step>
                Stopped. {phase.job.progress.calls} call
                {phase.job.progress.calls === 1 ? '' : 's'} were already sent and are already
                billed; what the run wrote is below.
              </Step>
            )}
            {phase.result ? (
              <>
                <AssayRunSummary
                  result={phase.result}
                  pubmedId={phase.paper.pubmed_id}
                  studyAccession={phase.paper.study_accession}
                />
                <AssayFindingsPanel findings={collectFindings(phase.result)} />
                <AssayBenchmarkView
                  benchmark={phase.result.benchmark ?? phase.result.assays}
                  registry={phase.result.assays}
                  obi={phase.result.obi}
                  notCanonical={
                    (phase.result.rounds?.obi as { source?: string } | undefined)?.source ===
                    'failed'
                  }
                  meta={phase.result.meta}
                />
              </>
            ) : (
              <Step>This run produced no registry.</Step>
            )}
          </>
        )}

        {phase.kind === 'error' && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
            <p className="text-sm text-rose-700">{phase.message}</p>
            {phase.retry && (
              <button
                onClick={() => onRetry(phase.retry as RetryStep)}
                className="mt-2 text-xs text-rose-800 hover:underline"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {turn.notice && phase.kind !== 'running' && (
          <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-2.5">
            <p className="text-xs text-gray-600">{turn.notice}</p>
          </div>
        )}
      </div>
    </article>
  );
}
