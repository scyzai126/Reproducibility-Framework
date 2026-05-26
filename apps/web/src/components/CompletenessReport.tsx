'use client';

import { useState } from 'react';
import { CompletnessSummary, ClaimFailures, GroupFailures, ResolutionFailure, DataGap } from '@/lib/types';

const FIELD_LABELS: Record<string, string> = {
  cohort: 'Cohort',
  assay_method: 'Assay method',
  disease: 'Disease',
  disease_stage: 'Disease stage',
  time_point: 'Time point',
};

// Which key in the candidate dict to display as the human-readable label
const CANDIDATE_NAME_KEY: Record<string, string> = {
  cohort: 'name',
  assay_method: 'name',
};

const FIELD_ORDER: Record<string, number> = { assay_method: 0 };
function sortByFieldPriority<T extends { field: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => (FIELD_ORDER[a.field] ?? 99) - (FIELD_ORDER[b.field] ?? 99));
}

function FieldPill({ field, count }: { field: string; count: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded-md px-2 py-0.5">
      <span>{FIELD_LABELS[field] ?? field}</span>
      <span className="font-mono font-semibold">×{count}</span>
    </span>
  );
}

function FailureDetail({ f }: { f: ResolutionFailure }) {
  const nameKey = CANDIDATE_NAME_KEY[f.field];
  const names = nameKey && f.immport_candidates?.length
    ? f.immport_candidates.map(c => c[nameKey]).filter(Boolean)
    : [];
  return (
    <div className="grid grid-cols-[100px_1fr] gap-x-3 gap-y-0.5 text-xs">
      <span className="text-amber-600 font-medium truncate pt-px">
        {FIELD_LABELS[f.field] ?? f.field}
      </span>
      <div className="space-y-0.5">
        <span className="font-mono text-gray-700 bg-gray-100 rounded px-1.5 py-0.5 inline-block">
          {f.original_value}
        </span>
        <p className="text-gray-400 leading-snug">{f.tried}</p>
        {names.length > 0 && (
          <p className="text-gray-500 leading-snug">
            <span className="font-medium">Available in ImmPort: </span>
            {names.join(', ')}
          </p>
        )}
      </div>
    </div>
  );
}

function GroupFailureRow({ group }: { group: GroupFailures }) {
  if (!group.failures.length) return null;
  return (
    <div className="space-y-1.5">
      {sortByFieldPriority(group.failures).map((f, i) => (
        <FailureDetail key={i} f={f} />
      ))}
    </div>
  );
}

function ClaimLevelFailureRow({ failure }: { failure: ResolutionFailure }) {
  return <FailureDetail f={failure} />;
}

function DataGapRow({ gap }: { gap: DataGap }) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-x-3 gap-y-0.5 text-xs">
      <span className="text-rose-500 font-medium truncate pt-px">Group {gap.group_id}</span>
      <div className="space-y-0.5">
        <p className="text-gray-700 leading-snug">{gap.reason}</p>
      </div>
    </div>
  );
}

function ClaimFailureCard({ entry, index }: { entry: ClaimFailures; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const claimLevelCount = entry.claim_failures?.length ?? 0;
  const totalFailures = claimLevelCount + entry.groups.reduce((n, g) => n + g.failures.length, 0);
  const dataGapCount = entry.data_gaps?.length ?? 0;
  const hasFailures = totalFailures > 0;
  const hasDataGaps = dataGapCount > 0;

  const unresolvedFields = Array.from(new Set([
    ...sortByFieldPriority([
      ...(entry.claim_failures ?? []),
      ...entry.groups.flatMap(g => g.failures),
    ]).map(f => FIELD_LABELS[f.field] ?? f.field),
  ]));

  return (
    <div className="rounded-xl border border-amber-200 overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 bg-amber-50 hover:bg-amber-100/70 transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            {hasFailures && (
              <span className="text-xs font-medium text-amber-700">
                Unresolved: {unresolvedFields.join(', ')}
              </span>
            )}
            {hasDataGaps && !hasFailures && (
              <span className="text-xs text-rose-500">
                {dataGapCount} group{dataGapCount !== 1 ? 's' : ''} with assay but no linked subjects
              </span>
            )}
          </div>
          <p className="text-xs text-gray-600 line-clamp-2">
            <span className="font-medium text-gray-500">Claim: </span>{entry.claim_text}
          </p>
        </div>
        <svg
          xmlns="http://www.w3.org/2000/svg" width="14" height="14"
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`flex-shrink-0 mt-1 text-amber-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div className="bg-white">
          {/* Original claim sources */}
          {(() => {
            const allSources = entry.sources?.length ? entry.sources : (entry.source ? [entry.source] : []);
            const validSources = allSources.filter(s => s.section || s.quote || s.ref);
            if (!validSources.length) return null;
            return (
              <div className="px-4 py-3 border-b border-amber-100 bg-amber-50/40 space-y-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-500">
                  Sources ({validSources.length})
                </p>
                {validSources.map((s, i) => (
                  <div key={i} className="space-y-0.5">
                    {s.section && (
                      <p className="text-xs text-gray-500">
                        <span className="font-medium text-gray-600">Section: </span>{s.section}
                      </p>
                    )}
                    {s.quote && (
                      <p className="text-xs text-gray-500 italic border-l-2 border-amber-300 pl-2">
                        &ldquo;{s.quote}&rdquo;
                      </p>
                    )}
                    {s.ref && (
                      <p className="text-xs text-gray-400">{s.ref}</p>
                    )}
                  </div>
                ))}
              </div>
            );
          })()}
          {/* Claim-level failures (assay_method — same for all groups) */}
          {hasFailures && entry.claim_failures && entry.claim_failures.length > 0 && (
            <div className="px-4 py-3 border-b border-amber-100 space-y-1.5">
              <p className="text-xs text-gray-400 mb-2">Applies to all groups</p>
              {sortByFieldPriority(entry.claim_failures).map((f, i) => (
                <ClaimLevelFailureRow key={i} failure={f} />
              ))}
            </div>
          )}
          {/* Per-group resolution failures */}
          {hasFailures && entry.groups.length > 0 && (
            <div className="divide-y divide-amber-100">
              {entry.groups.map((group, i) => (
                <div key={i} className="px-4 py-3">
                  <p className="text-xs text-gray-400 mb-2">Group {group.group_id}</p>
                  <GroupFailureRow group={group} />
                </div>
              ))}
            </div>
          )}
          {/* Data gaps: resolved correctly but no data in ImmPort */}
          {hasDataGaps && (
            <div className={`${hasFailures ? 'border-t border-rose-100' : ''}`}>
              <div className="px-4 py-2 bg-rose-50/60">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-rose-400">
                  Assay exists in ImmPort — no linked subjects/samples
                </p>
              </div>
              <div className="divide-y divide-rose-50">
                {entry.data_gaps!.map((gap, i) => (
                  <div key={i} className="px-4 py-3">
                    <DataGapRow gap={gap} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface Props {
  summary: CompletnessSummary;
  claimFailures: ClaimFailures[];
}

export default function CompletenessReport({ summary, claimFailures }: Props) {
  const allResolved = summary.claims_with_failures === 0;
  const dataGapGroups = summary.data_gap_groups ?? 0;

  return (
    <div className="space-y-3 text-sm">
      {/* Partial-completeness header */}
      {!allResolved && (
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0" />
          <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide">
            This study is partially complete in ImmPort
          </p>
        </div>
      )}
      {/* Summary bar */}
      <div className={`rounded-xl border px-4 py-3 flex items-start gap-3 ${
        allResolved
          ? 'border-emerald-200 bg-emerald-50'
          : 'border-amber-200 bg-amber-50'
      }`}>
        {allResolved ? (
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 mt-0.5 text-emerald-500">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 mt-0.5 text-amber-500">
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        )}
        <div className="flex-1 min-w-0">
          {allResolved ? (
            <p className="text-xs font-medium text-emerald-700">
              All fields resolved — {summary.total_claims} claim{summary.total_claims !== 1 ? 's' : ''} fully matched to ImmPort
            </p>
          ) : (
            <>
              <p className="text-xs font-medium text-amber-700 mb-1">
                {summary.claims_with_failures} of {summary.total_claims} claim{summary.total_claims !== 1 ? 's' : ''} have issues
                {summary.failed_groups > 0 && ` · ${summary.failed_groups} group${summary.failed_groups !== 1 ? 's' : ''} with unresolved fields`}
                {dataGapGroups > 0 && ` · ${dataGapGroups} group${dataGapGroups !== 1 ? 's' : ''} with assay but no linked subjects`}
              </p>
              {summary.failed_fields.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {summary.failed_fields.map((f, i) => (
                    <FieldPill key={i} field={f.field} count={f.count} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* All-complete state */}
      {allResolved && dataGapGroups === 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-6 py-8 flex flex-col items-center gap-3 text-center">
          <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-500">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-emerald-800">Data is complete in ImmPort for this study</p>
            <p className="text-xs text-emerald-600 mt-1">
              All {summary.total_claims} claim{summary.total_claims !== 1 ? 's' : ''} were fully matched — every cohort, assay, and filter resolved to an ImmPort record.
            </p>
          </div>
        </div>
      )}

      {/* Per-claim details */}
      {!allResolved && claimFailures.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
            Incompleteness by claim
          </p>
          {[...claimFailures].sort((a, b) => {
            const hasAssay = (c: ClaimFailures) =>
              (c.claim_failures ?? []).some(f => f.field === 'assay_method') ||
              c.groups.some(g => g.failures.some(f => f.field === 'assay_method'));
            return Number(hasAssay(b)) - Number(hasAssay(a));
          }).map((entry, i) => (
            <ClaimFailureCard key={entry.claim_id ?? i} entry={entry} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
