'use client';

import { useEffect, useMemo, useState } from 'react';
import AssayObiTable from './AssayObiTable';
import { checkAssayImmport, fetchAssayTable, fetchDataAvailability } from '@/lib/api';
import { toCorpusRows } from '@/lib/assayRows';
import type {
  AssayImmportResponse,
  AssayObiRow,
  AssayRegistryResponse,
  AssayRunResult,
  DataAvailabilityResult,
} from '@/lib/types';

interface Props {
  result: AssayRunResult | AssayRegistryResponse | null;
  pubmedId: string;
  studyAccession: string;
  /** A run's own data-repository answer. Absent, the stored record is read instead (free). */
  dataAvailability?: DataAvailabilityResult | null;
}

/**
 * One paper's assays at a glance, above its evidence — in exactly the Corpus tab's table.
 *
 * The rows come from GET /agent/assays/table, built by the same backend function as the corpus
 * file (benchmark columns, missed curator assays, paper link), and the data-availability record
 * is passed the way the corpus panel passes it, so the two tables show the same columns. Until
 * that free read returns — or if it fails — the rows are mapped from the result in hand, so the
 * summary never goes blank.
 *
 * The ImmPort column is the per-paper pass: SQL, then the cached LLM fallback for what SQL misses.
 */
export default function AssayRunSummary({ result, pubmedId, studyAccession, dataAvailability }: Props) {
  const study = `${pubmedId}_${studyAccession}`;
  const fallback = useMemo(
    () => toCorpusRows(result, pubmedId, studyAccession),
    [result, pubmedId, studyAccession]
  );
  const [served, setServed] = useState<AssayObiRow[] | null>(null);
  // The ImmPort check waits for the served rows: checking the placeholder rows first would ask
  // about the same assays twice, and a row SQL misses costs a model call each time it is asked.
  const [settled, setSettled] = useState(false);
  const [storedData, setStoredData] = useState<DataAvailabilityResult | null>(null);
  const [immport, setImmport] = useState<AssayImmportResponse | null>(null);

  // Re-read whenever the result changes: after a run, the registry on disk is the final one.
  useEffect(() => {
    let cancelled = false;
    setServed(null);
    setSettled(false);
    fetchAssayTable({ pubmed_id: pubmedId, study_accession: studyAccession })
      .then((rows) => !cancelled && setServed(rows.length ? rows : null))
      .catch(() => !cancelled && setServed(null))
      .finally(() => !cancelled && setSettled(true));
    return () => {
      cancelled = true;
    };
  }, [result, pubmedId, studyAccession]);

  useEffect(() => {
    if (dataAvailability !== undefined) return;
    let cancelled = false;
    fetchDataAvailability({ pubmed_id: pubmedId, study_accession: studyAccession })
      .then((record) => !cancelled && setStoredData(record))
      .catch(() => !cancelled && setStoredData(null));
    return () => {
      cancelled = true;
    };
  }, [dataAvailability, pubmedId, studyAccession]);

  const rows = served ?? fallback;
  // Our assays only: a benchmark-only row is a curator assay with nothing of ours to look up.
  const ours = useMemo(() => rows.filter((r) => !r.benchmark_only), [rows]);

  useEffect(() => {
    if (!settled) return;
    if (ours.length === 0) {
      setImmport(null);
      return;
    }
    let cancelled = false;
    checkAssayImmport(ours)
      .then((r) => !cancelled && setImmport(r))
      // Losing the column costs the summary one column, not the summary.
      .catch(() => !cancelled && setImmport(null));
    return () => {
      cancelled = true;
    };
  }, [ours, settled]);

  const record = dataAvailability !== undefined ? dataAvailability : storedData;
  // The corpus panel's prop, keyed like `row.study`: it switches on the same columns there.
  const dataByStudy = useMemo(
    () => (record ? { [study]: record } : {}),
    [record, study]
  );

  // A run that found nothing already says so in the benchmark view; an empty table would only
  // repeat it.
  if (rows.length === 0) return null;

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-medium text-gray-700">
          {ours.length} assay{ours.length === 1 ? '' : 's'} · {studyAccession}
        </h3>
        {immport && !immport.degraded && (
          <span className="text-xs text-gray-400">
            ImmPort registers {immport.stats.matched} of {ours.length}
          </span>
        )}
      </div>
      {immport?.degraded && (
        <p className="text-xs text-amber-700">{immport.warning}</p>
      )}
      <AssayObiTable
        rows={rows}
        immport={immport?.rows ?? []}
        dataAvailability={dataByStudy}
      />
    </section>
  );
}
