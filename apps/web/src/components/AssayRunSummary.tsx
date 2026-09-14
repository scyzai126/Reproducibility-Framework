'use client';

import { useEffect, useMemo, useState } from 'react';
import AssayObiTable from './AssayObiTable';
import { checkAssayImmport } from '@/lib/api';
import { toCorpusRows } from '@/lib/assayRows';
import type { AssayImmportResponse, AssayRegistryResponse, AssayRunResult } from '@/lib/types';

interface Props {
  result: AssayRunResult | AssayRegistryResponse | null;
  pubmedId: string;
  studyAccession: string;
}

/**
 * One paper's assays at a glance, above its evidence.
 *
 * The same table the Corpus tab uses, scoped to this paper — normalized name, OBI term, how it
 * resolved, and whether ImmPort registers it. The detail lives below in the benchmark view; this
 * answers "what did this paper use, and how did each one land?" without scrolling through nine
 * evidence cards to find out.
 *
 * Free. The rows are a mapping of the result already in hand, and the ImmPort column is the same
 * SQL-only pass the corpus column runs.
 */
export default function AssayRunSummary({ result, pubmedId, studyAccession }: Props) {
  const rows = useMemo(
    () => toCorpusRows(result, pubmedId, studyAccession),
    [result, pubmedId, studyAccession]
  );
  const [immport, setImmport] = useState<AssayImmportResponse | null>(null);

  useEffect(() => {
    if (rows.length === 0) {
      setImmport(null);
      return;
    }
    let cancelled = false;
    checkAssayImmport(rows)
      .then((r) => !cancelled && setImmport(r))
      // Losing the column costs the summary one column, not the summary.
      .catch(() => !cancelled && setImmport(null));
    return () => {
      cancelled = true;
    };
  }, [rows]);

  // A run that found nothing already says so in the benchmark view; an empty table would only
  // repeat it.
  if (rows.length === 0) return null;

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-medium text-gray-700">
          {rows.length} assay{rows.length === 1 ? '' : 's'} · {studyAccession}
        </h3>
        {immport && !immport.degraded && (
          <span className="text-xs text-gray-400">
            ImmPort registers {immport.stats.matched} of {rows.length}
          </span>
        )}
      </div>
      {immport?.degraded && (
        <p className="text-xs text-amber-700">{immport.warning}</p>
      )}
      <AssayObiTable rows={rows} immport={immport?.rows ?? []} />
    </section>
  );
}
