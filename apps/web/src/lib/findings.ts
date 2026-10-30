import type { AssayRunResult, Finding } from './types';

/**
 * Every reason not to trust an entry, collected from one run.
 *
 * One definition, for the same reason `report_result` in scripts/run_assay_pipeline.py is one
 * definition: CLAUDE.md requires each of these lines be reported rather than summarised, and a
 * second copy of this logic is how one of them quietly stops being collected. It serves both a
 * live run and a registry read off disk, so a finding does not depend on whether you were
 * watching when it happened.
 *
 * Pure — no React, no fetching. The panel that renders this is a flat `.map` over the result.
 */
export function collectFindings(result: AssayRunResult | null | undefined): Finding[] {
  if (!result) return [];
  const findings: Finding[] = [];

  // Entries that broke the extraction contract: a quote that cites no sentence, an alias field
  // that is not a list. Free checks, and the only ones that do not depend on a model's opinion.
  for (const warning of result.contract_warnings ?? []) {
    findings.push({ kind: 'WARNING', subject: '', detail: warning });
  }

  // The verifier's verdicts. The record verdict carries no reason of its own — it is derived
  // from the field verdicts, so the unsupported fields are where the "why" actually lives.
  const verificationResults =
    (result.verification?.results as Record<string, unknown>[] | undefined) ?? [];
  for (const record of verificationResults) {
    const verdict = record.record_verdict as string | undefined;
    if (verdict !== 'REVIEW' && verdict !== 'REJECT') continue;
    const fields = ((record.field_verifications as Record<string, unknown>[] | undefined) ?? [])
      .filter((f) => f.verdict && f.verdict !== 'SUPPORTED')
      .map((f) => ({
        field: String(f.field_name ?? '?'),
        verdict: String(f.verdict),
        reason: String(f.reason ?? 'no reason given'),
      }));
    findings.push({
      kind: verdict,
      subject: String(record.assay_id ?? ''),
      detail: `identity ${record.assay_identity_verdict ?? 'unknown'}`,
      fields,
    });
  }

  // Assays round 3 set aside as never performed. They are gone from the registry, so nothing
  // downstream would mention them again.
  for (const [key, record] of Object.entries(result.dropped ?? {})) {
    findings.push({ kind: 'DROPPED', subject: key, detail: record?.reason ?? 'rejected' });
  }

  // Entries fewer than a majority of the extraction calls found: not delivered, but listed, the
  // way the CLI's MINORITY line lists them -- a rare miss and a Results-only admission both look
  // like this, and a reader decides which.
  for (const [key, record] of Object.entries(
    (result.minority ?? {}) as Record<string, Record<string, unknown>>,
  )) {
    const runs = (record?.runs as string[] | undefined) ?? [];
    const quote = String(
      ((record?.entry as Record<string, unknown> | undefined)?.evidence as Record<string, unknown> | undefined)
        ?.quote ?? '',
    );
    findings.push({
      kind: 'MINORITY',
      subject: key,
      detail: `found by ${runs.length} of ${record?.of ?? '?'} extractions; not delivered — ${quote.slice(0, 120)}`,
    });
  }

  // Two entries on one OBI term that round 5 kept apart because their technique, sample type
  // or readouts differ. A reader decides whether they are one assay.
  const blocked = (result.merges?.blocked as Record<string, unknown>[] | undefined) ?? [];
  for (const record of blocked) {
    findings.push({
      kind: 'REVIEW',
      subject: String(record.member ?? ''),
      detail: `not folded: kept apart from ${record.kept_apart_from} (${record.obi_id ?? 'no term'}): ${record.reason ?? ''}`,
    });
  }

  // Round 5's folds. The OBI term is coarser than the paper's wording, and a fold is exactly
  // where that coarseness shows — so it is reported per fold, not counted.
  const merges = (result.merges?.results as Record<string, unknown>[] | undefined) ?? [];
  for (const record of merges) {
    const folded = (record.folded as string[] | undefined) ?? [];
    findings.push({
      kind: 'MERGED',
      subject: String(record.key ?? ''),
      detail: `${folded.join(', ')} → ${record.key} (${record.obi_id ?? 'no term'})`,
    });
  }

  // A repair that was asked for, paid for, and then failed: the entry keeps exactly the field
  // the verifier objected to. This used to surface only as a count inside the round's actions.
  const corrections = (result.corrections?.results as Record<string, unknown>[] | undefined) ?? [];
  for (const record of corrections) {
    const changes = (record.corrections as Record<string, unknown>[] | undefined) ?? [];
    for (const change of changes) {
      if (change.action !== 'ERROR' && !change.error) continue;
      findings.push({
        kind: 'CORRECT FAILED',
        subject: `${record.assay_id ?? '?'} / ${change.field ?? '?'}`,
        detail: String(change.error ?? 'no reason given'),
      });
    }
  }

  // An assay OBI has no term for is a gap in the vocabulary or a name too vague to map, and
  // only reading the name tells you which — so the names are listed, not totalled.
  const obiRound = (result.rounds?.obi ?? {}) as Record<string, unknown>;
  if (obiRound.source === 'failed') {
    findings.push({
      kind: 'OBI FAILED',
      subject: '',
      detail:
        'mapping did not run; rounds 1-3 are intact. Re-run: scripts/run_assay_merge.py --map <registry_dir>',
    });
  }
  for (const key of (obiRound.unresolved as string[] | undefined) ?? []) {
    findings.push({ kind: 'UNMAPPED', subject: key, detail: 'no OBI term' });
  }

  // The free deterministic checks. A registry that was fine when written can stop matching if
  // the paper's XML is re-fetched, so these are recomputed on every read.
  const perAssay = (result.quote_check?.per_assay as Record<string, { status?: string }> | undefined) ?? {};
  for (const [key, check] of Object.entries(perAssay)) {
    if (check?.status === 'found') continue;
    findings.push({
      kind: 'QUOTE MISSING',
      subject: key,
      detail: check?.status === 'no_quote'
        ? 'the entry cites no quote'
        : 'the quote is not verbatim in the sentences it cites',
    });
  }
  const perSource = (result.quote_check?.per_assay_source as Record<string, { status?: string }> | undefined) ?? {};
  for (const [key, check] of Object.entries(perSource)) {
    if (check?.status !== 'mismatch') continue;
    findings.push({
      kind: 'SOURCE MISMATCH',
      subject: key,
      detail: 'the cited sentences do not sit in the section `source` names',
    });
  }

  return findings;
}

/** Fixed order, so the panel's colours never shift when the data changes. */
export const FINDING_ORDER: Finding['kind'][] = [
  'REJECT',
  'DROPPED',
  'MINORITY',
  'CORRECT FAILED',
  'OBI FAILED',
  'REVIEW',
  'WARNING',
  'UNMAPPED',
  'QUOTE MISSING',
  'SOURCE MISMATCH',
  'MERGED',
];

/**
 * Amber warns, rose means something was lost, gray is information.
 *
 * A fold is gray on purpose: round 5 merging two write-ups of one technique is the pipeline
 * working, not a fault, and colouring it like a failure would train the eye to ignore the rows
 * that are.
 */
export const FINDING_TONE: Record<Finding['kind'], string> = {
  REJECT: 'bg-rose-50 text-rose-800 border-rose-200',
  DROPPED: 'bg-rose-50 text-rose-800 border-rose-200',
  'CORRECT FAILED': 'bg-rose-50 text-rose-800 border-rose-200',
  'OBI FAILED': 'bg-rose-50 text-rose-800 border-rose-200',
  REVIEW: 'bg-amber-50 text-amber-800 border-amber-200',
  WARNING: 'bg-amber-50 text-amber-800 border-amber-200',
  UNMAPPED: 'bg-amber-50 text-amber-800 border-amber-200',
  'QUOTE MISSING': 'bg-amber-50 text-amber-800 border-amber-200',
  'SOURCE MISMATCH': 'bg-amber-50 text-amber-800 border-amber-200',
  MINORITY: 'bg-amber-50 text-amber-800 border-amber-200',
  MERGED: 'bg-gray-100 text-gray-700 border-gray-200',
};
