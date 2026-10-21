# Assay → OBI mapping: flow walkthrough and review

*Written 2026-10-19 against `data/31paper_assays/assay_result_v1/` and
`data/benchmark_assay/comparison/benchmark_vs_agent.json` (benchmark v4, same date). No code, prompt
or data was changed for this review.*

Round 4 of the assay pipeline (`scripts/run_assay_pipeline.py` → `assay_service.assay_report`) maps each
extracted assay to an OBI term. The mapper is `apps/api/app/agent/assay_obi_mapper.py`; the pick prompt
is `apps/api/app/prompts/resolver_obi_assay.txt`; the vocabulary is built by
`scripts/prune_obi_domain.py` and embedded by `scripts/build_obi_embeddings.py` (see
`data/OBI/README.md`).

## The flow, per registry entry

**Inputs** (from the corrected registry after rounds 1–3): `name_in_paper[0]`, the other wordings +
`aliases`, `standard_technique_name`, `sample_type`, `readouts`.

**Vocabulary**: `obi.obo` 5218 terms → assay branch 1794 → drop compositional "measuring/detecting"
labels 1249 → drop out-of-scope subtrees → **701 terms** (`obi_generic_index.json`, with `definition`
and `n_descendants`). Each term is embedded as `label | synonyms | definition` with
`text-embedding-3-small`.

1. **Step 1 — exact lookup (free).** `name_in_paper[0]` lowercased (and with trailing " assay"
   stripped) against every label and synonym (`_build_lookup`). Only the paper's own name is a key;
   `standard_technique_name` and aliases are not (removed 2026-10-02: the technique is the parent
   label, and an exact hit never reached the picker that could choose the child).
   - Hit on a term with **no children in the index** → answer outright: `resource=exact_original`,
     `obi_confidence="high"`, `obi_granularity=None`. (ELISA, ELISpot: their children were pruned.)
   - Hit on a term **with children** → not an answer; the hit + its direct children (+ grandchildren
     for the two RNA-seq family ids) are *pinned* into step 2 (`_pinned_candidates`).
2. **Step 2 — retrieve + pick (2–3 paid calls).**
   - Query A: `name | alias1 | alias2 …` (`_paper_query`). Query B: `standard_technique_name`, only
     if it differs from the name. Each → top-20 by cosine (`_top_k_candidates`), restricted to index ids.
   - `_merge_candidates`: the first 14 of pool A are guaranteed; pool B fills to 20; dedupe on the
     better score; sort by score. Pinned terms are then prepended with `similarity=None`.
   - `build_pick_prompt` renders the resolver prompt: assay name, aliases, technique, sample type,
     readouts, and one numbered line per candidate (id | label | ≤4 synonyms | definition ≤300 chars
     | descendants | "exact name match"/"child of…" marks | similarity). Ten rules: definition first;
     specificity when warranted; array disambiguation; prefer BROAD to none; exact-match/child rule;
     cytometer-read functional assays; multiplex immunoassays.
   - Reply is strictly `N EXACT|BROAD` or `none` (`parse_pick_reply`); anything else → none.
   - Result: `obi_id`, `obi_label`, `resource` (`embedding_llm`; `embedding_llm_normalized` when only
     query B reached the chosen term; `exact_original_llm` when a pin was in play),
     `obi_confidence` = the chosen candidate's cosine (or "high" if it was the pinned exact hit),
     `obi_granularity` = EXACT/BROAD.
   - Floor: if a pinned exact hit exists and the picker says none, the exact hit stands.
3. **Outputs.** `enrich_assays_with_obi` writes `assays_OBI.json` (one failed lookup →
   `resource=error`, the rest continue). `assays_raw.json["obi"][key]` keeps the candidate lines and
   the reply, so a wrong term can be classified as a retrieval miss or a picker miss from disk.
4. **Round 5 consumes it.** Registry re-keyed by `obi_label`; entries sharing a label are fold
   candidates whatever their granularity (an EXACT-only rule was tried and withdrawn the same
   day, commit 4c1726e, because the label flips between runs) and fold only when the fold judge
   calls them one measurement. Unmapped and identity-reviewed entries stand alone under their
   paper name (`assay_merger.canonical_groups`). `obi_granularity` is therefore diagnostic only.

## Evidence

Resources across 151 mapped entries in the 31-paper corpus:

| resource | n |
|---|---|
| exact_original (free) | 10 |
| exact_original_llm (pinned, paid) | 28 |
| embedding_llm | 101 |
| embedding_llm_normalized | 9 |
| unresolved | 2 |
| manual_review (hand-edited file) | 1 |

Granularity: EXACT 127, BROAD 12, None 12 (= the 10 free + 2 unresolved).

Benchmark v4 vs agent: 155 curator rows, 149 matched, **136 same OBI term (91%)**,
3 MATCH_GRANULARITY, 5 MATCH_OBI_CONFLICT, 5 MATCH_OBI_UNMAPPED, 6 missed, 3 extra.

## Findings

1. **What remains is almost all granularity, and the curators are split on the same families.**
   - SDY1393: curator `bulk RNA-seq assay`, ours `RNA-seq assay`; SDY1373: curator
     `polyA-selected RNA sequencing assay`, ours `bulk RNA-seq assay`.
   - SDY1640: curator `analyte detection by flow based bead assay`, ours `cytometric bead array
     assay` (prompt rule 10 says parent unless beads were read on a flow cytometer).
   - SDY80: curator `96-well neutralization assay`, ours `serum neutralization of viral infectivity assay`.
   - SDY1289: curator `real time PCR`, ours `real time RT-PCR` (extract prompt: cDNA template → RT).

   The prompt's rule 2 ("most specific … only when warranted") cannot be scored per row without a
   written per-family granularity policy agreed with the curators.
   `data/benchmark_assay/comparison/same_name_different_obi.json` already documents the benchmark's
   own inconsistency. More prompt rules will not close this gap.

2. **Three of the five CONFLICT rows are arguably the agent being right by the prompt's own rules.**
   SDY1373 multiplex cytokines → curator `multiplex bead-based protein state immunoassay` (rule 10
   forbids this for concentration panels); SDY1294 ADCC → curator `flow cytometry assay`, ours
   `cell-cell killing assay`; SDY984 metabolomics → curator `LC-MS assay`, ours `metabolomics by
   mass spectrometry assay`. These are curator-review items, not code.

3. **Four of five OBI_UNMAPPED rows are the curator leaving the term blank while ours mapped**
   (SBA / serum bactericidal → `bacterial neutralization assay`, lateral flow serology →
   `single-value binding of antibody with reporter to antigen assay`). Only one is unmapped on
   both sides (CFU counts).

4. **BROAD is dominated by flow cytometry, for a known vocabulary reason.** 7 of 12 BROAD entries sit
   on `flow cytometry assay`; six are ICS-type (OBI's ICS term is obsolete, see `data/OBI/README.md`).
   Two plain "Flow cytometry" phenotyping panels (SDY984, SDY1655) were also marked BROAD although
   rule 9 says phenotyping stays on `flow cytometry assay` — the granularity definition ("correct
   category but more general") pulls the other way on a mixed panel. Since granularity no longer
   gates folding (4c1726e), this has no effect on the registry; it only matters when the field is
   read during adjudication.

5. **The free step rarely fires: 10 of 151 entries.** The child-pinning rule moved 28 exact hits into
   the paid step, deliberately. Docstrings still describe exact match as "the only free step" as if it
   were common. Each paid entry is 2–3 calls (embedding ×1–2 + pick). Not a defect, worth knowing.

6. **Two unresolved entries are vocabulary gaps, correctly reported UNMAPPED**: `IFN-γ Capture Assay`
   (no cytokine-secretion/capture term in OBI) and CFU counting (no colony-count term in `obi.obo`).
   One extraction-side wrinkle reaches the mapper here: SDY1596's `name_in_paper` is
   `culturable microbial count assay`, an ontology-style phrase the paper never wrote (aliases are
   "CFU counts"); the verifier did not flag it. The paper-wording query was therefore not paper
   wording.

7. **Small hygiene items.** `EMBED_MODEL` is declared in both `assay_obi_mapper.py` and
   `scripts/build_obi_embeddings.py` with no test tying them (a drift silently invalidates every
   vector). `obi_confidence` is a cosine, not a confidence, and differs by resource — already
   documented, still shown in the table/UI. `manual_review` is a hand-written resource in one result
   file and is billed as paid by `obi_calls`.

## Open items (none started)

- **A. Granularity policy with curators.** One table, per family (RNA-seq, PCR, bead multiplex,
  neutralization, flow/ICS): which depth is "the" term. Then benchmark v5 and prompt rules 2/8/9/10
  follow it, instead of each encoding a different answer.
- **B. Curator-review list.** Emit the 3 CONFLICT + 4 one-sided-UNMAPPED rows as a Markdown
  review sheet (`scripts/compare_assay_benchmark_v2.py` already has the rows).
- **C. Rule 9 clarification.** Make "phenotyping on `flow cytometry assay` is EXACT; mark BROAD only
  when readouts describe a function with no candidate term" explicit, with a test on
  `build_pick_prompt`. No fold risk now that granularity is diagnostic only.
- **D. Hygiene.** One test asserting the two `EMBED_MODEL` constants agree; add `manual_review` to
  the free-resource tuple or strip it from the result file.
- **E. Extraction guard.** A `name_in_paper` that is not found verbatim in the paper (SDY1596 case)
  should be flagged by the verifier's identity check; investigate why it was not.

## Code-level review and fixes (2026-10-19, later the same day)

A second pass read the mapper itself rather than its output. Evidence came from read-only scans
of the 31 `assays_raw.json` traces under `data/31paper_assays/stability/` (167 pick replies) and
of `obi_generic_index.json`. The mapping is accurate; what was weak is reproducibility and
diagnostics. Fixed in one commit, unit-tested, no paper run:

| # | Problem | Evidence | Fix |
|---|---|---|---|
| 1 | The pick call set `temperature=0` but no `seed`; extraction sets `seed=EXTRACTION_SEED`. | The re-run moved the OBI term on 9 of 31 papers with no extraction change. | `_llm_pick` and the fold judge pass the extraction seed. Best-effort on the provider's side; the effect is only measurable with a paid re-run. |
| 2 | A reply the strict parser refused (`3 EXACT.`, `3, EXACT`, `candidate 3`) became "none" → `unresolved`, indistinguishable from a vocabulary gap. | 0 of 167 replies today, so no harm yet; a model change would surface it as UNMAPPED with only a log line. | Punctuation around the granularity now parses. A reply naming no listed candidate raises `PickReplyError`, recorded as `resource: error` + `obi_error` (billed, listed under `errors`, printed `OBI ERROR`). On a pinned exact hit the hit still stands. |
| 3 | `obi_granularity` is written and read by nothing since 4c1726e; docstrings implied it gated folding. | grep over `apps/` and `scripts/`. | Documented as diagnostic only in the mapper; kept because adjudication starts from it. |
| 4 | Round 4 mapped entries serially on one worker thread (2–3 blocking calls each) and emitted only "running" until it returned. | Rounds 3 and 5 gather their calls. | `enrich_assays_with_obi` maps 4 entries at a time (`OBI_WORKERS`), returns in registry order, and fires `on_done(key, done, total)`; the service relays it as `round=obi, state=running, done=n, total=N, item=key`, like round 2. Each worker runs in a copy of the caller's context so the trace still receives the replies. |
| 5 | `run_assay_merge.py --map` re-mapped and re-paid every entry even when one carried `resource: error`. | Script read. | With a mapping on disk `--map` re-maps only entries whose lookup failed or that the mapping lacks; `--map-all` maps everything; `--map --dry-run` counts accordingly. |
| 6 | `_build_lookup` let a synonym beat a label on a shared key; index order decided. | 4 colliding keys: `histopathology`, `lps`, `at-iii`, `at-iii assay`. | Labels are indexed before synonyms; a test pins the four so an OBI bump that adds one is noticed. |
| 7 | `_term_details()` ignored `terms_path`; `_top_k_candidates`' docstring cited a deleted file. | Code read. | Both take/describe the vocabulary actually searched. |

**Deliberately not changed.** Abstention is almost off: rule 6 ("prefer BROAD to none") plus no
similarity threshold gave 4 `none` in 167 picks, so a junk name nearly always gets a term. The two
corpus UNMAPPED entries were genuine vocabulary gaps, so this is working as intended, and any
change needs a benchmark run to judge. Also observational: the picker chose candidate #1 in 108 of
167 (similarity order is shown despite the prompt saying it is not evidence), and 7 picks came from
rank 11–21, which is what justifies `TOP_K=20`. Pinned lists are uncapped ("RNA Sequencing" shows
26 pinned + 20 retrieved lines); accepted design.
