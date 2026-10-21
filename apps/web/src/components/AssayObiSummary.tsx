'use client';

import { useMemo, type ReactNode } from 'react';
import type { AssayObiStats, DataAvailabilityResult, ObiResource } from '@/lib/types';

/**
 * Colours for the mapping-method bar. Validated against the app's white surface
 * (lightness band, chroma floor, CVD separation, normal-vision floor, contrast — all pass;
 * worst adjacent CVD ΔE 18.9). Do not substitute by eye.
 *
 * The two exact tiers share a hue family because they are the same kind of result;
 * orange marks a different kind (inference); grey is the null slot, never a series colour.
 */
export const RESOURCE_COLOR: Record<ObiResource, string> = {
  exact_original: '#184f95',
  exact_normalized: '#3987e5',
  // Same swatch as the tier it succeeds, deliberately. The four values above were picked
  // together and CVD-checked as a set, and the note above says not to extend them by eye --
  // so the two new tiers reuse their family's colour rather than adding unvalidated hues.
  // They read as "an exact normalized match" and "an embedding match" respectively, which is
  // what the chart encodes; the RESOURCE_LABEL text is what tells the two apart. If they ever
  // need to be distinguished at a glance, re-run the palette analysis rather than nudging a
  // hex here.
  exact_normalized_llm: '#3987e5',
  // Same reasoning: an exact original-name hit the picker refined, so the original tier's swatch.
  exact_original_llm: '#184f95',
  embedding_llm: '#eb6834',
  embedding_llm_normalized: '#eb6834',
  embedding_llm_neighbour: '#eb6834',
  // The tree descent is the other LLM-decided tier, so the LLM swatch, for the reason above.
  descend_llm: '#eb6834',
  embedding_llm_descended: '#eb6834',
  unresolved: '#898781',
};

export const RESOURCE_LABEL: Record<ObiResource, string> = {
  exact_original: 'Exact — original name',
  exact_normalized: 'Exact — standard technique name (retired)',
  exact_normalized_llm: 'Exact — standard technique name',
  exact_original_llm: 'Exact — refined by picker',
  embedding_llm: 'Embedding + LLM',
  embedding_llm_normalized: 'Embedding + LLM (via standard technique name)',
  embedding_llm_neighbour: 'Embedding + LLM (via an OBI neighbour)',
  descend_llm: 'OBI tree descent + LLM',
  embedding_llm_descended: 'Embedding + LLM, refined by descent',
  unresolved: 'Unresolved',
};

function StatTile({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 px-5 py-4">
      {/* A hero number is not a chart — no colour encoding here. */}
      <div className="text-2xl font-semibold text-gray-900 tabular-nums">{value}</div>
      <div className="text-xs text-gray-400 mt-0.5">{label}</div>
      {hint && <div className="text-[11px] text-gray-400 mt-1.5 leading-snug">{hint}</div>}
    </div>
  );
}

/** Which repositories hold the corpus's own data, from the confirmed `data_repositories` only:
 *  each repository with the number of studies using it (most-used first), distinct datasets
 *  (two papers of one study can share a series), and the studies with any confirmed data. */
function summarizeRepositories(records: Record<string, DataAvailabilityResult>) {
  const studiesByRepo = new Map<string, Set<string>>();
  const datasets = new Set<string>();
  let studiesWithData = 0;
  for (const [study, record] of Object.entries(records)) {
    const repos = record.data_repositories ?? [];
    if (repos.length) studiesWithData += 1;
    for (const repo of repos) {
      datasets.add(`${repo.repository}\u0000${repo.accession}`);
      if (!studiesByRepo.has(repo.repository)) studiesByRepo.set(repo.repository, new Set());
      studiesByRepo.get(repo.repository)!.add(study);
    }
  }
  const repositories = Array.from(studiesByRepo, ([name, studies]) => ({ name, studies: studies.size }))
    .sort((a, b) => b.studies - a.studies || a.name.localeCompare(b.name));
  return { repositories, datasets: datasets.size, studiesWithData };
}

export default function AssayObiSummary({
  stats,
  dataAvailability = {},
  children,
}: {
  stats: AssayObiStats;
  /** Every paper's data-availability record, keyed `<PMID>_<SDY>`; empty until it loads. */
  dataAvailability?: Record<string, DataAvailabilityResult>;
  /** Replaces the resolver bar — the corpus tab shows its benchmark accuracy there instead. */
  children?: ReactNode;
}) {
  const total = stats.total_rows || 1;
  const repos = useMemo(() => summarizeRepositories(dataAvailability), [dataAvailability]);
  const hasRepos = repos.repositories.length > 0;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile value={String(stats.papers)} label="papers" />
        <StatTile value={String(stats.total_rows)} label="assay rows" />
        <StatTile value={String(stats.obi_terms)} label="distinct OBI terms" />
        <StatTile
          value={hasRepos ? String(repos.repositories.length) : '—'}
          label="distinct data repositories"
          hint={
            hasRepos
              ? `${repos.repositories.map((r) => `${r.name} ${r.studies}`).join(' · ')} — ` +
                `${repos.datasets} datasets, ${repos.studiesWithData} of ${stats.papers} studies`
              : 'not run yet'
          }
        />
      </div>

      {children ?? (
      <div className="rounded-xl border border-gray-200 px-5 py-4">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">
          How each row resolved
        </h2>

        {/* 2px gaps between segments; rounded outer ends only. */}
        <div className="flex gap-0.5 h-7 mb-3">
          {stats.by_resource.map(({ resource, count }, i) => {
            const pct = (count / total) * 100;
            const isFirst = i === 0;
            const isLast = i === stats.by_resource.length - 1;
            return (
              <div
                key={resource}
                className="flex items-center justify-center overflow-hidden"
                style={{
                  width: `${pct}%`,
                  backgroundColor: RESOURCE_COLOR[resource],
                  borderTopLeftRadius: isFirst ? 4 : 0,
                  borderBottomLeftRadius: isFirst ? 4 : 0,
                  borderTopRightRadius: isLast ? 4 : 0,
                  borderBottomRightRadius: isLast ? 4 : 0,
                }}
                title={`${RESOURCE_LABEL[resource]}: ${count} rows (${pct.toFixed(1)}%)`}
              >
                {/* Direct-label only where the segment can actually hold the number. */}
                {pct >= 8 && (
                  <span className="text-xs font-medium text-white tabular-nums">{count}</span>
                )}
              </div>
            );
          })}
        </div>

        {/* Legend is always present — identity is never carried by colour alone. */}
        <div className="flex flex-wrap gap-x-5 gap-y-1.5">
          {stats.by_resource.map(({ resource, count }) => (
            <span key={resource} className="flex items-center gap-1.5 text-xs text-gray-500">
              <span
                className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                style={{ backgroundColor: RESOURCE_COLOR[resource] }}
              />
              {/* Label text wears an ink token, not the series colour. */}
              {RESOURCE_LABEL[resource]}
              <span className="text-gray-400 tabular-nums">{count}</span>
            </span>
          ))}
        </div>

        {stats.unresolved_names.length > 0 && (
          <p className="text-[11px] text-gray-400 mt-3 leading-relaxed">
            <span className="font-medium">No OBI term exists for:</span>{' '}
            {stats.unresolved_names.join(' · ')}
          </p>
        )}
      </div>
      )}
    </div>
  );
}
