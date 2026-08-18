'use client';

import type { AssayObiStats, ObiResource } from '@/lib/types';

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
  embedding_llm: '#eb6834',
  unresolved: '#898781',
};

export const RESOURCE_LABEL: Record<ObiResource, string> = {
  exact_original: 'Exact — original name',
  exact_normalized: 'Exact — normalized name',
  embedding_llm: 'Embedding + LLM',
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

export default function AssayObiSummary({ stats }: { stats: AssayObiStats }) {
  const total = stats.total_rows || 1;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile value={String(stats.total_rows)} label="assay rows" />
        <StatTile value={String(stats.papers)} label="papers" />
        <StatTile value={String(stats.obi_terms)} label="distinct OBI terms" />
        <StatTile
          value={`${stats.coverage_pct}%`}
          label="mapped to OBI"
          hint={`${stats.mapped_rows} of ${stats.total_rows} rows`}
        />
      </div>

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
    </div>
  );
}
