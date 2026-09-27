'use client';

import { useMemo, useState } from 'react';
import type {
  AssayImmportRow,
  AssayObiRow,
  DataAvailabilityResult,
  DataRepository,
  ImmportStatus,
  ObiResource,
} from '@/lib/types';
import { RESOURCE_COLOR, RESOURCE_LABEL } from './AssayObiSummary';
import { benchmarkViews } from './AssayBenchmarkResults';

/** The table's DOM id, so the accuracy bars above it can scroll it into view on a click. */
export const ASSAY_TABLE_ID = 'assay-obi-table';

type SortKey =
  | 'study' | 'assay' | 'normalized_name' | 'obi_label' | 'benchmark_assay' | 'benchmark_obi_label'
  | 'resource' | 'obi_confidence';
type SortDir = 'asc' | 'desc';

/** The corpus table's paper-level column: which repositories hold the study's own data. */
const DATA_COLUMN = 'Data availability';

const COLUMNS: { key: SortKey | null; label: string; className?: string }[] = [
  { key: 'study', label: 'Study' },
  { key: 'assay', label: 'Assay in paper' },
  { key: 'obi_label', label: 'OBI term' },
  { key: 'benchmark_assay', label: 'Benchmark assay' },
  { key: 'benchmark_obi_label', label: 'Benchmark OBI label' },
  { key: null, label: 'In ImmPort' },
  { key: null, label: DATA_COLUMN },
  { key: 'resource', label: 'Resolved by' },
  { key: 'obi_confidence', label: 'Conf.', className: 'text-right' },
  { key: 'normalized_name', label: 'Normalized' },
  { key: null, label: 'Sample type' },
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

/** ImmPort's search reads `text` client-side. The corpus spells a study `<pmid>_<SDY>`, and the
 *  backend has already split the SDY half onto every coverage row as `study_accession`, so there
 *  is nothing to parse here. */
function immportSearchUrl(studyAccession: string): string {
  return `https://www.immport.org/shared/search?text=${encodeURIComponent(studyAccession.toLowerCase())}`;
}

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

function formatBytes(n: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`;
}

/** Hover text for a repository link: what is behind it, when the locator could tell. */
function repositoryDetail(repo: DataRepository): string {
  const parts = [
    repo.access,
    repo.file_count ? `${repo.file_count} file${repo.file_count === 1 ? '' : 's'}` : null,
    repo.total_size_bytes ? formatBytes(repo.total_size_bytes) : null,
  ].filter(Boolean);
  return `Open ${repo.repository} ${repo.accession}${parts.length ? ` (${parts.join(', ')})` : ''}`;
}

/** Where this paper's own data lives: one link per confirmed repository, then any the
 *  repository could not confirm as plain grey text -- only what passed validation is clickable.
 *  A paper never run shows a dash, one run with nothing found says so. */
function DataAvailabilityCell({ record }: { record: DataAvailabilityResult | undefined }) {
  if (!record) {
    return <span className="text-gray-300" title="Data availability has not been run for this paper">—</span>;
  }
  const repos = record.data_repositories ?? [];
  const unconfirmed = record.unconfirmed ?? [];
  if (!repos.length && !unconfirmed.length) {
    return <span className="text-gray-400" title="No repository holding this study's own data was found">none</span>;
  }
  return (
    <>
      {repos.map((repo) => (
        <a
          key={repo.accession}
          href={repo.landing_page ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-emerald-700 hover:text-emerald-900 hover:underline"
          title={repositoryDetail(repo)}
        >
          {repo.repository} {repo.accession}
          <span className="ml-0.5 text-gray-300" aria-hidden="true">↗</span>
        </a>
      ))}
      {unconfirmed.map((item) => (
        <span
          key={item.accession}
          className="block text-gray-400"
          title={`Not confirmed by ${item.repository}: ${item.status ?? 'not checked'}${item.detail ? ` — ${item.detail}` : ''}`}
        >
          {item.repository} {item.accession} <span className="italic">(unconfirmed)</span>
        </span>
      ))}
    </>
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
  view: controlledView,
  onViewChange,
  dataAvailability,
}: {
  rows: AssayObiRow[];
  /** Coverage from a separate, free fetch — empty when ImmPort was unreachable. */
  immport?: AssayImmportRow[];
  /** The benchmark result to filter to (a `benchmarkViews` id). Controlled by the corpus panel,
   *  whose accuracy-bar legend selects it; uncontrolled elsewhere. */
  view?: string | null;
  onViewChange?: (id: string | null) => void;
  /** Where each paper's own data lives, keyed like `row.study`. Given by the corpus panel and
   *  by the Extract tab's AssayRunSummary, so both show the same columns: it adds Data
   *  availability and drops Resolved by / Conf. A table without it keeps those two. */
  dataAvailability?: Record<string, DataAvailabilityResult>;
}) {
  const isCorpus = dataAvailability !== undefined;
  const coverage = useMemo(
    () => new Map(immport.map((r) => [immportKey(r.study, r.assay), r])),
    [immport]
  );

  const [query, setQuery] = useState('');
  const [study, setStudy] = useState('');
  const [resources, setResources] = useState<ObiResource[]>([]);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [ownView, setOwnView] = useState<string | null>(null);
  const view = controlledView !== undefined ? controlledView : ownView;
  const setView = onViewChange ?? setOwnView;

  const studies = useMemo(
    () => Array.from(new Set(rows.map((r) => r.study))).sort(),
    [rows]
  );
  // Scoped to one paper — as the summary above a result is — the study filter selects nothing
  // and the Study column repeats the heading on every row. Derived, so the corpus view, which
  // has 35 studies, is untouched.
  const oneStudy = studies.length <= 1;
  // The curator columns exist only where rows carry benchmark data — the corpus table, not a
  // single paper's run on the Extract tab.
  const hasBenchmark = useMemo(
    () => rows.some((r) => r.benchmark_assay || r.benchmark_only),
    [rows]
  );
  const visibleColumns = useMemo(
    () => COLUMNS.filter((c) =>
      // One paper's table keeps Study too wherever it mirrors the corpus table: the column
      // carries the paper link. Only the bare, non-corpus table drops it.
      !(oneStudy && !isCorpus && c.key === 'study') &&
      !(!hasBenchmark && (c.key === 'benchmark_assay' || c.key === 'benchmark_obi_label')) &&
      !(isCorpus && (c.key === 'resource' || c.key === 'obi_confidence')) &&
      !(!isCorpus && c.label === DATA_COLUMN)),
    [oneStudy, hasBenchmark, isCorpus]
  );
  // On the corpus table the accuracy-bar legend takes the place of the resolver chips: each
  // legend word is a count, and selecting it filters the table to the rows behind that count.
  const views = useMemo(
    () => (hasBenchmark ? benchmarkViews(rows, coverage, (r) => immportKey(r.study, r.assay)) : []),
    [hasBenchmark, rows, coverage]
  );
  const activeView = views.find((v) => v.id === view) ?? null;
  const presentResources = useMemo(
    () => (Object.keys(RESOURCE_LABEL) as ObiResource[]).filter((r) => rows.some((row) => row.resource === r)),
    [rows]
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter((r) => {
      if (study && r.study !== study) return false;
      if (resources.length && !(r.resource && resources.includes(r.resource))) return false;
      if (activeView && !activeView.matches(r, coverage.get(immportKey(r.study, r.assay)))) return false;
      if (!q) return true;
      const repos = (dataAvailability?.[r.study]?.data_repositories ?? []).map((d) => d.accession);
      return [r.assay, r.normalized_name, r.obi_label, r.obi_id, r.study,
              r.benchmark_assay, r.benchmark_obi_label, r.benchmark_obi_id, ...repos]
        .some((field) => field?.toLowerCase().includes(q));
    });
    if (!sortKey) return filtered;
    const sorted = [...filtered].sort((a, b) => compare(a, b, sortKey));
    return sortDir === 'asc' ? sorted : sorted.reverse();
  }, [rows, query, study, resources, activeView, coverage, sortKey, sortDir, dataAvailability]);

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

  // Data availability is a per-study fact on a per-assay table, so its cell spans each run of
  // adjacent rows from one study: spans[i] is the run's length on its first row, 0 after it.
  // Runs are taken from what is on screen -- sorted by another column, a study's rows split and
  // each piece gets its own cell.
  const spans = useMemo(() => {
    const out = new Array<number>(visible.length).fill(0);
    let start = 0;
    visible.forEach((row, i) => {
      if (i > 0 && row.study !== visible[i - 1].study) start = i;
      out[start] += 1;
    });
    return out;
  }, [visible]);

  const hasFilters = Boolean(query.trim() || study || resources.length || activeView);

  const clearFilters = () => {
    setQuery('');
    setStudy('');
    setResources([]);
    setView(null);
  };

  /** Every active filter, phrased for the empty state so the culprit is never hidden. */
  const activeFilters = [
    study && `paper ${study}`,
    resources.length && `resolved by ${resources.map((r) => RESOURCE_LABEL[r]).join(' or ')}`,
    activeView && `in “${activeView.label}”`,
    query.trim() && `matching “${query.trim()}”`,
  ].filter(Boolean) as string[];

  const toggleResource = (resource: ObiResource) => {
    setResources((prev) =>
      prev.includes(resource) ? prev.filter((r) => r !== resource) : [...prev, resource]
    );
  };

  return (
    <div id={ASSAY_TABLE_ID} className="space-y-3 scroll-mt-4">
      {/* Filters in one row above the table. */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={isCorpus ? "Search assay, OBI term, benchmark, study, repository…" : "Search assay, OBI term, benchmark, study…"}
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
        {!hasBenchmark && presentResources.map((resource) => {
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
        {/* The benchmark result picked in the accuracy bars above, shown next to what it filters. */}
        {activeView && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md bg-emerald-50 text-emerald-900 ring-1 ring-emerald-500">
            {activeView.label}
            <button
              onClick={() => setView(null)}
              aria-label={`Stop filtering to ${activeView.label}`}
              className="text-emerald-700 hover:text-emerald-950"
            >
              ✕
            </button>
          </span>
        )}
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
                  {(oneStudy && !isCorpus) || (
                    <td className="px-3 py-2 font-mono text-gray-500 whitespace-nowrap">
                      {row.paper_url ? (
                        <a
                          href={row.paper_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-gray-900 hover:underline"
                          title={`Open the paper in ${row.paper_source ?? 'a new tab'}`}
                        >
                          {row.study}
                          <span className="ml-0.5 text-gray-300" aria-hidden="true">↗</span>
                        </a>
                      ) : (
                        row.study
                      )}
                    </td>
                  )}
                  <td className="px-3 py-2 text-gray-900 max-w-[220px]">
                    {row.benchmark_only ? (
                      <span
                        className="italic text-gray-400"
                        title="The curator lists this assay; the agent's registry has no entry for it"
                      >
                        not found by the agent
                      </span>
                    ) : (
                      row.assay
                    )}
                  </td>
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
                  {hasBenchmark && (
                    <>
                      <td className="px-3 py-2 text-gray-900 max-w-[220px]">
                        {row.benchmark_assay || <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-3 py-2 max-w-[220px]">
                        {row.benchmark_obi_label || row.benchmark_obi_id ? (
                          <>
                            <span className="text-gray-900">{row.benchmark_obi_label ?? '—'}</span>
                            {row.benchmark_obi_id && (
                              <span className="block font-mono text-gray-400 mt-0.5">
                                {row.benchmark_obi_id}
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                    </>
                  )}
                  <td className="px-3 py-2 whitespace-nowrap">
                    {(() => {
                      if (row.benchmark_only) return null;
                      const hit = coverage.get(immportKey(row.study, row.assay));
                      if (!hit) return <span className="text-gray-300">—</span>;
                      return (
                        <span
                          className={IMMPORT_TONE[hit.status]}
                          title={IMMPORT_DETAIL[hit.status]}
                        >
                          {/* Both answers link to the same place — the study in ImmPort. A "no"
                              is the one worth clicking: it is where you go to see what the study
                              does hold. Tone stays on the span, so yes/no keep their colours and
                              only the underline marks the link. */}
                          {hit.study_accession ? (
                            <a
                              href={immportSearchUrl(hit.study_accession)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                              title={`${IMMPORT_DETAIL[hit.status]} — search ImmPort for ${hit.study_accession}`}
                            >
                              {IMMPORT_LABEL[hit.status]}
                            </a>
                          ) : (
                            IMMPORT_LABEL[hit.status]
                          )}
                          {/* What it matched, in ImmPort's own vocabulary — the point of a
                              "yes" is which technique the study registered. */}
                          {hit.measurement_technique && (
                            <span className="block text-gray-500 mt-0.5">
                              {hit.measurement_technique}
                              {hit.method === 'LLM' && (
                                <span
                                  className="ml-1 text-gray-400"
                                  title="SQL found no match; the model picked this experiment"
                                >
                                  · via LLM
                                </span>
                              )}
                            </span>
                          )}
                        </span>
                      );
                    })()}
                  </td>
                  {isCorpus ? (
                    spans[i] > 0 && (
                      <td
                        rowSpan={spans[i]}
                        className="px-3 py-2 whitespace-nowrap border-l border-gray-100 bg-white"
                      >
                        <DataAvailabilityCell record={dataAvailability[row.study]} />
                      </td>
                    )
                  ) : (
                    <>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {/* Colour chip plus its text label — this table is the bar's accessible fallback. */}
                        {row.resource && (
                          <span className="inline-flex items-center gap-1.5 text-gray-500">
                            <span
                              className="w-2 h-2 rounded-sm flex-shrink-0"
                              style={{ backgroundColor: RESOURCE_COLOR[row.resource] }}
                            />
                            {RESOURCE_LABEL[row.resource]}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        {!row.benchmark_only && <ConfidenceCell value={row.obi_confidence} />}
                      </td>
                    </>
                  )}
                  <td className="px-3 py-2 text-gray-600 max-w-[180px]">{row.normalized_name || '—'}</td>
                  <td className="px-3 py-2 text-gray-400 max-w-[180px]">{row.sample_type || '—'}</td>
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
