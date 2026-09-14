'use client';

import { useEffect, useRef } from 'react';
import { JobGoneError, fetchAssayJob } from './api';
import type { AssayJob } from './types';

const POLL_MS = 1_500;
const POLL_BACKOFF_MS = 3_000;
/** After this many consecutive transport failures, say so rather than polling on in silence. */
const LOST_CONTACT_AFTER = 5;

interface Handlers {
  onJob: (job: AssayJob) => void;
  /** The backend restarted and no longer remembers this run. */
  onGone: () => void;
  onLostContact: (lost: boolean) => void;
}

/**
 * Follow one job to a terminal state.
 *
 * A `setTimeout` re-armed after each response rather than a `setInterval`, so a slow reply
 * cannot stack requests on a single-process dev server. One hook instance per turn means one
 * timer per turn, cleaned up by that turn's own unmount — which is what makes several runs at
 * once cost nothing to coordinate.
 *
 * Transport failures widen the interval and are reported after a few in a row; the poll is
 * never abandoned, because the run is spending money whether or not anything is watching.
 *
 * Pass `jobId: null` when the turn is not running; the hook then does nothing.
 */
export function useJobPoll(jobId: string | null, handlers: Handlers): void {
  // Held in a ref so a re-rendered parent does not restart the timer mid-run.
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;

    const step = async () => {
      if (cancelled) return;
      try {
        const job = await fetchAssayJob(jobId);
        if (cancelled) return;
        failures = 0;
        latest.current.onLostContact(false);
        latest.current.onJob(job);
        if (job.state === 'done' || job.state === 'error' || job.state === 'cancelled') return;
        timer = setTimeout(step, POLL_MS);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof JobGoneError) {
          latest.current.onGone();
          return;
        }
        failures += 1;
        if (failures >= LOST_CONTACT_AFTER) latest.current.onLostContact(true);
        timer = setTimeout(step, POLL_BACKOFF_MS);
      }
    };

    void step();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);
}
