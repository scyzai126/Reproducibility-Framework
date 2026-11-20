'use client';

import { useEffect, useMemo, useState } from 'react';
import AssayAccuracyBars from './AssayAccuracyBars';
import { benchmarkCounts } from './AssayBenchmarkResults';
import AssayObiSummary from './AssayObiSummary';
import AssayObiTable from './AssayObiTable';
import { fetchAssayImmport, fetchAssayObi, fetchDataAvailabilityCorpus } from '@/lib/api';
import type { AssayImmportResponse, AssayObiResponse, DataAvailabilityResult } from '@/lib/types';

/**
 * The corpus-wide assay/OBI table, lifted out of the page unchanged.
 *
 * Reads one stored file (data/benchmark_agent_assays/all_assays_OBI.json, one row per assay, built by
 * scripts/build_assay_table.py) across every paper. It is the
 * finished picture; the Extract tab is where one paper's registry is built.
 */
export default function AssayCorpusPanel() {
  const [data, setData] = useState<AssayObiResponse | null>(null);
  const [immport, setImmport] = useState<AssayImmportResponse | null>(null);
  const [immportFailed, setImmportFailed] = useState(false);
  // Where each paper's own data lives, keyed like the rows' `study`. Empty until it loads.
  const [dataAvailability, setDataAvailability] = useState<Record<string, DataAvailabilityResult>>({});
  // The benchmark result picked in the accuracy bars, which filters the table below them.
  const [view, setView] = useState<string | null>(null);
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
      .catch(() => {
        setImmport(null);
        setImmportFailed(true);
      });
  }, []);

  // A third independent fetch, a file read: failing only leaves the Data availability column
  // blank, never the table.
  useEffect(() => {
    fetchDataAvailabilityCorpus()
      .then((res) => setDataAvailability(res.papers))
      .catch(() => setDataAvailability({}));
  }, []);

  // The same counts the result cards below the table filters show, drawn as ratios.
  const counts = useMemo(() => {
    if (!data || !data.rows.some((r) => r.benchmark_items?.length)) return null;
    const key = (study: string, assay: string) => `${study}\u0000${assay}`;
    const coverage = new Map((immport?.rows ?? []).map((r) => [key(r.study, r.assay), r]));
    return benchmarkCounts(data.rows, coverage, (r) => key(r.study, r.assay));
  }, [data, immport]);
  const immportState =
    immportFailed || immport?.degraded ? 'unavailable' : immport === null ? 'loading' : 'ready';

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
          <AssayObiSummary stats={data.stats} dataAvailability={dataAvailability}>
            {counts ? (
              <AssayAccuracyBars
                counts={counts}
                immportState={immportState}
                view={view}
                onView={setView}
              />
            ) : undefined}
          </AssayObiSummary>
          {/* Without benchmark data there is no ImmPort bar, so the sentence carries it. */}
          {!counts && immport && !immport.degraded && (
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
              Matched by SQL first; the rest were asked of the model.
            </p>
          )}
          {immport?.warning && (
            <p className="text-xs text-amber-700">{immport.warning}</p>
          )}
          <AssayObiTable
            rows={data.rows}
            immport={immport?.rows ?? []}
            dataAvailability={dataAvailability}
            view={view}
            onViewChange={setView}
          />
        </div>
      )}
    </>
  );
}
