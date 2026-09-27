/**
 * The corpus benchmark results: the counts the accuracy bars draw, and the row filters their
 * legend selects. Logic only -- the bars (AssayAccuracyBars) and the table render it.
 */

import type { AssayImmportRow, AssayObiRow, BenchmarkObiMatch } from '@/lib/types';

/** One selectable result: a count, and the rows it stands for. */
export interface ResultView {
  id: string;
  group: string;
  label: string;
  value: string;
  hint: string;
  /** Which table rows this result is about — selecting it filters the table to them. */
  matches: (row: AssayObiRow, immport: AssayImmportRow | undefined) => boolean;
}

/** Best first: a curator assay paired with two of our entries is counted by its best pairing. */
const MATCH_ORDER: BenchmarkObiMatch[] = [
  'same', 'related', 'differs', 'curator_unmapped', 'ours_unmapped', 'missed',
];

const hasMatch = (row: AssayObiRow, wanted: BenchmarkObiMatch[]) =>
  !row.benchmark_only && (row.benchmark_items ?? []).some((i) => wanted.includes(i.obi_match));

export const pct = (n: number, d: number) => (d ? `${Math.round((n / d) * 100)}%` : '—');

/** The corpus-wide numbers behind the accuracy bars and their row filters. */
export interface BenchmarkCounts {
  curated: number;
  found: number;
  missed: number;
  extra: number;
  ours: number;
  same: number;
  related: number;
  differs: number;
  curatorUnmapped: number;
  oursUnmapped: number;
  immportChecked: number;
  inImmport: number;
}

/**
 * How the agent's assays line up with the curators' benchmark, how its OBI terms compare with
 * theirs, and how many ImmPort registers. The benchmark groups count *curator assays* -- one
 * curator assay paired with two of our entries counts once, by its best pairing -- and ImmPort
 * counts our assays.
 */
export function benchmarkCounts(
  rows: AssayObiRow[],
  coverage: Map<string, AssayImmportRow>,
  keyOf: (row: AssayObiRow) => string,
): BenchmarkCounts {
  const best = new Map<string, BenchmarkObiMatch>();
  for (const row of rows) {
    for (const item of row.benchmark_items ?? []) {
      const key = `${row.study}\u0000${item.key}`;
      const prev = best.get(key);
      if (!prev || MATCH_ORDER.indexOf(item.obi_match) < MATCH_ORDER.indexOf(prev)) {
        best.set(key, item.obi_match);
      }
    }
  }
  const count = (wanted: BenchmarkObiMatch) =>
    Array.from(best.values()).filter((m) => m === wanted).length;
  const ours = rows.filter((r) => !r.benchmark_only);
  const checked = ours.filter((r) => coverage.has(keyOf(r)));
  return {
    curated: best.size,
    found: best.size - count('missed'),
    missed: count('missed'),
    extra: ours.filter((r) => !(r.benchmark_items ?? []).length).length,
    ours: ours.length,
    same: count('same'),
    related: count('related'),
    differs: count('differs'),
    curatorUnmapped: count('curator_unmapped'),
    oursUnmapped: count('ours_unmapped'),
    immportChecked: checked.length,
    inImmport: checked.filter((r) => coverage.get(keyOf(r))?.status === 'matched').length,
  };
}

/** One view per legend word under the accuracy bars; selecting one filters the table to its rows. */
export function benchmarkViews(
  rows: AssayObiRow[],
  coverage: Map<string, AssayImmportRow>,
  keyOf: (row: AssayObiRow) => string,
): ResultView[] {
  const c = benchmarkCounts(rows, coverage, keyOf);
  const { curated, found, extra, inImmport } = c;
  const noCompare = c.curatorUnmapped + c.oursUnmapped;
  const immportValue = (n: number) => (c.immportChecked ? String(n) : '—');

  return [
    {
      id: 'found', group: 'Benchmark', label: 'curator assays we found',
      value: `${found} / ${curated}`, hint: `${pct(found, curated)} recall`,
      matches: (r) => hasMatch(r, MATCH_ORDER.filter((m) => m !== 'missed')),
    },
    {
      id: 'missed', group: 'Benchmark', label: 'curator assays we missed',
      value: String(c.missed), hint: 'in the benchmark, not in our registry',
      matches: (r) => Boolean(r.benchmark_only),
    },
    {
      id: 'extra', group: 'Benchmark', label: 'extra assays we found',
      value: String(extra), hint: 'in our registry, not in the benchmark',
      matches: (r) => !r.benchmark_only && !(r.benchmark_items ?? []).length,
    },
    {
      id: 'same', group: 'OBI term vs. the curator', label: 'same OBI term',
      value: String(c.same), hint: `${pct(c.same, found)} of the ${found} found`,
      matches: (r) => hasMatch(r, ['same']),
    },
    {
      id: 'related', group: 'OBI term vs. the curator', label: 'broader or narrower term',
      value: String(c.related), hint: 'one term is an is_a ancestor of the other',
      matches: (r) => hasMatch(r, ['related']),
    },
    {
      id: 'differs', group: 'OBI term vs. the curator', label: 'different term',
      value: String(c.differs), hint: 'unrelated OBI terms',
      matches: (r) => hasMatch(r, ['differs']),
    },
    {
      id: 'nocompare', group: 'OBI term vs. the curator', label: 'no term to compare',
      value: String(noCompare),
      hint: `curator gave none: ${c.curatorUnmapped} · we gave none: ${c.oursUnmapped}`,
      matches: (r) => hasMatch(r, ['curator_unmapped', 'ours_unmapped']),
    },
    {
      id: 'immport', group: 'ImmPort', label: 'in ImmPort',
      value: immportValue(inImmport), hint: `${pct(inImmport, c.immportChecked)} of ${c.ours}`,
      matches: (r, hit) => hit?.status === 'matched',
    },
    {
      id: 'not-immport', group: 'ImmPort', label: 'not in ImmPort',
      value: immportValue(c.immportChecked - inImmport),
      hint: 'no matching experiment for the study',
      matches: (r, hit) => Boolean(hit) && hit?.status !== 'matched',
    },
  ];
}
