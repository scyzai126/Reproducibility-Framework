'use client';

import type { BenchmarkCounts } from './AssayBenchmarkResults';
import { pct } from './AssayBenchmarkResults';
import { ASSAY_TABLE_ID } from './AssayObiTable';

/**
 * The validated resolver swatches, reused rather than extended by eye (see AssayObiSummary):
 * dark blue = the agent agrees with the curator, lighter blue = it agrees loosely, orange = it
 * does not, grey = the null slot, where there is nothing to compare. The three hues pass the
 * palette validator as a set; grey fails only the chroma floor, which is what makes it read as
 * "no value" rather than as a fourth series.
 */
const AGREE = '#184f95';
const CLOSE = '#3987e5';
const MISS = '#eb6834';
const NONE = '#898781';

interface Segment {
  label: string;
  count: number;
  color: string;
  /** The `benchmarkViews` id this segment filters the table to. */
  view: string;
}

/** Select a view (or clear it when it is already selected) and bring the table into sight. */
type Pick = (view: string) => void;

const TITLE = 'Show these rows in the table below';

function RatioBar({
  title,
  subtitle,
  segments,
  note,
  active,
  onPick,
}: {
  title: string;
  subtitle: string;
  segments: Segment[];
  note?: { text: string; view: string };
  active: string | null;
  onPick: Pick;
}) {
  const total = segments.reduce((sum, s) => sum + s.count, 0) || 1;
  const shown = segments.filter((s) => s.count > 0);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <span className="text-sm text-gray-900">{title}</span>
        <span className="text-xs text-gray-400">{subtitle}</span>
      </div>
      {/* 2px gaps between segments; rounded outer ends only. */}
      <div className="flex gap-0.5 h-7 mb-2">
        {shown.map((s, i) => {
          const share = (s.count / total) * 100;
          return (
            <button
              key={s.label}
              onClick={() => onPick(s.view)}
              aria-pressed={active === s.view}
              className={`flex items-center justify-center overflow-hidden transition-opacity hover:opacity-85 ${
                active && active !== s.view ? 'opacity-40' : ''
              }`}
              style={{
                width: `${share}%`,
                backgroundColor: s.color,
                borderTopLeftRadius: i === 0 ? 4 : 0,
                borderBottomLeftRadius: i === 0 ? 4 : 0,
                borderTopRightRadius: i === shown.length - 1 ? 4 : 0,
                borderBottomRightRadius: i === shown.length - 1 ? 4 : 0,
              }}
              title={`${s.label}: ${s.count} (${share.toFixed(1)}%) — ${TITLE.toLowerCase()}`}
            >
              {/* Direct-label only where the segment can actually hold it. */}
              {share >= 12 && (
                <span className="text-xs font-medium text-white tabular-nums">
                  {s.count} · {Math.round(share)}%
                </span>
              )}
            </button>
          );
        })}
      </div>
      {/* Legend is always present — identity is never carried by colour alone. */}
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        {segments.map((s) => {
          const on = active === s.view;
          return (
            <button
              key={s.label}
              onClick={() => onPick(s.view)}
              aria-pressed={on}
              title={on ? 'Show all rows' : TITLE}
              className={`flex items-center gap-1.5 text-xs transition-colors hover:text-gray-900 ${
                on ? 'text-gray-900 font-medium underline underline-offset-2' : 'text-gray-500'
              }`}
            >
              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: s.color }} />
              {s.label}
              <span className={`tabular-nums ${on ? 'text-gray-700' : 'text-gray-400'}`}>
                {s.count} ({pct(s.count, total)})
              </span>
            </button>
          );
        })}
      </div>
      {note && (
        <button
          onClick={() => onPick(note.view)}
          aria-pressed={active === note.view}
          title={active === note.view ? 'Show all rows' : TITLE}
          className={`block text-left text-[11px] mt-1.5 transition-colors hover:text-gray-900 ${
            active === note.view ? 'text-gray-900 font-medium underline underline-offset-2' : 'text-gray-400'
          }`}
        >
          {note.text}
        </button>
      )}
    </div>
  );
}

/** How accurate the agent is against the curators' benchmark, as three part-to-whole bars. */
export default function AssayAccuracyBars({
  counts,
  immportState,
  view,
  onView,
}: {
  counts: BenchmarkCounts;
  /** "loading" until the ImmPort fetch returns; "unavailable" when it failed or degraded. */
  immportState: 'loading' | 'ready' | 'unavailable';
  /** The legend word currently filtering the table, and the setter shared with the table. */
  view: string | null;
  onView: (view: string | null) => void;
}) {
  const c = counts;
  const onPick: Pick = (picked) => {
    const next = view === picked ? null : picked;
    onView(next);
    if (next) {
      document.getElementById(ASSAY_TABLE_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };
  const shared = { active: view, onPick };
  return (
    <div className="rounded-xl border border-gray-200 px-5 py-4 space-y-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          How accurate the agent is
        </h2>
        <span className="text-[11px] text-gray-400">Click a label or bar to filter the table</span>
      </div>

      <RatioBar
        title="Finding the curators' assays"
        subtitle={`${c.curated} curated assays`}
        segments={[
          { label: 'found', count: c.found, color: AGREE, view: 'found' },
          { label: 'missed', count: c.missed, color: MISS, view: 'missed' },
        ]}
        note={{
          text: `+${c.extra} extra assays the agent found that the curators don't list — the benchmark is a recall reference, so these are not counted as errors.`,
          view: 'extra',
        }}
        {...shared}
      />

      <RatioBar
        title="OBI term vs. the curator's"
        subtitle={`${c.found} found assays`}
        segments={[
          { label: 'same term', count: c.same, color: AGREE, view: 'same' },
          { label: 'broader or narrower', count: c.related, color: CLOSE, view: 'related' },
          { label: 'different term', count: c.differs, color: MISS, view: 'differs' },
          { label: 'no term to compare', count: c.curatorUnmapped + c.oursUnmapped, color: NONE, view: 'nocompare' },
        ]}
        {...shared}
      />

      {immportState === 'ready' && c.immportChecked > 0 ? (
        <RatioBar
          title="Registered in ImmPort"
          subtitle={`${c.ours} of our assays`}
          segments={[
            { label: 'in ImmPort', count: c.inImmport, color: AGREE, view: 'immport' },
            { label: 'not in ImmPort', count: c.immportChecked - c.inImmport, color: NONE, view: 'not-immport' },
          ]}
          {...shared}
        />
      ) : (
        <p className="text-xs text-gray-400">
          {immportState === 'loading'
            ? 'Checking ImmPort…'
            : 'ImmPort coverage is unavailable.'}
        </p>
      )}
    </div>
  );
}
