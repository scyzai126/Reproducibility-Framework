---
name: extract-assay-methods
description: Extracts the experimental methods/assays a scientific paper actually used to generate its reported findings into a structured JSON registry (name, aliases, sample type, readouts, supporting evidence, confidence, and role in the paper's argument). Use this whenever the user wants to identify, extract, list, catalog, or summarize the assays, experimental methods, measurement techniques, or lab procedures used in a research paper — even if they don't say "assay" explicitly (e.g. "what techniques did they use to get this result", "pull out the methods from this paper", "build a table of the measurements used across these papers", "does this paper actually run flow cytometry or just cite someone else's"). Also use it as a first step before comparing methods across multiple papers or linking findings back to the technique that produced them.
---

# Extract Assay Methods

Build the inventory of wet-lab measurement techniques a paper used, and trace each of the paper's findings back to the technique that produced it. Both halves matter: papers cite prior work, describe instruments in passing, run quality-control steps, and name computational analyses as if they were measurements — a naive "list every method word you see" extraction pulls in all of that noise. So the inventory comes from Methods, Results and captions are mined for claims rather than for names, and every entry carries the claims attributable to it.

## Getting the paper

**The input is a paper's JATS XML**, normally `data/JAT_XML/<SDY>_<pmid>.xml` (fetched by `scripts/download_jats_xml.py`). Don't read the raw XML markup — parse it first:

```
python .claude/skills/extract-assay-methods/scripts/jats_to_text.py <path/to/paper.xml>
```

That prints the structured text to work from (no API key, no network, no cost). Its shape:

- `## <heading>` blocks, one per section, in canonical reading order: abstract → introduction → results → methods → discussion → anything else. The Methods heading is whatever the paper called it — "Methods", "Materials and Methods", "Experimental Procedures", "Study Design", "Online Methods".
- a `--- Figures ---` block, then a `--- Tables ---` block: one `[Label]` entry each, with `Title:` and `Caption:` lines, plus a `Body:` line carrying the grid for tables.

The parser has already dropped the reference list, supplementary-material containers, Extended Data figures, and publisher boilerplate (acknowledgments, author contributions, competing interests, and the like) — don't spend effort re-filtering those.

**Why this representation, and not the other two.** There are three ways to put a JATS paper in front of a model, and this skill deliberately takes the third:

- **Raw XML markup** — costs roughly 4× the tokens of the parsed text (median 152 KB vs 38 KB across the corpus) for markup you then have to read past. No upside.
- **`claim_abstraction_v5.split_panels`** — groups the paper into figure/table panels, attaching each Results paragraph to the panels it cross-references. Precise about *which* figure a finding belongs to, but it discards every Results paragraph that cites no figure: 24% of Results prose on average across the corpus, and 100% of it on three papers.
- **`parse_jats_xml` (what `jats_to_text.py` runs)** — the whole Results section, every caption, and table bodies, with the boilerplate already stripped.

Coverage wins for this task. An assay named only in an unlinked Results paragraph is unrecoverable if that paragraph never reaches you, whereas a slightly less precise `evidence_location` is still a usable citation. The claim-abstraction pipeline takes the opposite trade-off on purpose — it drafts one claim per panel, so a claim that anchors to no panel has nowhere to live anyway — which is why the two read differently.

**Introduction and Discussion/Conclusions do survive parsing**, so skip them yourself: an assay named only there is background from someone else's study, not something this paper used to generate its own claims. Use the Abstract, Methods, Results, and every figure/table caption and body.

**Two consequences of working from XML rather than the PDF:**

- **A missing Methods section is normal and is not a reason to give up.** Publisher XML often omits supplementary material entirely, so some papers arrive with no Methods section at all. That paper has no inventory to build from and nothing for the classification pass to compare against, so build the inventory from the Results text and figure/table captions directly — they usually name the technique behind each finding. Expect lower precision and say so in your report: paraphrase and computational noise are exactly what the Methods-first order exists to filter out.
- **There are no page images** — you get captions and table bodies, not the panels themselves. See "Linking claims to the inventory" for what that means when citing a figure.

**If there is no XML for the paper** — none on disk, or the parser exits non-zero — say so and fall back to reading the paper's PDF under `data/pdf/` directly (native PDF reading, no tooling needed). Name which source you used when you report results: the two do not see the same material.

## Where assays come from: Methods is the inventory, Results is a recall backstop

These are **not** peer sources, and treating them as if they were is the main way this extraction goes wrong. Measured on one paper:

| source | mentions | what they actually were |
|---|---|---|
| Methods | 9 | the inventory |
| Results + captions | 10 | 6 paraphrases of Methods items, 3 computational analyses, **1 genuinely new assay** |

Results and captions are where the *claims* live, but they name assays in loose paraphrase — "cell death assay" for what Methods calls "cell viability staining using multi-photon microscopy" — and they mix in computational analyses ("DEG profiling", "Von Mises stress model"). Mining them for assay *names* inflates the registry with duplicates and non-assays.

So run two passes:

**Pass 1 — build the inventory from Methods.** Every distinct wet-lab measurement technique described there is an entry. Methods is also the authority on naming (see "Naming each assay"). Find them regardless of how they're named — some are a single clause embedded in another assay's paragraph, with no subheading of their own. Conversely, if one subheading or sentence bundles multiple distinct techniques (e.g. "Hemagglutination Inhibition and Virus-Neutralization Assays"), split them into separate entries: group by distinct technique, not by how the paper organized its headings.

**Pass 2 — sweep Results and captions for candidates, then classify each against the inventory.** Exactly one label per candidate:

- **`SAME_AS_METHODS`** — a paraphrase, abbreviation, or platform alias of an entry you already have. Add the wording to that entry's `aliases`; never create a second entry.
- **`NOT_AN_ASSAY`** — a computational analysis, a sample-prep step, or a QC check (the three exclusions below).
- **`NEW_ASSAY`** — a real wet-lab measurement technique with no counterpart in the inventory. **Only this label is admitted**, with `source: "results"`.

On the measured paper that pass admitted the 1 real addition and rejected the other 9. Do not skip the classification step and merge the two lists directly.

**A technique performed but never concluded from stays in the inventory.** Papers routinely describe more procedures than they draw conclusions from; that entry simply ends up with an empty `claims` array, which records the fact precisely instead of hiding it by dropping the entry.

Three categories are deliberately excluded even though papers mention them constantly, because none of them independently produce a claim-supporting readout:

- **Downstream computational/statistical analyses** — GSEA, GO enrichment, pathway analysis, differential expression testing, clustering, module scoring, etc. These are computations run *on* an assay's output, not their own sample/tissue/readout. Fold any finding they produce back into the wet-lab assay that generated the underlying data (a GSEA-derived pathway finding belongs to "RNA-seq", not "GSEA").
- **Sample-prep / cell-isolation steps** — MACS, FACS sorting for isolation, density-gradient separation, magnetic/column enrichment. These purify a sample for a later measurement; they produce no readout of their own. Register the technique that actually measures the isolated material, not the isolation step.
- **Sample quality/quantity checks** — NanoDrop, BioAnalyzer/TapeStation, Qubit. These gate whether the input material was good enough to proceed; they don't generate an independent finding. Fold any mention into the downstream assay they qualified.

## Linking claims to the inventory

This is the point of the extraction. For reproduction work the question is not *which assays exist* but **which assay produced this claim** — so once the inventory is settled, walk Results and the main-text figure/table captions again and attribute every interpretive or comparative assertion to exactly one inventory entry.

- **Attribute upstream, past the computation.** A claim about DEG counts belongs to the RNA-seq that generated the data, not to the differential-expression analysis that counted them. Same for a GSEA-derived pathway finding, a BTM score, or a clustering result — the wet-lab technique owns the claim.
- **Attribute at figure level** where the claim lives in a figure or table: record the ref, so the claim can be traced back to the panel that reports it.
- **You have captions, not panels.** Working from parsed XML there are no page images, so cite `{"type": "figure", ...}` only when the caption itself reports the finding — never on the assumption that a panel you cannot see shows it. Table `Body:` text is real readable content and can be cited normally.

## Naming each assay

Use the paper's own wording, not a normalized/canonical name — but collapse synonyms, abbreviations, and platform aliases of the *same* measurement into one entry rather than several.

**Names come from Methods.** A Results or caption paraphrase never becomes `name_in_paper`; at most it becomes an alias. "Cell death assay" in a Results sentence is an alias of the Methods entry "cell viability staining using multi-photon microscopy" — never its own entry, and never the name that entry is filed under. The only exception is an assay admitted as `NEW_ASSAY`, which has no Methods wording to defer to.

- Prefer a Methods/Experimental Procedures subsection heading for the name when one exists — it's usually the paper's own canonical name for the technique. When the XML carries no Methods section at all, name the assay from the most specific technique wording in the Results text or the figure/table captions instead. Strip generic framing down to the bare technique name (e.g. "Measurement of anti-Meningococcal antibodies by ELISA" → "ELISA"; "RNA Isolation and Microarray Analysis" → "microarray"). If the paper names a specific instrument/chip/kit (e.g. "Human U133 Plus 2.0 Arrays (Affymetrix)") *and* separately states the technique it runs, use the technique as the name and the product name as an alias — the product is metadata about how the technique was run, not the technique itself. Brand names that *are* the field's standard name for a technique (Luminex, CyTOF, ELISpot, TaqMan) are the exception — keep those as the name.
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
    "source": "methods",
    "claims": [
      {"claim": "IFN-\u03b3+ CD8 T cell frequency rose by day 7 versus baseline.",
       "evidence_location": {"type": "figure", "ref": "Figure 3B"}}
    ],
    "confidence": 0.95,
    "claim_role": "validation"
  },
  "mass cytometry": {
    "name_in_paper": "mass cytometry",
    "aliases": ["CyTOF"],
    "sample_type": "PBMCs",
    "readouts": "cell-type frequencies, signaling markers",
    "source": "methods",
    "claims": [
      {"claim": "Intermediate monocyte frequencies increased 2 days after vaccination versus baseline.",
       "evidence_location": {"type": "text", "section": "Results", "quote": "Intermediate monocyte frequencies increased significantly 2 days after vaccination compared with baseline, as measured by mass cytometry."}}
    ],
    "confidence": 0.95,
    "claim_role": "primary"
  }
}
```

Field definitions:
- **`aliases`** — other exact wordings the paper uses for this same assay/readout; `[]` if none.
- **`sample_type`** — the tissue/specimen the assay was performed on (e.g. whole blood, PBMCs, serum, plasma).
- **`readouts`** — the key measurement(s) it produces (e.g. cell frequencies, gene expression, antibody titers).
- **`source`** — `"methods"` for an inventory entry, `"results"` for one admitted by the backstop pass as `NEW_ASSAY`. Keeps that pass auditable: without it there is no way to see what the classification actually let through.
- **`claims`** — every claim attributed to this assay, each `{"claim": "<short statement of the finding>", "evidence_location": {...}}`. The location is `{"type": "text", "section": "Results", "quote": "<short exact quote>"}` for a sentence, or `{"type": "figure"|"table", "ref": "<number>"}` when the finding appears only there. **`[]` is valid and meaningful**: the paper describes the technique but concludes nothing from it — record that rather than dropping the entry.
- **`confidence`** — float 0–1 for how clearly the paper identifies this as a distinct, specific technique. Near 1.0 for an unambiguous named platform with its own subheading (flow cytometry, ELISA, CyTOF); near 0.0 for vague/generic wording ("commercial immunoassays", "standard laboratory methods") or a passing mention with no methodological detail.
- **`claim_role`** — pick the single most central role if more than one could apply:
  - `"primary"` — a headline finding of the paper rests directly on this assay's output.
  - `"outcome_variable"` — measures the dependent variable/endpoint/response that other assays are correlated with or compared against (antibody titers, neutralization assay, tumor size, survival).
  - `"validation"` — corroborates or confirms a claim generated by another assay (qPCR validating RNA-seq, flow cytometry validating a transcriptomic cell-expansion claim).

Return `{}` only if the paper describes no wet-lab measurement technique at all — don't force an entry just to have output.

## A note on scale

When there are many papers to process, extract each one independently (don't let one paper's assay list influence another's naming) and only merge/compare after each is extracted on its own.

## Optional: mapping to OBI ontology IDs

If the user also wants each assay mapped to its Ontology for Biomedical Investigations (OBI) term (e.g. `OBI:0000916` for flow cytometry), this only works inside the `claim_reprodue_agent` repo — it depends on that repo's local ontology files and OpenAI API access, so it will not work if this skill is used anywhere else. Check first that `apps/api/app/agent/assay_obi_mapper.py` exists relative to the repo root, that that repo's `data/OBI/obi_generic_index.json` and `data/OBI/obi_generic_embeddings.json` are present, and that `OPENAI_API_KEY` is set. If any of those are missing, tell the user OBI mapping isn't available in the current environment and stop there — don't guess at OBI IDs yourself.

If they're all present, write the assay registry to a JSON file, then run:

```
python .claude/skills/extract-assay-methods/scripts/obi_enrich_file.py <path/to/assays.json>
```

This calls the repo's existing three-step matching chain (exact name match → exact normalized-name match → embedding-similarity + LLM pick among the real OBI term list) and writes `<assays>_OBI.json` alongside the input with `obi_id`/`obi_label`/`resource`/`confidence` added to each entry. Report the result to the user, including any assays the script left `unresolved` — don't silently drop them or invent an OBI ID for them yourself.
