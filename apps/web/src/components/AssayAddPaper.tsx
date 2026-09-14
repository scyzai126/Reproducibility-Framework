'use client';

import { useState } from 'react';
import { addAssayPaper } from '@/lib/api';
import type { AssayPaperSummary } from '@/lib/types';

interface Props {
  onAdded: (paper: AssayPaperSummary) => void;
  disabled?: boolean;
}

/** Cheap shape checks, mirrored from the backend so the rule is visible before it is enforced. */
const PMID_OK = /^\d+$/;
const SDY_OK = /^SDY\d+$/;

/**
 * Add a paper to the corpus by PubMed ID.
 *
 * Free — the backend fetches the paper's JATS XML from PMC, which is two NCBI requests and no
 * model calls. The paper then appears in the picker like any other, with no registry yet, and
 * the ordinary estimate-then-run gate applies to it.
 *
 * Both identifiers are required. The XML is filed as `<SDY>_<pmid>.xml` and the two halves are
 * told apart by the SDY prefix, so a PubMed ID alone cannot name the file.
 */
export default function AssayAddPaper({ onAdded, disabled }: Props) {
  const [pmid, setPmid] = useState('');
  const [sdy, setSdy] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const ready = PMID_OK.test(pmid.trim()) && SDY_OK.test(sdy.trim());

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const result = await addAssayPaper({
        pubmed_id: pmid.trim(),
        study_accession: sdy.trim(),
      });
      setNote(result.message);
      setPmid('');
      setSdy('');
      onAdded(result.paper);
    } catch (err) {
      // The backend's own wording: "not in PMC open access", "abstract-only XML (no <body>)"
      // and "publisher restricts full-text XML download" are three different problems with
      // three different remedies, and flattening them to "failed" would make this control
      // useless exactly when it matters.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <header className="px-4 py-2.5 border-b border-gray-200 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium text-gray-700">Add a paper</h2>
        <span className="text-xs text-gray-400">free · fetches the XML, calls no model</span>
      </header>

      <form onSubmit={submit} className="px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex-1 min-w-[140px]">
            <span className="block text-xs text-gray-500 mb-1">PubMed ID</span>
            <input
              value={pmid}
              onChange={(e) => setPmid(e.target.value)}
              placeholder="34252919"
              inputMode="numeric"
              disabled={disabled || busy}
              className="w-full px-3 py-2 text-sm font-mono border border-gray-200 rounded-lg text-gray-700 placeholder-gray-300 focus:outline-none focus:ring-1 focus:ring-emerald-400 disabled:bg-gray-50"
            />
          </label>
          <label className="flex-1 min-w-[140px]">
            <span className="block text-xs text-gray-500 mb-1">Study accession</span>
            <input
              value={sdy}
              // Normalised as you type, so the stored filename is never a matter of how it
              // happened to be typed.
              onChange={(e) => setSdy(e.target.value.toUpperCase())}
              placeholder="SDY2189"
              disabled={disabled || busy}
              className="w-full px-3 py-2 text-sm font-mono border border-gray-200 rounded-lg text-gray-700 placeholder-gray-300 focus:outline-none focus:ring-1 focus:ring-emerald-400 disabled:bg-gray-50"
            />
          </label>
          <button
            type="submit"
            disabled={!ready || busy || disabled}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? 'Fetching…' : 'Fetch paper'}
          </button>
        </div>

        <p className="text-xs text-gray-400 mt-2 leading-relaxed">
          The paper must be in PubMed Central open access with a full body — abstract-only records
          cannot be used. <span className="text-gray-500">The accession is not checked against the
          paper</span>, only its shape, so a typo files a real paper under the wrong study.
        </p>

        {note && <p className="text-xs text-emerald-700 mt-2">{note}</p>}
        {error && (
          <p className="text-xs text-rose-700 mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
