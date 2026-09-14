'use client';

import { useEffect, useState } from 'react';
import AssayObiSummary from './AssayObiSummary';
import AssayObiTable from './AssayObiTable';
import { fetchAssayImmport, fetchAssayObi } from '@/lib/api';
import type { AssayImmportResponse, AssayObiResponse } from '@/lib/types';

/**
 * The corpus-wide assay/OBI table, lifted out of the page unchanged.
 *
 * Reads one stored file (data/claims/all_assays_full_OBI.json) across every paper. It is the
 * finished picture; the Extract tab is where one paper's registry is built.
 */
export default function AssayCorpusPanel() {
  const [data, setData] = useState<AssayObiResponse | null>(null);
  const [immport, setImmport] = useState<AssayImmportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAssayObi()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  // A second, independent fetch: the coverage sweep queries ImmPort per row, so it is slower
  // than the file read above and must not hold the table back — nor take it down when the
  // database is unreachable, which the table itself does not need.
  useEffect(() => {
    fetchAssayImmport()
      .then(setImmport)
      .catch(() => setImmport(null));
  }, []);

  return (
    <>
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
          <p className="text-sm text-rose-700">{error}</p>
        </div>
      )}

      {!data && !error && <p className="text-sm text-gray-400">Loading assay registry…</p>}

      {data && (
        <div className="space-y-6">
          <AssayObiSummary stats={data.stats} />
          {immport && !immport.degraded && (
            <p className="text-xs text-gray-500">
              ImmPort registers an experiment for{' '}
              <span className="text-gray-900 font-medium">{immport.stats.matched}</span> of{' '}
              {immport.stats.total} assays.{' '}
              {immport.stats.no_experiments > 0 && (
                <>
                  {immport.stats.no_experiments} are in studies ImmPort has no experiments for at
                  all ({immport.stats.studies_without_experiments.join(', ')}).{' '}
                </>
              )}
              Matched by SQL only — no model call was made.
            </p>
          )}
          {immport?.degraded && (
            <p className="text-xs text-amber-700">{immport.warning}</p>
          )}
          <AssayObiTable rows={data.rows} immport={immport?.rows ?? []} />
        </div>
      )}
    </>
  );
}
