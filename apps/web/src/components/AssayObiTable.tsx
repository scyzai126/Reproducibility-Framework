'use client';

import { useMemo, useState } from 'react';
import type { AssayImmportRow, AssayObiRow, ImmportStatus, ObiResource } from '@/lib/types';
import { RESOURCE_COLOR, RESOURCE_LABEL } from './AssayObiSummary';

type SortKey = 'study' | 'assay' | 'normalized_name' | 'obi_label' | 'resource' | 'obi_confidence';
type SortDir = 'asc' | 'desc';

const COLUMNS: { key: SortKey | null; label: string; className?: string }[] = [
  { key: 'study', label: 'Study' },
  { key: 'assay', label: 'Assay in paper' },
  { key: 'normalized_name', label: 'Normalized' },
  { key: null, label: 'Sample type' },
  { key: 'obi_label', label: 'OBI term' },
  { key: null, label: 'In ImmPort' },
  { key: 'resource', label: 'Resolved by' },
  { key: 'obi_confidence', label: 'Conf.', className: 'text-right' },
];

/** The column answers one question, so it gives one word. */
const IMMPORT_LABEL: Record<ImmportStatus, string> = {
  matched: 'yes',
  absent: 'no',
  no_experiments: 'no',
  unknown_study: '—',
};

const IMMPORT_TONE: Record<ImmportStatus, string> = {
  matched: 'text-emerald-700',
  absent: 'text-gray-400',
  no_experiments: 'text-gray-400',
  unknown_study: 'text-gray-300',
};

/** The two "no"s are different facts — nothing registered for the study at all, versus this
 *  assay not being among what was registered — so the distinction is kept on hover rather than
 *  dropped, since only the second is something a resolver could still settle. */
const IMMPORT_DETAIL: Record<ImmportStatus, string> = {
  matched: 'ImmPort registers an experiment for this assay',
  absent: 'ImmPort has experiments for this study, but none matching this assay',
  no_experiments: 'ImmPort has no experiments registered for this study at all',
  unknown_study: 'the study identifier could not be read',
};

/** study + assay is unique across the corpus, so it is the join between the two fetches. */
function immportKey(study: string, assay: string): string {
  return `${study}\u0000${assay}`;
}

/** Exact matches ("high") outrank every similarity score; unresolved sorts last. */
function confidenceRank(value: string | number | null): number {
  if (value === 'high') return 2;
  if (typeof value === 'number') return 1;
  return 0;
}

function compare(a: AssayObiRow, b: AssayObiRow, key: SortKey): number {
  if (key === 'obi_confidence') {
    const rank = confidenceRank(a.obi_confidence) - confidenceRank(b.obi_confidence);
    if (rank !== 0) return rank;
    const av = typeof a.obi_confidence === 'number' ? a.obi_confidence : 0;
    const bv = typeof b.obi_confidence === 'number' ? b.obi_confidence : 0;
    return av - bv;
  }
  return String(a[key] ?? '').localeCompare(String(b[key] ?? ''));
}

/** Inline SVG rather than ↕/↑/↓ — those glyphs pick up emoji presentation on macOS. */
function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={active ? 'text-gray-700' : 'text-gray-300'}
    >
      {(!active || dir === 'asc') && <polyline points="7 10 12 5 17 10" />}
      {(!active || dir === 'desc') && <polyline points="7 14 12 19 17 14" />}
    </svg>
  );
}

function ConfidenceCell({ value }: { value: string | number | null }) {
  if (value === null) return <span className="text-gray-300">—</span>;
  if (value === 'high') return <span className="text-gray-500">high</span>;
  return <span className="text-gray-500 tabular-nums">{Number(value).toFixed(2)}</span>;
}

export default function AssayObiTable({
  rows,
  immport = [],
}: {
  rows: AssayObiRow[];
  /** Coverage from a separate, free fetch — empty when ImmPort was unreachable. */
  immport?: AssayImmportRow[];
}) {
  const coverage = useMemo(
    () => new Map(immport.map((r) => [immportKey(r.study, r.assay), r])),
    [immport]
  );

  const [query, setQuery] = useState('');
  const [study, setStudy] = useState('');
  const [resources, setResources] = useState<ObiResource[]>([]);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const studies = useMemo(
    () => Array.from(new Set(rows.map((r) => r.study))).sort(),
    [rows]
  );
  // Scoped to one paper — as the summary above a result is — the study filter selects nothing
  // and the Study column repeats the heading on every row. Derived, so the corpus view, which
  // has 35 studies, is untouched.
  const oneStudy = studies.length <= 1;
  const visibleColumns = useMemo(
    () => (oneStudy ? COLUMNS.filter((c) => c.key !== 'study') : COLUMNS),
    [oneStudy]
  );
  const presentResources = useMemo(
    () => (Object.keys(RESOURCE_LABEL) as ObiResource[]).filter((r) => rows.some((row) => row.resource === r)),
    [rows]
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter((r) => {
      if (study && r.study !== study) return false;
      if (resources.length && !resources.includes(r.resource)) return false;
      if (!q) return true;
      return [r.assay, r.normalized_name, r.obi_label, r.obi_id, r.study]
        .some((field) => field?.toLowerCase().includes(q));
    });
    if (!sortKey) return filtered;
    const sorted = [...filtered].sort((a, b) => compare(a, b, sortKey));
    return sortDir === 'asc' ? sorted : sorted.reverse();
  }, [rows, query, study, resources, sortKey, sortDir]);

  // Three-state cycle: asc → desc → unsorted.
  const toggleSort = (key: SortKey) => {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDir('asc');
    } else if (sortDir === 'asc') {
      setSortDir('desc');
    } else {
      setSortKey(null);
    }
  };

  const hasFilters = Boolean(query.trim() || study || resources.length);

  const clearFilters = () => {
    setQuery('');
    setStudy('');
    setResources([]);
  };

  /** Every active filter, phrased for the empty state so the culprit is never hidden. */
  const activeFilters = [
    study && `paper ${study}`,
    resources.length && `resolved by ${resources.map((r) => RESOURCE_LABEL[r]).join(' or ')}`,
    query.trim() && `matching “${query.trim()}”`,
  ].filter(Boolean) as string[];

  const toggleResource = (resource: ObiResource) => {
    setResources((prev) =>
      prev.includes(resource) ? prev.filter((r) => r !== resource) : [...prev, resource]
    );
  };

  return (
    <div className="space-y-3">
      {/* Filters in one row above the table. */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search assay, OBI term, study…"
          className="flex-1 min-w-[200px] px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-400 focus:border-emerald-400"
        />
        {!oneStudy && (
          <select
            value={study}
            onChange={(e) => setStudy(e.target.value)}
            className="px-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-600 focus:outline-none focus:ring-1 focus:ring-emerald-400"
          >
            <option value="">All {studies.length} papers</option>
            {studies.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}
        {presentResources.map((resource) => {
          const active = resources.includes(resource);
          return (
            <button
              key={resource}
              onClick={() => toggleResource(resource)}
              aria-pressed={active}
              className={`flex items-center gap-1.5 px-2.5 py-2 text-xs rounded-lg border transition-colors ${
                active
                  ? 'border-emerald-500 bg-emerald-50 text-emerald-900 font-medium ring-1 ring-emerald-500'
                  : 'border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}
            >
              <span
                className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                style={{ backgroundColor: RESOURCE_COLOR[resource] }}
              />
              {RESOURCE_LABEL[resource]}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <p className="text-xs text-gray-400">
          {visible.length === rows.length
            ? `${rows.length} rows`
            : `${visible.length} of ${rows.length} rows`}
        </p>
        {/* Filters combine, so an empty result is easy to reach by accident — always offer the way out. */}
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="text-xs text-emerald-700 hover:text-emerald-900 hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      <div className="border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto max-h-[70vh] min-h-[320px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-50 border-b border-gray-200 z-10">
              <tr>
                {visibleColumns.map(({ key, label, className }) => (
                  <th
                    key={label}
                    className={`px-3 py-2.5 text-left font-medium text-gray-500 whitespace-nowrap ${className ?? ''}`}
                  >
                    {key ? (
                      <button
                        onClick={() => toggleSort(key)}
                        className="inline-flex items-center gap-1 hover:text-gray-900 transition-colors"
                      >
                        {label}
                        <SortIcon active={sortKey === key} dir={sortDir} />
                      </button>
                    ) : (
                      label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row, i) => (
                <tr
                  key={`${row.study}-${row.assay}-${i}`}
                  className="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors align-top"
                >
                  {oneStudy || (
                    <td className="px-3 py-2 font-mono text-gray-500 whitespace-nowrap">
                      {row.study}
                    </td>
                  )}
                  <td className="px-3 py-2 text-gray-900 max-w-[220px]">{row.assay}</td>
                  <td className="px-3 py-2 text-gray-600 max-w-[180px]">{row.normalized_name}</td>
                  <td className="px-3 py-2 text-gray-400 max-w-[180px]">{row.sample_type || '—'}</td>
                  <td className="px-3 py-2 max-w-[220px]">
                    {row.obi_id ? (
                      <>
                        <span className="text-gray-900">{row.obi_label}</span>
                        <span className="block font-mono text-gray-400 mt-0.5">{row.obi_id}</span>
                      </>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {(() => {
                      const hit = coverage.get(immportKey(row.study, row.assay));
                      if (!hit) return <span className="text-gray-300">—</span>;
                      return (
                        <span
                          className={IMMPORT_TONE[hit.status]}
                          title={IMMPORT_DETAIL[hit.status]}
                        >
                          {IMMPORT_LABEL[hit.status]}
                          {/* What it matched, in ImmPort's own vocabulary — the point of a
                              "yes" is which technique the study registered. */}
                          {hit.measurement_technique && (
                            <span className="block text-gray-500 mt-0.5">
                              {hit.measurement_technique}
                            </span>
                          )}
                        </span>
                      );
                    })()}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {/* Colour chip plus its text label — this table is the bar's accessible fallback. */}
                    <span className="inline-flex items-center gap-1.5 text-gray-500">
                      <span
                        className="w-2 h-2 rounded-sm flex-shrink-0"
                        style={{ backgroundColor: RESOURCE_COLOR[row.resource] }}
                      />
                      {RESOURCE_LABEL[row.resource]}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <ConfidenceCell value={row.obi_confidence} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {visible.length === 0 && (
            <div className="px-3 py-10 text-center">
              <p className="text-sm text-gray-500">
                No rows are both {activeFilters.join(' and ')}.
              </p>
              <button
                onClick={clearFilters}
                className="mt-2 text-xs text-emerald-700 hover:text-emerald-900 hover:underline"
              >
                Clear filters
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
