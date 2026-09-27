'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import AssayCorpusPanel from '@/components/AssayCorpusPanel';
import AssayExtractPanel from '@/components/AssayExtractPanel';
import PaperTurnFeed from '@/components/PaperTurnFeed';

type Tab = 'benchmark' | 'extract';

const TABS: { id: Tab; label: string; blurb: string }[] = [
  {
    id: 'benchmark',
    label: 'Benchmark',
    blurb:
      'The 31 benchmark papers: every assay the agent extracted, mapped to its OBI term and ' +
      "scored against the curators' benchmark — how many it found, missed and added, how its " +
      'OBI terms compare, and which ImmPort registers.',
  },
  {
    id: 'extract',
    label: 'Extract',
    blurb:
      'Type an identifier to fetch and run a paper, or pick one from the list below. The ' +
      'deliverable is assays_benchmark.json. Nothing here spends until you press Run — except ' +
      'a paper that has never been run, which starts as soon as it is fetched.',
  },
];

export default function AssaysPage() {
  const [tab, setTab] = useState<Tab>('benchmark');

  // Read and write the tab through the URL directly rather than through useSearchParams, which
  // would force a Suspense boundary for prerender — a failure that only shows up at build time,
  // and this project does not build during development.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('tab');
    // `corpus` is the tab's old name; links and bookmarks that still use it land here too.
    if (requested === 'extract') setTab('extract');
    else if (requested === 'benchmark' || requested === 'corpus') setTab('benchmark');
  }, []);

  const select = (next: Tab) => {
    setTab(next);
    const params = new URLSearchParams(window.location.search);
    params.set('tab', next);
    window.history.replaceState(null, '', `${window.location.pathname}?${params}`);
  };

  const active = TABS.find((t) => t.id === tab) ?? TABS[0];

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <header className="mb-4">
          <Link
            href="/"
            className="text-xs text-gray-400 hover:text-emerald-700 transition-colors"
          >
            ← Back to analysis
          </Link>
          <h1 className="text-xl font-bold text-gray-900 mt-2">Assays</h1>
          <p className="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">{active.blurb}</p>
        </header>

        <div className="border-b border-gray-200 mb-6 flex gap-4">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              onClick={() => select(entry.id)}
              aria-selected={entry.id === tab}
              role="tab"
              className={`px-1 pb-2 -mb-px text-sm transition-colors ${
                entry.id === tab
                  ? 'text-gray-900 font-medium border-b-2 border-emerald-600'
                  : 'text-gray-400 hover:text-gray-700 border-b-2 border-transparent'
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>

        {tab === 'benchmark' ? (
          <AssayCorpusPanel />
        ) : (
          <div className="space-y-6">
            <PaperTurnFeed />
            {/* Not decoration: both halves can start a run and both render an estimate card, a
                progress panel and a findings list, so an unbroken page showing two estimate
                cards reads as a bug rather than as two ways in. */}
            <div className="flex items-center gap-3">
              <span className="h-px flex-1 bg-gray-200" />
              <span className="text-xs text-gray-400">or pick from the list</span>
              <span className="h-px flex-1 bg-gray-200" />
            </div>
            <AssayExtractPanel />
          </div>
        )}
      </div>
    </div>
  );
}
