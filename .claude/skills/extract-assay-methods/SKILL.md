---
name: extract-assay-methods
description: Extracts the experimental methods/assays a scientific paper actually used to generate its reported findings into a structured JSON registry (name, aliases, sample type, readouts, supporting evidence, confidence, and role in the paper's argument). Use this whenever the user wants to identify, extract, list, catalog, or summarize the assays, experimental methods, measurement techniques, or lab procedures used in a research paper — even if they don't say "assay" explicitly (e.g. "what techniques did they use to get this result", "pull out the methods from this paper", "build a table of the measurements used across these papers", "does this paper actually run flow cytometry or just cite someone else's"). Also use it as a first step before comparing methods across multiple papers or linking findings back to the technique that produced them.
---

# Extract Assay Methods

Identify the assays/experimental methods a paper actually used to generate a specific reported finding — not every technique the paper happens to mention. This distinction is the whole point of the skill: papers cite prior work, describe instruments in passing, and run quality-control steps that never produce an independent scientific claim. A naive "list every method word you see" extraction pulls in all of that noise. This skill only registers a technique when there's a traceable line from that technique to something the paper actually claims in Results.

## Getting the paper

If given a PDF path, read it directly (native PDF reading — no external tooling needed). If given raw/pasted text instead, work from that. Either way, only use:
- Abstract, Methods (may be titled "Methods", "Materials and Methods", "Experimental Procedures", "Study Design", or similar — including "Online Methods"), Results, and all figure/table captions and bodies.

Ignore Introduction, Discussion/Conclusions, References, and any section explicitly labeled Supplementary — assays mentioned only there are background from other studies or extra material, not something this paper used to generate its own claims.

## What counts as a claim-generating assay

An assay qualifies only if it directly produced data behind an interpretive or comparative assertion — an effect, a direction of change, a comparison, a correlation, a dependency — reported in Results, a main-text figure, or a main-text table. A technique named or described only in Methods, with nothing in Results/figures/tables attributable to it, does not qualify: papers routinely describe more procedures in Methods than they end up drawing conclusions from, and registering all of them defeats the purpose of tying methods to actual findings.

Find every qualifying assay regardless of how it's named — some are described in a single clause embedded inside another assay's paragraph, with no subheading of their own. Conversely, if one subheading or sentence bundles multiple distinct techniques (e.g. "Hemagglutination Inhibition and Virus-Neutralization Assays"), split them into separate entries — group by distinct technique, not by how the paper happened to organize its headings.

Three categories are deliberately excluded even though papers mention them constantly, because none of them independently produce a claim-supporting readout:

- **Downstream computational/statistical analyses** — GSEA, GO enrichment, pathway analysis, differential expression testing, clustering, module scoring, etc. These are computations run *on* an assay's output, not their own sample/tissue/readout. Fold any finding they produce back into the wet-lab assay that generated the underlying data (a GSEA-derived pathway finding belongs to "RNA-seq", not "GSEA").
- **Sample-prep / cell-isolation steps** — MACS, FACS sorting for isolation, density-gradient separation, magnetic/column enrichment. These purify a sample for a later measurement; they produce no readout of their own. Register the technique that actually measures the isolated material, not the isolation step.
- **Sample quality/quantity checks** — NanoDrop, BioAnalyzer/TapeStation, Qubit. These gate whether the input material was good enough to proceed; they don't generate an independent finding. Fold any mention into the downstream assay they qualified.

## Naming each assay

Use the paper's own wording, not a normalized/canonical name — but collapse synonyms, abbreviations, and platform aliases of the *same* measurement into one entry rather than several:

- Prefer a Methods/Experimental Procedures subsection heading for the name when one exists — it's usually the paper's own canonical name for the technique. Strip generic framing down to the bare technique name (e.g. "Measurement of anti-Meningococcal antibodies by ELISA" → "ELISA"; "RNA Isolation and Microarray Analysis" → "microarray"). If the paper names a specific instrument/chip/kit (e.g. "Human U133 Plus 2.0 Arrays (Affymetrix)") *and* separately states the technique it runs, use the technique as the name and the product name as an alias — the product is metadata about how the technique was run, not the technique itself. Brand names that *are* the field's standard name for a technique (Luminex, CyTOF, ELISpot, TaqMan) are the exception — keep those as the name.
- **Exception:** if the same platform/instrument appears under two or more headings for genuinely different measurements with different readouts (e.g. a Luminex antibody-titer assay and a separate Luminex cytokine panel), don't strip both down to the same bare platform name — keep enough of each heading's distinguishing wording that the two stay separate entries.
- Treat abbreviation/expansion pairs ("FACS" / "flow cytometry"), platform/descriptive-name pairs ("Luminex" / "bead-based multiplex assay"), and generic result-phrase mentions ("transcriptional profiling" referring to the paper's microarray data) as aliases of one entry, not separate entries. Never create a standalone entry for something that's really just an alias of one already registered.
- Don't merge entries that happen to share a platform name but measure genuinely different things — same-platform, different-readout stays split (see exception above).

## Output

Return a JSON object with one key per deduplicated assay (the key is the same string as `name_in_paper`):

```json
{
  "flow cytometry": {
    "name_in_paper": "flow cytometry",
    "aliases": ["FACS"],
    "sample_type": "PBMCs",
    "readouts": "intracellular cytokine production",
    "evidence_location": {"type": "figure", "ref": "Figure 3B"},
    "confidence": 0.95,
    "claim_role": "validation"
  },
  "mass cytometry": {
    "name_in_paper": "mass cytometry",
    "aliases": ["CyTOF"],
    "sample_type": "PBMCs",
    "readouts": "cell-type frequencies, signaling markers",
    "evidence_location": {"type": "text", "section": "Results", "quote": "Intermediate monocyte frequencies increased significantly 2 days after vaccination compared with baseline, as measured by mass cytometry."},
    "confidence": 0.95,
    "claim_role": "primary"
  }
}
```

Field definitions:
- **`aliases`** — other exact wordings the paper uses for this same assay/readout; `[]` if none.
- **`sample_type`** — the tissue/specimen the assay was performed on (e.g. whole blood, PBMCs, serum, plasma).
- **`readouts`** — the key measurement(s) it produces (e.g. cell frequencies, gene expression, antibody titers).
- **`evidence_location`** — the specific Results/main-text-figure/main-text-table location reporting the claim this assay supports; this is what justifies including it at all, so it can never be a Methods-only or Abstract-only mention. Use `{"type": "text", "section": "Results", "quote": "<short exact quote>"}` for a sentence, or `{"type": "figure"|"table", "ref": "<number>"}` when the finding only appears there. If nothing in Results/figures/tables can be cited here, don't register the assay.
- **`confidence`** — float 0–1 for how clearly the paper identifies this as a distinct, specific technique. Near 1.0 for an unambiguous named platform with its own subheading (flow cytometry, ELISA, CyTOF); near 0.0 for vague/generic wording ("commercial immunoassays", "standard laboratory methods") or a passing mention with no methodological detail.
- **`claim_role`** — pick the single most central role if more than one could apply:
  - `"primary"` — a headline finding of the paper rests directly on this assay's output.
  - `"outcome_variable"` — measures the dependent variable/endpoint/response that other assays are correlated with or compared against (antibody titers, neutralization assay, tumor size, survival).
  - `"validation"` — corroborates or confirms a claim generated by another assay (qPCR validating RNA-seq, flow cytometry validating a transcriptomic cell-expansion claim).

Return `{}` if no qualifying assay is found — don't force an entry just to have output.

## A note on scale

For a paper with many papers to process, or a batch of PDFs, extract each independently (don't let one paper's assay list influence another's naming) and only merge/compare after each is extracted on its own.

## Optional: mapping to OBI ontology IDs

If the user also wants each assay mapped to its Ontology for Biomedical Investigations (OBI) term (e.g. `OBI:0000916` for flow cytometry), this only works inside the `claim_reprodue_agent` repo — it depends on that repo's local ontology files and OpenAI API access, so it will not work if this skill is used anywhere else. Check first that `apps/api/app/agent/assay_obi_mapper.py` exists relative to the repo root, that this skill's `references/obi_assay_terms.json` and `references/obi_assay_embeddings.json` are present, and that `OPENAI_API_KEY` is set. If any of those are missing, tell the user OBI mapping isn't available in the current environment and stop there — don't guess at OBI IDs yourself.

If they're all present, write the assay registry to a JSON file, then run:

```
python .claude/skills/extract-assay-methods/scripts/obi_enrich_file.py <path/to/assays.json>
```

This calls the repo's existing three-step matching chain (exact name match → exact normalized-name match → embedding-similarity + LLM pick among the real OBI term list) and writes `<assays>_OBI.json` alongside the input with `obi_id`/`obi_label`/`resource`/`confidence` added to each entry. Report the result to the user, including any assays the script left `unresolved` — don't silently drop them or invent an OBI ID for them yourself.
