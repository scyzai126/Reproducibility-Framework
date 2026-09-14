'use client';

import { FINDING_ORDER, FINDING_TONE } from '@/lib/findings';
import type { Finding } from '@/lib/types';

interface Props {
  findings: Finding[];
  /** What was checked, so a clean run reads as "checked and clean" rather than as an empty box. */
  checked?: string;
}

/**
 * Every finding, listed.
 *
 * CLAUDE.md requires each WARNING / REVIEW / REJECT / DROPPED / MERGED / UNMAPPED /
 * CORRECT FAILED line be reported rather than summarised away, and this is the component most
 * likely to break that rule as the list grows. So the enforcement is structural: the body is a
 * flat `.map` over every finding. There is no collapse, no pagination, and no "and 4 more" —
 * adding one would be the bug.
 *
 * The counts across the top are a summary *in addition to* the list, never instead of it.
 */
export default function AssayFindingsPanel({ findings, checked }: Props) {
  const counts = FINDING_ORDER.map((kind) => ({
    kind,
    count: findings.filter((f) => f.kind === kind).length,
  })).filter(({ count }) => count > 0);

  const ordered = FINDING_ORDER.flatMap((kind) => findings.filter((f) => f.kind === kind));

  return (
    <section className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <header className="px-4 py-3 border-b border-gray-200">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h2 className="text-sm font-medium text-gray-700">Findings</h2>
          <span className="text-xs text-gray-400">
            {findings.length === 0
              ? 'nothing to report'
              : `${findings.length} to read`}
          </span>
        </div>
        {counts.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {counts.map(({ kind, count }) => (
              <span
                key={kind}
                className={`px-2 py-0.5 text-xs rounded-md border font-medium ${FINDING_TONE[kind]}`}
              >
                {kind} {count}
              </span>
            ))}
          </div>
        )}
      </header>

      {ordered.length === 0 ? (
        <p className="px-4 py-4 text-sm text-gray-500">
          Nothing was flagged.{' '}
          {checked ??
            'The extraction contract held, every entry was supported, every quote was verbatim, and every assay mapped to an OBI term.'}
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {ordered.map((finding, index) => (
            <li key={`${finding.kind}-${finding.subject}-${index}`} className="px-4 py-2.5">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span
                  className={`px-1.5 py-0.5 text-[10px] rounded border font-medium tracking-wide flex-shrink-0 ${FINDING_TONE[finding.kind]}`}
                >
                  {finding.kind}
                </span>
                {finding.subject && (
                  <span className="text-sm text-gray-900 font-medium">{finding.subject}</span>
                )}
                <span className="text-xs text-gray-500">{finding.detail}</span>
              </div>
              {/* The record verdict carries no reason of its own — it is derived from these. */}
              {finding.fields && finding.fields.length > 0 && (
                <ul className="mt-1.5 ml-1 space-y-0.5">
                  {finding.fields.map((field) => (
                    <li
                      key={field.field}
                      className="text-xs text-gray-600 pl-3 border-l-2 border-gray-200"
                    >
                      <span className="font-mono text-gray-500">{field.field}</span>:{' '}
                      <span className="font-medium">{field.verdict}</span> — {field.reason}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
