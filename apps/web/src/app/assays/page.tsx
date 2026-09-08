'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import AssayObiSummary from '@/components/AssayObiSummary';
import AssayObiTable from '@/components/AssayObiTable';
import { fetchAssayObi } from '@/lib/api';
import type { AssayObiResponse } from '@/lib/types';

export default function AssaysPage() {
  const [data, setData] = useState<AssayObiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAssayObi()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <header className="mb-6">
          <Link
            href="/"
            className="text-xs text-gray-400 hover:text-emerald-700 transition-colors"
          >
            ← Back to analysis
          </Link>
          <h1 className="text-xl font-bold text-gray-900 mt-2">Assay Registry</h1>
          <p className="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
            Every assay extracted from the paper corpus, mapped to its Ontology for Biomedical
            Investigations term.
          </p>
        </header>

        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
            <p className="text-sm text-rose-700">{error}</p>
          </div>
        )}

        {!data && !error && <p className="text-sm text-gray-400">Loading assay registry…</p>}

        {data && (
          <div className="space-y-6">
            <AssayObiSummary stats={data.stats} />
            <AssayObiTable rows={data.rows} />
          </div>
        )}
      </div>
    </div>
  );
}
