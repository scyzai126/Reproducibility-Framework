import type {
  AssayEstimate,
  AssayJob,
  AssayRegistryResponse,
  AssayRunResult,
  PaperCandidate,
  ResolveResponse,
} from './types';

/**
 * One submitted identifier, and everything that happened to it.
 *
 * A turn walks: resolving → (choosing, when the identifier is ambiguous) → fetching →
 * estimating → awaiting_confirm | running → done. Each phase carries exactly what its renderer
 * needs and nothing else, so an impossible combination — a job id with no paper, an estimate
 * with no candidate — cannot be represented.
 *
 * Pure: no React, no fetching. The driver in PaperTurnFeed performs the side effects and
 * dispatches the results here.
 */

export type TurnPhaseKind =
  | 'resolving'
  | 'choosing'
  | 'fetching'
  | 'estimating'
  | 'awaiting_confirm'
  | 'running'
  | 'done'
  | 'error';

export type RetryStep = 'resolve' | 'fetch' | 'estimate' | 'run';

export type TurnPhase =
  | { kind: 'resolving' }
  /** More than one paper matched, or none did; either way the user decides what happens next. */
  | { kind: 'choosing'; resolution: ResolveResponse }
  | { kind: 'fetching'; paper: PaperCandidate }
  | { kind: 'estimating'; paper: PaperCandidate }
  | {
      kind: 'awaiting_confirm';
      paper: PaperCandidate;
      estimate: AssayEstimate;
      /** A previous run's result, shown beside the estimate so "do I need to spend this
       *  again?" is answerable. Free to read. */
      registry: AssayRegistryResponse | null;
    }
  | {
      kind: 'running';
      paper: PaperCandidate;
      jobId: string;
      job: AssayJob | null;
      /** Carried through because AssayJob.estimate is null for a job adopted from elsewhere. */
      estimate: AssayEstimate | null;
      adopted: boolean;
    }
  | {
      kind: 'done';
      paper: PaperCandidate;
      job: AssayJob | null;
      result: AssayRunResult | null;
      estimate: AssayEstimate | null;
    }
  | {
      kind: 'error';
      message: string;
      at: TurnPhaseKind;
      retry: RetryStep | null;
      paper?: PaperCandidate;
      /** PMC will not serve this paper: offer a PDF upload instead of a retry. */
      upload?: boolean;
    };

export interface PaperTurn {
  id: string;
  /** Exactly what was typed. */
  query: string;
  submittedAt: string;
  phase: TurnPhase;
  notice: string | null;
  /** Several consecutive poll failures: the run may still be going. */
  lostContact: boolean;
}

export type TurnAction =
  | { type: 'submit'; id: string; query: string; replace?: boolean }
  | { type: 'resolved'; id: string; resolution: ResolveResponse }
  | { type: 'choose'; id: string; paper: PaperCandidate }
  | { type: 'fetched'; id: string; paper: PaperCandidate }
  | {
      type: 'estimated';
      id: string;
      estimate: AssayEstimate;
      registry: AssayRegistryResponse | null;
    }
  | { type: 'started'; id: string; jobId: string; adopted: boolean }
  | { type: 'job'; id: string; job: AssayJob }
  | { type: 'job_gone'; id: string; registry: AssayRegistryResponse | null }
  | { type: 'lost_contact'; id: string; lost: boolean }
  | { type: 'failed'; id: string; message: string; retry: RetryStep | null; upload?: boolean }
  | { type: 'notice'; id: string; text: string | null }
  | { type: 'reset'; id: string }
  | { type: 'hydrate'; turns: PaperTurn[] };

function isTerminalJob(job: AssayJob): boolean {
  return job.state === 'done' || job.state === 'error' || job.state === 'cancelled';
}

/** The paper a turn is about, when it has got far enough to have one. */
export function turnPaper(turn: PaperTurn): PaperCandidate | null {
  const phase = turn.phase;
  return 'paper' in phase && phase.paper ? phase.paper : null;
}

export function isTerminalPhase(phase: TurnPhase): boolean {
  return phase.kind === 'done' || phase.kind === 'error';
}

function replace(turns: PaperTurn[], id: string, update: (turn: PaperTurn) => PaperTurn) {
  return turns.map((turn) => (turn.id === id ? update(turn) : turn));
}

export function turnsReducer(turns: PaperTurn[], action: TurnAction): PaperTurn[] {
  switch (action.type) {
    case 'hydrate':
      return action.turns;

    case 'submit': {
      // A new question replaces the last answer, but never a run still in flight: that turn is
      // the only way back to the job's Stop button, and the job keeps spending server-side
      // whether or not it is on screen. `replace` is opt-in because hydration also dispatches
      // this action, rebuilding stored turns one at a time.
      const kept = action.replace ? turns.filter((t) => !isTerminalPhase(t.phase)) : turns;
      return [
        ...kept,
        {
          id: action.id,
          query: action.query,
          submittedAt: new Date().toISOString(),
          phase: { kind: 'resolving' },
          notice: null,
          lostContact: false,
        },
      ];
    }

    case 'resolved':
      // Zero or many both land in `choosing`: with none there is a reason to read, with many a
      // choice to make. Exactly one is resolved by the driver, which calls `choose` itself.
      return replace(turns, action.id, (turn) => ({
        ...turn,
        phase: { kind: 'choosing', resolution: action.resolution },
      }));

    case 'choose':
      return replace(turns, action.id, (turn) => ({
        ...turn,
        phase: { kind: 'fetching', paper: action.paper },
      }));

    case 'fetched':
      return replace(turns, action.id, (turn) => ({
        ...turn,
        phase: { kind: 'estimating', paper: action.paper },
      }));

    case 'estimated':
      return replace(turns, action.id, (turn) => {
        const paper = turnPaper(turn);
        if (!paper) return turn;
        return {
          ...turn,
          phase: {
            kind: 'awaiting_confirm',
            paper,
            estimate: action.estimate,
            registry: action.registry,
          },
        };
      });

    case 'started':
      // The one invariant that matters for money: a run may only start from the phase that
      // showed the cost. React double-invokes effects in development, so the paid POST is
      // driven from a click and guarded here rather than fired on entering a phase.
      return replace(turns, action.id, (turn) => {
        if (turn.phase.kind !== 'awaiting_confirm' && turn.phase.kind !== 'choosing') return turn;
        const paper = turnPaper(turn);
        const estimate =
          turn.phase.kind === 'awaiting_confirm' ? turn.phase.estimate : null;
        if (!paper) return turn;
        return {
          ...turn,
          phase: {
            kind: 'running',
            paper,
            jobId: action.jobId,
            job: null,
            estimate,
            adopted: action.adopted,
          },
        };
      });

    case 'job':
      return replace(turns, action.id, (turn) => {
        if (turn.phase.kind !== 'running') return turn;
        if (!isTerminalJob(action.job)) {
          return { ...turn, lostContact: false, phase: { ...turn.phase, job: action.job } };
        }
        return {
          ...turn,
          lostContact: false,
          phase: {
            kind: 'done',
            paper: turn.phase.paper,
            job: action.job,
            result: action.job.result,
            estimate: turn.phase.estimate,
          },
        };
      });

    case 'job_gone':
      // The backend restarted. Not a lost result: the files the run wrote are on disk, and the
      // registry read that replaces it is free.
      return replace(turns, action.id, (turn) => {
        const paper = turnPaper(turn);
        if (!paper) return turn;
        return {
          ...turn,
          lostContact: false,
          notice:
            'That run’s progress was lost when the backend restarted — anything it wrote is ' +
            'still on disk, and is shown below.',
          phase: {
            kind: 'done',
            paper,
            job: null,
            result: action.registry,
            estimate: turn.phase.kind === 'running' ? turn.phase.estimate : null,
          },
        };
      });

    case 'lost_contact':
      return replace(turns, action.id, (turn) => ({ ...turn, lostContact: action.lost }));

    case 'failed':
      return replace(turns, action.id, (turn) => ({
        ...turn,
        phase: {
          kind: 'error',
          message: action.message,
          at: turn.phase.kind,
          retry: action.retry,
          paper: turnPaper(turn) ?? undefined,
          upload: action.upload,
        },
      }));

    case 'notice':
      return replace(turns, action.id, (turn) => ({ ...turn, notice: action.text }));

    case 'reset':
      return turns.filter((turn) => turn.id !== action.id);

    default:
      return turns;
  }
}

// ── persistence ─────────────────────────────────────────────────────────────
// Results are ~70KB each and localStorage is ~5MB, so a turn stores only what it takes to
// redraw its header; everything else is re-fetched, and every one of those reads is free.

const STORAGE_KEY = 'paper_turns';
const MAX_TURNS = 20;
const STORAGE_VERSION = 1;

export interface StoredTurn {
  id: string;
  query: string;
  submittedAt: string;
  kind: TurnPhaseKind;
  pubmed_id: string;
  study_accession: string;
  title: string | null;
  jobId: string | null;
  notice: string | null;
}

export function toStored(turn: PaperTurn): StoredTurn {
  const paper = turnPaper(turn);
  return {
    id: turn.id,
    query: turn.query,
    submittedAt: turn.submittedAt,
    kind: turn.phase.kind,
    pubmed_id: paper?.pubmed_id ?? '',
    study_accession: paper?.study_accession ?? '',
    title: paper?.title ?? paper?.paper_title ?? null,
    jobId: turn.phase.kind === 'running' ? turn.phase.jobId : null,
    notice: turn.notice,
  };
}

export function readStoredTurns(): StoredTurn[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { version?: number; turns?: StoredTurn[] };
    // A shape change drops the history rather than crashing the page on it.
    if (parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.turns)) return [];
    return parsed.turns;
  } catch {
    return [];
  }
}

export function writeStoredTurns(turns: PaperTurn[]): void {
  // Only a run still in flight is worth coming back to. Everything else is history, and storing
  // a turn that will never be restored is dead weight that also leaves stale rows behind.
  const stored = turns
    .filter((turn) => turn.phase.kind === 'running')
    .slice(-MAX_TURNS)
    .map(toStored);
  const write = (rows: StoredTurn[]) =>
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, turns: rows }));
  try {
    write(stored);
  } catch {
    // A full quota costs the oldest turn, not the whole history.
    try {
      write(stored.slice(1));
    } catch {
      // A browser that refuses storage costs us the resume, not the run.
    }
  }
}
