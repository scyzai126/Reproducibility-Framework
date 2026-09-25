'use client';

import { useMemo, useState } from 'react';
import type { AssayPaperSummary, PaperRef } from '@/lib/types';

interface Props {
  papers: AssayPaperSummary[];
  value: PaperRef | null;
  onSelect: (paper: AssayPaperSummary) => void;
  disabled?: boolean;
}

function formatDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Every paper the pipeline can run on.
 *
 * The list is the JATS corpus, not the registry: a paper that has never been extracted is still
 * offered, and one whose XML is missing is not offered at all rather than offered and then
 * failed at — the XML is the only thing assay_report reads to find a paper.
 */
export default function AssayPaperPicker({ papers, value, onSelect, disabled }: Props) {
  const [query, setQuery] = useState('');

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return papers;
    return papers.filter((p) =>
      `${p.study_accession} ${p.pubmed_id} ${p.paper_title ?? ''}`.toLowerCase().includes(needle)
    );
  }, [papers, query]);

  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-medium text-gray-700">Paper</h2>
        <span className="text-xs text-gray-400">
          {visible.length === papers.length
            ? `${papers.length} papers`
            : `${visible.length} of ${papers.length} papers`}
        </span>
      </div>

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter by accession, PubMed ID or title"
        className="w-full px-3 py-2 mb-2 text-sm border border-gray-200 rounded-lg text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-emerald-400"
      />

      <div className="border border-gray-200 rounded-xl overflow-hidden">
        {/* Sized to the window rather than to a fixed height: 280px showed four of 35 papers and
            left most of the page empty, so the list scrolled while the page did not. */}
        <div className="max-h-[70vh] overflow-y-auto divide-y divide-gray-100">
          {visible.length === 0 && (
            <p className="px-4 py-6 text-sm text-gray-400">No paper matches that.</p>
          )}
          {visible.map((paper) => {
            const selected =
              value?.pubmed_id === paper.pubmed_id &&
              value?.study_accession === paper.study_accession;
            return (
              <button
                key={paper.paper_source}
                onClick={() => onSelect(paper)}
                disabled={disabled}
                aria-pressed={selected}
                className={`w-full text-left px-4 py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                  selected ? 'bg-emerald-50 ring-1 ring-inset ring-emerald-500' : 'hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-500 flex-shrink-0">
                    {paper.study_accession} · {paper.pubmed_id}
                  </span>
                  {paper.has_registry ? (
                    <span className="text-xs text-emerald-700 flex-shrink-0">
                      {paper.assays ?? '?'} assays
                      {paper.updated_at ? ` · ${formatDate(paper.updated_at)}` : ''}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-400 flex-shrink-0">no registry yet</span>
                  )}
                </div>
                <p className="text-sm text-gray-700 mt-0.5 line-clamp-2">
                  {paper.paper_title ?? paper.paper_source}
                </p>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
