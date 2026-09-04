---
name: extract-assay-methods
description: Extracts the experimental methods/assays a scientific paper actually used to generate its reported findings into a structured JSON registry (name, aliases, platform/instrument, sample type, readouts, and the supporting evidence that the paper performed it). Use this whenever the user wants to identify, extract, list, catalog, or summarize the assays, experimental methods, measurement techniques, or lab procedures used in a research paper — even if they don't say "assay" explicitly (e.g. "what techniques did they use to get this result", "pull out the methods from this paper", "build a table of the measurements used across these papers", "does this paper actually run flow cytometry or just cite someone else's"). Also use it as a first step before comparing methods across multiple papers or linking findings back to the technique that produced them. Runs the extraction as a single scripted LLM call rather than reading the paper yourself.
---

# Extract Assay Methods

Build the inventory of wet-lab measurement techniques a paper actually used.

**The extraction rules are not in this file.** They live in
`apps/api/app/prompts/extract_assays.txt`, which is the prompt the extraction call sends —
what counts as an entry, how entries are named, when Results may add one, and what each field
may say. That file is the single source of truth, for the same reason `claim_types.txt` is one
file shared by the extractor and the judge that audits it: two copies of a rule drift, and the
drift is invisible until something downstream disagrees with itself.

So this file tells you how to *run* the extraction. When you need to know what a rule says,
read the prompt.

**This skill does not attribute claims to assays.** The claim pipeline already does that from
the other direction — `extract_claims_pdf.txt` emits an `assay` object per claim and
`claim_abstraction_v5` publishes `assay_method_in_paper`. Produce the inventory; leave the
claims to the claims.

## Extract

```
python scripts/run_assay_extract.py <paper.xml> data/claims/assay_registries/<pmid>_<SDY>
```

One LLM call for the whole paper. Add `--dry-run` to see the paper size and title, and whether
an existing registry would be overwritten, without calling anything.

The input is JATS XML, normally `data/JAT_XML/<SDY>_<pmid>.xml`. If it isn't there, fetch it:

```
python scripts/download_jats_xml.py
```

**Note the two directory schemes run in opposite orders** — `<pmid>_<SDY>` for the registry
directory, `<SDY>_<pmid>` for the XML file. This trips people up; `run_assay_verify.locate_xml`
exists to paper over it.

The script writes `assays.json` into the directory you name — one canonical location per
paper, overwritten in place on a re-run. Without that convention the same paper accumulates
divergent copies under several directory schemes, which has already happened:
`19047440_SDY1289` has three, and two of them disagree (7 entries vs 9).

**Report every `WARNING` line the script prints.** They flag entries that broke the output
contract — no evidence quote, no sentence ids, a `source` value outside the vocabulary — and
each one makes that entry unusable downstream. Do not skim past them because the entry count
looked reasonable.

## Then check the quotes — free

```
python scripts/run_assay_verify.py data/claims/assay_registries/<pmid>_<SDY> --check-quotes
```

No API call. It confirms each entry's evidence quote really appears in the sentences its
`sentence_ids` cite. A `MISSING` means the model reconstructed the quote instead of copying
it, which is a defect to resolve before spending anything further. Always run this after an
extraction.

## Inspecting the paper yourself

To read the parsed text — to answer a question about the paper, or to check something the
extraction returned:

```
python .claude/skills/extract-assay-methods/scripts/jats_to_text.py <path/to/paper.xml>
```

No API key, no network, no cost. Sections in canonical order (abstract → introduction →
results → methods → discussion → other), then `--- Figures ---` and `--- Tables ---` blocks.
**Every sentence carries an `[S<n>]` marker**, numbered continuously across the document;
headings and `[Figure 1]` labels do not. Those markers are the ids `evidence.sentence_ids`
cites, and they are what makes an extracted value checkable against a specific sentence. The
reference list, supplementary containers, and publisher boilerplate are already stripped.

## When the script cannot run

Two cases, and in both the instruction is the same: **read
`apps/api/app/prompts/extract_assays.txt` and apply those rules yourself** to the paper text.
The prompt is the rulebook, so the hand path and the scripted path follow identical rules.

- **No JATS XML for the paper.** The script requires it — the parse is what produces the
  `[S<n>]` markers. Fall back to reading the PDF under `data/pdf/` directly (native PDF
  reading, no tooling needed). Say which source you used when you report: the two do not see
  the same material, and a PDF read cannot cite sentence ids.
- **Running outside the `claim_reprodue_agent` repo, or no `OPENAI_API_KEY`.** The script
  imports `apps/api/app/agent/assay_extractor.py`, as the OBI and verification steps below
  likewise depend on this repo.

Also worth knowing: publisher XML sometimes omits the Methods section entirely — 1 of the 30
papers in `data/JAT_XML` (`SDY1669_32788292`). The prompt handles it by building from Results
and captions, but precision drops, so say so when reporting that paper.

## Output shape

Seven fields per entry, keyed by `name_in_paper`. This is orientation only — the prompt
defines what each field may contain:

```json
{
  "flow cytometry": {
    "name_in_paper": "flow cytometry",
    "aliases": ["FACS"],
    "platform": "BD LSRFortessa",
    "sample_type": "PBMCs",
    "readouts": "intracellular cytokine production",
    "source": "methods",
    "evidence": {"section": "Materials and Methods", "sentence_ids": ["S318"],
                 "quote": "PBMCs were stimulated for 6 h and stained for intracellular IFN-γ prior to acquisition on a BD LSRFortessa."}
  }
}
```

## Many papers at once

Extract each paper independently — one script invocation each — so one paper's assay list
cannot influence another's naming. Merge or compare only after each is extracted on its own.

## Optional: mapping to OBI ontology IDs

If the user also wants each assay mapped to its Ontology for Biomedical Investigations term
(e.g. `OBI:0000916` for flow cytometry):

```
python .claude/skills/extract-assay-methods/scripts/obi_enrich_file.py <path/to/assays.json>
```

This needs `apps/api/app/agent/assay_obi_mapper.py`, this repo's `data/OBI/obi_generic_index.json`
and `data/OBI/obi_generic_embeddings.json`, and `OPENAI_API_KEY`. If any are missing, say OBI
mapping isn't available here and stop — don't guess at OBI IDs yourself.

It writes `<assays>_OBI.json` alongside the input, adding `obi_id`/`obi_label`/`resource`/
`obi_confidence`; the seven fields pass through untouched. **Report any assay left
`unresolved`** rather than dropping it silently.

## Optional: independently verifying the registry

A registry is unverified: a `platform` inferred from what a technique usually runs on reads
exactly like one copied out of Methods. A separate pass re-reads the paper with a fresh model
that has none of the extraction's reasoning in view.

```
python scripts/run_assay_verify.py <registry_dir>
```

One call per assay, each carrying the whole paper — the whole paper, because an assay
"mentioned only in the Introduction" cannot be recognised as such by a reader shown only
Methods. It writes `assays_verification.json` and **never modifies the registry**: verification
only, no corrections.

**Report every `REVIEW` and `REJECT` record with its reason**, rather than accepting the
registry because a summary line looked healthy.

### Repairing what verification flagged

```
python scripts/run_assay_correct.py <registry_dir> --dry-run   # free; shows the bill
python scripts/run_assay_correct.py <registry_dir>             # 1 call per flagged FIELD
```

Blind re-extraction: the correcting model is shown the paper and a question, never the
disputed value or the verdict — being shown the rejected string anchors it into editing that
string rather than reading the paper. Each flagged field comes back REAFFIRMED (the verifier
was wrong), REPLACED (the extraction was wrong), or CLEARED (the paper does not state it).

Results go to `assays_corrected.json` plus `assays_corrections.json`. **Nothing downstream
reads them** until promoted, which is a separate deliberate step:

```
python scripts/run_assay_correct.py <registry_dir> --promote
```

That installs the corrected registry as `assays.json` and keeps the pre-correction version as
`assays_precorrection.json`. Review the corrections before promoting; do not promote on the
user's behalf without showing them what changed.
