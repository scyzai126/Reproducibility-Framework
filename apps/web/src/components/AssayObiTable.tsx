'use client';

import { useMemo, useState } from 'react';
import type { AssayObiRow, ObiResource } from '@/lib/types';
import { RESOURCE_COLOR, RESOURCE_LABEL } from './AssayObiSummary';

type SortKey = 'study' | 'assay' | 'normalized_name' | 'obi_label' | 'resource' | 'obi_confidence';
type SortDir = 'asc' | 'desc';

const COLUMNS: { key: SortKey | null; label: string; className?: string }[] = [
  { key: 'study', label: 'Study' },
  { key: 'assay', label: 'Assay in paper' },
  { key: 'normalized_name', label: 'Normalized' },
  { key: null, label: 'Sample type' },
  { key: 'obi_label', label: 'OBI term' },
  { key: 'resource', label: 'Resolved by' },
  { key: 'obi_confidence', label: 'Conf.', className: 'text-right' },
];

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

export default function AssayObiTable({ rows }: { rows: AssayObiRow[] }) {
  const [query, setQuery] = useState('');
  const [study, setStudy] = useState('');
  const [resources, setResources] = useState<ObiResource[]>([]);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const studies = useMemo(
    () => Array.from(new Set(rows.map((r) => r.study))).sort(),
    [rows]
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
        <div className="overflow-x-auto max-h-[calc(100vh-380px)] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-50 border-b border-gray-200 z-10">
              <tr>
                {COLUMNS.map(({ key, label, className }) => (
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
                  <td className="px-3 py-2 font-mono text-gray-500 whitespace-nowrap">{row.study}</td>
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
