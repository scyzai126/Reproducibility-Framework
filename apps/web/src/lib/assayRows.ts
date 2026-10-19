import type {
  AssayBenchmarkEntry,
  AssayObiEntry,
  AssayObiRow,
  AssayRegistryResponse,
  AssayRunResult,
  ObiResource,
} from './types';

/**
 * One paper's result, in the shape the corpus table renders.
 *
 * Every column the corpus table shows already exists per assay — `assays_OBI.json` carries
 * name_in_paper, standard_technique_name, sample_type, readouts and the four obi_* fields — so this is a
 * mapping rather than a fetch, and the summary above a result cannot disagree with the evidence
 * below it about which assays exist.
 *
 * Pure: no React, no network.
 */

/** `name_in_paper` is a list after round 5 folds wordings together, and a string before it. */
function paperNames(entry: AssayBenchmarkEntry | AssayObiEntry): string[] {
  const names = (entry as AssayBenchmarkEntry).name_in_paper;
  if (Array.isArray(names)) return names;
  return names ? [names] : [];
}

export function toCorpusRows(
  result: AssayRunResult | AssayRegistryResponse | null | undefined,
  pubmedId: string,
  studyAccession: string,
): AssayObiRow[] {
  if (!result) return [];
  // `obi` in preference to `assays`: the OBI mapper fills in technique even where the
  // extractor left it null, which is why the corpus file has good values and a raw registry
  // often does not. When round 4 failed there is no obi at all, and the registry still gives
  // every column but the OBI ones.
  const source = (result.obi ?? result.assays ?? {}) as Record<
    string,
    AssayBenchmarkEntry & AssayObiEntry
  >;
  const study = `${pubmedId}_${studyAccession}`;

  return Object.entries(source).map(([key, entry]) => ({
    study,
    // The key is the OBI label after canonicalisation; the paper's own wording is what a reader
    // recognises, so it leads and the key is the fallback.
    // " / ", as the backend's table rows join them: the ImmPort check caches by this string.
    assay: paperNames(entry).join(' / ') || key,
    standard_technique_name: entry.standard_technique_name ?? '',
    sample_type: entry.sample_type ?? '',
    readouts: entry.readouts ?? '',
    obi_id: entry.obi_id ?? null,
    obi_label: entry.obi_label ?? null,
    // The table colours by resource and renders "unresolved" for a term it never mapped.
    resource: (entry.resource as ObiResource) ?? 'unresolved',
    obi_confidence: entry.obi_confidence ?? null,
  }));
}
