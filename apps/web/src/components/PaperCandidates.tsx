'use client';

import type { PaperCandidate, ResolveResponse } from '@/lib/types';

interface Props {
  resolution: ResolveResponse;
  onChoose: (paper: PaperCandidate) => void;
  disabled?: boolean;
}

/**
 * Which paper did that identifier mean?
 *
 * The mapping between PubMed IDs and study accessions is many-to-many — SDY212 has six papers,
 * PubMed ID 26682988 belongs to five studies — so this list exists because the backend refuses
 * to pick one. Getting it wrong does not produce a bad extraction: it produces a correct,
 * verified registry filed under a study it does not describe, which is cheap to do and invisible
 * afterwards. So the title and year are the primary text, and a paper that already has a
 * registry is badged, because that is usually the one meant.
 */
export default function PaperCandidates({ resolution, onChoose, disabled }: Props) {
  const { candidates } = resolution;

  if (candidates.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
        <p className="text-sm text-gray-600">{resolution.reason ?? 'Nothing matched.'}</p>
      </div>
    );
  }

  return (
    <section className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <header className="px-4 py-2.5 border-b border-gray-200 flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-medium text-gray-700">
          {resolution.normalized} matches {candidates.length} papers — which one?
        </h3>
        <span className="text-xs text-gray-400">free · nothing has been called</span>
      </header>

      {resolution.warning && (
        <p className="px-4 py-2 text-xs text-amber-800 bg-amber-50 border-b border-amber-200">
          {resolution.warning}
        </p>
      )}

      <ul className="divide-y divide-gray-100">
        {candidates.map((candidate) => (
          <li key={`${candidate.study_accession}-${candidate.pubmed_id}`}>
            <button
              onClick={() => onChoose(candidate)}
              disabled={disabled || !candidate.usable}
              className="w-full text-left px-4 py-2.5 hover:bg-gray-50 transition-colors disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:opacity-60"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs text-gray-500">
                  {candidate.study_accession} · {candidate.pubmed_id}
                </span>
                {candidate.year && (
                  <span className="text-xs text-gray-400">{candidate.year}</span>
                )}
                {candidate.has_registry ? (
                  <span className="text-xs text-emerald-700">
                    {candidate.assays ?? '?'} assays already extracted
                  </span>
                ) : candidate.has_xml ? (
                  <span className="text-xs text-gray-400">paper on disk, never run</span>
                ) : (
                  <span className="text-xs text-gray-400">will be fetched from PMC</span>
                )}
                {!candidate.in_db && (
                  <span className="text-xs text-amber-700">not in ImmPort</span>
                )}
                {!candidate.usable && (
                  <span className="text-xs text-amber-700">cannot be run</span>
                )}
              </div>
              <p className="text-sm text-gray-800 mt-0.5">
                {candidate.title ?? candidate.paper_title ?? '(no title)'}
              </p>
              {candidate.journal && (
                <p className="text-xs text-gray-400 mt-0.5">{candidate.journal}</p>
              )}
              {/* Why, not just that: the reason names the way forward where there is one. */}
              {candidate.unusable_reason && (
                <p className="text-xs text-amber-700 mt-1">{candidate.unusable_reason}</p>
              )}
            </button>
          </li>
        ))}
      </ul>

      <footer className="px-4 py-2 border-t border-gray-200 bg-gray-50">
        <p className="text-xs text-gray-500">
          The accession decides which study directory the registry is written under — picking the
          wrong one files a real result under a study it does not describe.
        </p>
      </footer>
    </section>
  );
}
