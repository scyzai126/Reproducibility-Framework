'use client';

import { useState } from 'react';
import type { AssayBenchmarkEntry, AssayEvidence, AssayObiEntry } from '@/lib/types';

interface Props {
  benchmark: Record<string, AssayBenchmarkEntry>;
  /** The ten-field record every pass in the chain works from. */
  registry?: Record<string, AssayBenchmarkEntry> | null;
  obi?: Record<string, AssayObiEntry> | null;
  meta?: { benchmark_path?: string; registry_path?: string; obi_path?: string | null };
  /** True when round 5 did not run, so the keys are paper wordings rather than OBI labels. */
  notCanonical?: boolean;
}

/** `name_in_paper` is a list after round 5 and a string before it; both are on disk. */
function paperNames(entry: AssayBenchmarkEntry): string[] {
  const names = entry.name_in_paper;
  if (Array.isArray(names)) return names;
  return names ? [names] : [];
}

function Evidence({ evidence }: { evidence: AssayEvidence | null | undefined }) {
  if (!evidence) return <p className="text-xs text-gray-400">no evidence recorded</p>;
  const ids = evidence.sentence_ids ?? [];
  return (
    <>
      <p className="text-xs text-gray-500">
        {evidence.section || 'no section'}{' '}
        <span className="font-mono text-gray-400">
          [{ids.length ? ids.join(', ') : 'no sentence ids'}]
        </span>
      </p>
      {evidence.quote ? (
        <blockquote className="mt-1 text-xs text-gray-600 italic border-l-2 border-emerald-200 pl-3">
          {evidence.quote}
        </blockquote>
      ) : (
        <p className="mt-1 text-xs text-amber-700">no quote</p>
      )}
    </>
  );
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex gap-3 text-xs">
      <span className="w-24 flex-shrink-0 text-gray-400">{label}</span>
      <span className="text-gray-700">
        {value === null || value === undefined || value === '' ? (
          <span className="text-gray-400">(none)</span>
        ) : (
          String(value)
        )}
      </span>
    </div>
  );
}

/**
 * The deliverable.
 *
 * `assays_benchmark.json` is the file to read, per CLAUDE.md — keyed by the assay's OBI label,
 * carrying only `name_in_paper`, `aliases`, `source` and `evidence`, plus `additional_evidence`
 * where round 5 folded another write-up onto the same term. The full ten-field record behind
 * it is a toggle rather than the default, because it is what the pipeline works from rather
 * than what a reader is being asked to check.
 *
 * `name_in_paper` is rendered as a list of every wording and never joined into one string: the
 * whole point of the field is that one OBI term can have been written up several ways.
 */
export default function AssayBenchmarkView({ benchmark, registry, obi, meta, notCanonical }: Props) {
  const [showFull, setShowFull] = useState(false);
  const keys = Object.keys(benchmark);

  return (
    <section className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <header className="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-medium text-gray-700">
            {keys.length} assay{keys.length === 1 ? '' : 's'}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            {notCanonical
              ? 'keyed by the paper’s wording — round 5 did not run'
              : 'keyed by OBI label'}
          </p>
        </div>
        {registry && (
          <button
            onClick={() => setShowFull((v) => !v)}
            className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
          >
            {showFull ? 'Show the deliverable' : 'Show the full 7-field record'}
          </button>
        )}
      </header>

      {notCanonical && (
        <p className="px-4 py-2.5 text-xs text-amber-800 bg-amber-50 border-b border-amber-200">
          OBI mapping did not run, so the registry was never re-keyed. These keys are the
          paper’s own wordings, and two write-ups of one technique are still two entries.
        </p>
      )}

      {keys.length === 0 && (
        <p className="px-4 py-4 text-sm text-gray-500">This run found no assays.</p>
      )}

      <ul className="divide-y divide-gray-100">
        {keys.map((key) => {
          const entry = benchmark[key];
          const full = registry?.[key];
          const term = obi?.[key];
          return (
            <li key={key} className="px-4 py-3">
              <div className="flex items-baseline gap-2 flex-wrap">
                <h3 className="text-sm font-medium text-gray-900">{key}</h3>
                {term?.obi_id && (
                  <span className="font-mono text-xs text-gray-400">{term.obi_id}</span>
                )}
                {entry.source && (
                  <span className="px-1.5 py-0.5 text-[10px] rounded border border-gray-200 text-gray-500">
                    {entry.source}
                  </span>
                )}
              </div>

              <div className="mt-2 space-y-1">
                <div className="flex gap-3 text-xs">
                  <span className="w-24 flex-shrink-0 text-gray-400">in paper</span>
                  <ul className="text-gray-700 space-y-0.5">
                    {paperNames(entry).length === 0 && <li className="text-gray-400">(none)</li>}
                    {paperNames(entry).map((name) => (
                      <li key={name}>{name}</li>
                    ))}
                  </ul>
                </div>

                <div className="flex gap-3 text-xs">
                  <span className="w-24 flex-shrink-0 text-gray-400">aliases</span>
                  <span className="flex flex-wrap gap-1">
                    {(entry.aliases ?? []).length === 0 ? (
                      <span className="text-gray-400">(none)</span>
                    ) : (
                      (entry.aliases ?? []).map((alias) => (
                        <span
                          key={alias}
                          className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600"
                        >
                          {alias}
                        </span>
                      ))
                    )}
                  </span>
                </div>

                {showFull && full && (
                  <>
                    <Row label="standard technique" value={full.standard_technique_name} />
                    <Row label="platform" value={full.platform} />
                    <Row label="sample type" value={full.sample_type} />
                    <Row label="readouts" value={full.readouts} />
                  </>
                )}

                <div className="flex gap-3 text-xs">
                  <span className="w-24 flex-shrink-0 text-gray-400">evidence</span>
                  <div className="min-w-0">
                    <Evidence evidence={entry.evidence} />
                  </div>
                </div>

                {/* The judge's doubt about the identity. No round repairs an identity, so this
                    is the only place the doubt reaches the reader. */}
                {entry.identity_review?.verdict && (
                  <div className="flex gap-3 text-xs">
                    <span className="w-24 flex-shrink-0 text-gray-400">identity</span>
                    <p className="min-w-0 text-amber-700">
                      <span className="font-medium">{entry.identity_review.verdict}</span>
                      {entry.identity_review.reason ? ` — ${entry.identity_review.reason}` : ''}
                    </p>
                  </div>
                )}

                {/* The second write-up's evidence survives the fold; it is the one thing the
                    surviving record cannot reconstruct. */}
                {(entry.additional_evidence ?? []).length > 0 && (
                  <div className="flex gap-3 text-xs">
                    <span className="w-24 flex-shrink-0 text-gray-400">also reported as</span>
                    <div className="min-w-0 space-y-2">
                      {(entry.additional_evidence ?? []).map((extra, index) => (
                        <div key={index}>
                          <p className="text-gray-700">{extra.name_in_paper}</p>
                          <Evidence evidence={extra.evidence} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {meta && (meta.benchmark_path || meta.registry_path) && (
        <footer className="px-4 py-2.5 border-t border-gray-200 bg-gray-50 space-y-0.5">
          {meta.benchmark_path && (
            <p className="text-xs text-gray-500 font-mono">
              {meta.benchmark_path}{' '}
              <span className="font-sans text-gray-400">← the deliverable</span>
            </p>
          )}
          {meta.registry_path && (
            <p className="text-xs text-gray-400 font-mono">
              {meta.registry_path}{' '}
              <span className="font-sans">full ten-field registry the pipeline works from</span>
            </p>
          )}
          {meta.obi_path && (
            <p className="text-xs text-gray-400 font-mono">
              {meta.obi_path} <span className="font-sans">the same registry with OBI terms</span>
            </p>
          )}
        </footer>
      )}
    </section>
  );
}
