'use client';

import type { AssayEstimate, AssayEstimateRound } from '@/lib/types';

interface Props {
  estimate: AssayEstimate;
  onConfirm: () => void;
  busy?: boolean;
}

const ROUND_LABEL: Record<string, string> = {
  extract: 'extract',
  verify: 'verify',
  correct: 'correct',
  obi: 'OBI map',
  canonicalize: 'canonicalize',
  judge: 'judge folds',
  data_availability: 'data repositories',
};

const ROUND_DOES: Record<string, string> = {
  extract: 'builds the registry from the paper',
  verify: 'judges every entry, one call each',
  correct: 'repairs what verification refused, one call per flagged field',
  obi: 'resolves each name to an OBI term; exact matches are free',
  canonicalize: 'keys by OBI term and folds duplicates; free',
  judge: 'asks once about each fold round 5 refused on readouts or sample type',
  data_availability:
    'runs alongside the assays: finds where the study deposited its data; one call when the paper names an accession, repository lookups free',
};

/** "~8", "?" or "0" — never a number the backend could not actually stand behind. */
function callLabel(round: AssayEstimateRound): string {
  if (round.calls === null) return '?';
  return `${round.exact ? '' : '~'}${round.calls}`;
}

function roundNote(round: AssayEstimateRound): string {
  if (round.calls === null) return 'cannot be sized until round 1 finds the assays';
  switch (round.name) {
    case 'verify':
      return `the last run found ${round.assays} assay${round.assays === 1 ? '' : 's'}`;
    case 'correct':
      return `${round.rejected} assay(s) set aside last run`;
    case 'obi':
      return `${round.free_matches} of ${round.assays} match the vocabulary for free`;
    case 'canonicalize':
      return `${round.entries} entries → ${round.groups}, keyed by OBI term`;
    case 'judge': {
      const pairs = round.pairs?.length ?? round.calls;
      return pairs
        ? `${pairs} refused fold${pairs === 1 ? '' : 's'} to ask about`
        : 'no refused fold to ask about';
    }
    case 'data_availability':
      return round.entries
        ? `${round.entries} accession-like ID${round.entries === 1 ? '' : 's'} named in the paper`
        : 'the paper names no accession, so no call — repositories are still asked by PMID';
    default:
      return '';
  }
}

/**
 * The cost gate.
 *
 * CLAUDE.md requires the dry-run estimate be reported and a go-ahead waited for before a paid
 * run, so this card is the feature's centre rather than a detail of it: everything above it on
 * the page is free, and its button is the only thing on the page that spends. The numbers are
 * the ones `scripts/run_assay_pipeline.py --dry-run` prints, from the same function.
 *
 * The "~" and the "?" both survive to the screen. Rounds 2 and 3 are sized from the previous
 * run's output, which this run re-extracts rather than reuses, and a paper that has never been
 * run cannot be sized at all — rendering either as a confident number would make the gate lie.
 */
export default function AssayEstimateCard({ estimate, onConfirm, busy }: Props) {
  const total = estimate.total_calls_known
    ? `≈ ${estimate.total_calls} model call${estimate.total_calls === 1 ? '' : 's'}`
    : 'Cost unknown until round 1 finishes';
  const paidMisses = estimate.rounds.find((r) => r.name === 'obi')?.misses ?? [];
  const folds = estimate.rounds.find((r) => r.name === 'canonicalize')?.folds ?? [];
  // Counted, not written in: the data-repository step runs alongside the rounds and is not one.
  const roundCount = estimate.rounds.filter((r) => r.name !== 'data_availability').length;

  return (
    <section className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <header className="px-4 py-3 border-b border-gray-200 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium text-gray-700">Estimate</h2>
        <span className="text-xs text-gray-400">free · nothing has been called</span>
      </header>

      <div className="px-4 py-4">
        <p className="text-2xl font-semibold text-gray-900 tabular-nums">{total}</p>
        {!estimate.total_calls_known && (
          <p className="text-xs text-gray-500 mt-1">
            This paper has never been run, so rounds 2–4 cannot be sized from anything. At least
            one call, and one more per assay found.
          </p>
        )}

        <table className="w-full text-xs mt-4">
          <tbody>
            {estimate.rounds.map((round) => (
              <tr key={round.name} className="border-t border-gray-100">
                <td className="py-1.5 pr-2 text-gray-400 tabular-nums w-4">{round.round}</td>
                <td className="py-1.5 pr-3 text-gray-800 font-medium whitespace-nowrap">
                  {ROUND_LABEL[round.name]}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums whitespace-nowrap font-medium text-gray-900">
                  {callLabel(round)} call{round.calls === 1 ? '' : 's'}
                </td>
                <td className="py-1.5 text-gray-500">
                  {roundNote(round) || ROUND_DOES[round.name]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {paidMisses.length > 0 && (
          <div className="mt-3 text-xs">
            <p className="text-gray-500 mb-1">
              Names the OBI vocabulary misses — two or three calls each:
            </p>
            <ul className="space-y-0.5">
              {paidMisses.map((name) => (
                <li key={name} className="text-gray-700 pl-3 border-l-2 border-amber-200">
                  {name}
                </li>
              ))}
            </ul>
          </div>
        )}

        {folds.length > 0 && (
          <div className="mt-3 text-xs">
            <p className="text-gray-500 mb-1">Entries that would fold onto one OBI term — free:</p>
            <ul className="space-y-0.5">
              {folds.map((fold) => (
                <li key={fold.key} className="text-gray-700 pl-3 border-l-2 border-gray-200">
                  folds onto <span className="font-medium">{fold.key}</span>:{' '}
                  {fold.members.join(', ')}
                </li>
              ))}
            </ul>
          </div>
        )}

        {estimate.caveat && (
          <p className="mt-4 text-xs text-gray-500 leading-relaxed">
            <span className="font-mono text-gray-400">~</span> {estimate.caveat}
          </p>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-gray-200 bg-gray-50 flex items-center justify-between gap-3 flex-wrap">
        <p className="text-xs text-gray-500">
          Every round runs on every request — re-running this paper costs what the first run cost.
        </p>
        <button
          onClick={onConfirm}
          disabled={busy}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy
            ? 'Starting…'
            : `Run all ${roundCount} rounds${estimate.total_calls_known ? ` — ≈${estimate.total_calls} calls` : ''}`}
        </button>
      </footer>
    </section>
  );
}
