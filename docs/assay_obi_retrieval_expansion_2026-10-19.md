# OBI retrieval: should exact-first stay, and what widening the candidate list buys (2026-10-19)

*Follows `docs/assay_obi_mapping_review.md` and `docs/assay_obi_remap_2026-10-19.md`. No paper
run was made for this; every number below comes from files already on disk.*

## The question

Should the mapper keep "exact match first, embedding retrieval later", and would a lexical (BM25)
pool or the OBI neighbours of the top retrieved terms find curated terms that retrieval misses?

## The chain as it stands

Exact match answers outright only on a leaf term (2 of 42 entries in today's six-paper re-map;
10 of 151 corpus-wide). On a term with children it is *pinned* into the picker's list with those
children. So in practice the chain is "retrieve and pick, with the verbatim hit guaranteed a
seat" — the right shape, given that an exact hit answering outright on the technique name once
produced 33 of 52 benchmark disagreements by returning the parent term.

## Measurement (free): is retrieval the bottleneck?

`scripts/eval_obi_retrieval.py` joins `data/benchmark_assay/comparison/benchmark_vs_stability.json`
(curated term per matched row) to the candidate lines every pick stored in `assays_raw.json`, and
simulates the two expansions from `obi_generic_index.json` and `obi.obo`.

| | rows |
|---|---|
| matched rows with a curated OBI id | 144 |
| curator's term **among the 20 candidates shown** | **140 (97.2%)** |
| absent | 4 |
| …absent, OBI neighbours of the top-3 retrieved would add it | **1** — SDY1260 `anti-Diphtheria IgG by Luminex`: curated `antibody detection by cytometric bead array assay`, a child of our `cytometric bead array assay` pick |
| …absent, BM25 top-5 over `label \| synonyms` would add it | **0** |
| …absent, neither | 3 — SDY1328 multiplex ELISA → CBA (we left it unmapped), SDY1328 complete blood count → `hematology assay`, SDY1655 cytokine array → CBA (we chose `multiplex bead-based protein state immunoassay`) |
| curator left the term blank | 5, not scored |

**Retrieval is not the bottleneck.** 14 of the 18 scored disagreements had the curator's term on
the list and the picker chose otherwise; those are granularity and policy disputes (see the
adjudication doc), not retrieval misses. A first quick count had reported 139/144 and 2 recoverable
misses; it was wrong because its regex read only `OBI:` ids and the SDY1294 curated term is a
`CHMO:` id that was on the list. The script accepts any `PREFIX:digits` id.

## Decision

- **Idea 2, structural neighbours — implemented.** It generalises a mechanism the mapper already
  had for exact hits, costs no API call, and targets the dominant residual error (parent chosen
  where a child fit). Measured gain on this benchmark: 1 row's term now reaches the picker.
- **Idea 1, BM25 lexical pool — not implemented.** 0 of 4 recovered. The eval script keeps the
  simulation behind `--lexical` so it can be re-checked on more papers.
- **Exact-first stays**, as a pin. The only remaining bypass is a leaf exact hit, which never
  consults sample type or readouts (e.g. a paper calling a Luminex panel "ELISA"). Not changed
  today; it would cost 2–3 calls on ~5% of entries to always run the picker.

## What changed (`apps/api/app/agent/assay_obi_mapper.py`, `prompts/resolver_obi_assay.txt`)

- `_index_parents(terms_path)`: inverse of `_index_children`, same `obi.obo` parse.
- `NEIGHBOUR_TOP = 3`, `MAX_NEIGHBOUR_CHILDREN = 8`.
- `_with_neighbours(candidates)`: after `_merge_candidates` and `_with_pinned`, appends the direct
  parents and children of the first three *retrieved* candidates (pinned rows are not anchors;
  they bring their own children). A term with more than 8 index children contributes no
  children (`analyte assay` 79, `cytometry assay` 45); parents are always added. Rows carry
  `similarity: None`, `pin: child_of | parent_of`, `of: <anchor's 1-based number>`; nothing
  already listed is repeated.
  Simulated on the 167 stored candidate lists of the stability run, the capped expansion adds
  2.4 rows per entry on average (max 8; 24 entries gain none; the cap held back 11 anchors'
  children), so the picker's list grows from 20 to ~22 lines.
- `_candidate_line` marks them `child of candidate N` / `parent of candidate N`.
- Attribution: a pick only the expansion could reach is `resource: embedding_llm_neighbour`
  (billed like `embedding_llm`); the `embedding_llm_normalized` attribution is unchanged.
- Prompt: the candidate preamble explains the two marks; rule 8 says to treat them under rule 2
  like retrieved terms — child on specific evidence, parent when the anchor is more specific than
  the record warrants, the retrieved term otherwise.
- `scripts/eval_obi_retrieval.py`: the measurement, reusable before and after any retrieval
  change. `--show-misses` lists the rows; `--lexical` adds the BM25 simulation.

Tests: 251 passed across the mapper, service, merge-script, progress and merger files
(`apps/api/tests/`). One existing test that asserted the exact candidate set now asserts the
retrieved terms lead the list and the rest ride along.

## Not validated yet (paid)

The picker has not been run against the widened list. The one row it can change is SDY1260's
Luminex IgG entry; the six re-mapped papers from earlier today would serve as controls. A re-map
of SDY1260 alone is 6 entries, ~15 calls (`run_assay_merge.py <dir> --map-all --judge`). Whether
the longer list shifts any of the 140 already-correct picks is the other thing only a run shows.
