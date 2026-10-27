# OBI assay vocabularies

The assay vocabulary and vectors used by `apps/api/app/agent/assay_obi_mapper.py`.
**`obi_assay_pruned_index.json` is the live vocabulary the mapper searches.** It is a *derived* file:
`scripts/prune_obi_domain.py` takes the assay branch of `obi.obo`, applies two prunes, and adds
each term's `definition` and `n_descendants` — one command, from `obi.obo` alone.

| file | terms | size | role |
|---|---|---|---|
| `obi_assay_pruned_index.json` | 701 | 212 KB | **Live vocabulary.** Exact matching + the candidate pool for semantic search. Derived — do not hand-edit. |
| `obi_assay_pruned_embeddings.json` | 701 | 28 MB | **Live vectors.** `text-embedding-3-small`, 1536-dim, one row per index term — see *The vectors*. **Not on disk since 2026-10-27** (deleted ahead of the full-vocabulary experiment; the former `obi_generic_embeddings.json` is in git history). Rebuild with `scripts/build_obi_embeddings.py`; the full list's vectors go to `obi_assay_full_embeddings.json`. |
| `obi_assay_full_index.json` | 1794 | 0.7 MB | **Unpruned assay branch.** Every `is_a` descendant of `assay`, in exactly the index's format (same six fields, same helpers), so `run_obi_map.py --terms` can take it for a full-vocabulary experiment. Not on the serving path. Derived by `scripts/build_obi_assay_terms.py` — do not hand-edit. |
| `obi.obo` | 5218 | 1.5 MB | Upstream OBI release 2026-05-08. The only source: the index and the 1794-term assay branch are both derived from it. Off the serving path, but required to rebuild. |
| `README.md` | — | — | This file: the record of what each prune removes and why. |

```
obi.obo  5218  ──[ assay branch ]──▶  1794  ──[ measuring/detecting filter ]──▶  1249  ──[ tier A-I subtrees ]──▶  701
```

The assay branch is every `is_a` descendant of `OBI:0000070 assay`, in `obi.obo` order. Each index
entry is:

```json
{
  "id": "OBI:0600031",
  "label": "enzyme-linked immunospot assay",
  "synonyms": ["ELISPOT assay"],
  "is_a": ["OBI:0001977", "OBI:0003587"],
  "definition": "A cytometry assay in which cells are cultured on a surface coated with ...",
  "n_descendants": 43
}
```

`is_a` is the stanza's parent ids in OBO order, from the **full** `obi.obo`: a parent can be
`assay` itself or a term the prune removed, so an edge need not have both ends in the index.
`definition` is the OBO `def:` text (all 701 have one). `n_descendants` counts distinct `is_a`
descendants in the **full** `obi.obo`, self excluded — not within the index. ELISPOT's 43 are all
compositional terms the prune removed, so it is broad in OBI and a leaf here.

The removed terms are **not** committed — this README and the root list in
`scripts/prune_obi_domain.py` are the record, and `--show-dropped` reprints them on demand.

## Why the compositional prune

The dropped 546 are IEDB-style **compositional** labels — *"… assay measuring epitope specific
X production by Y cells"* — plus IEDB MHC-binding constructs like *"radioactivity detection
assay measuring half maximal inhibitory concentration [IC50] …"*. Everything matching
`/\b(measuring|detecting)\b/` is removed, except the ids pinned in `_COMPOSITIONAL_KEEP`
(`app/agent/assay_obi_mapper.py`) — today only `OBI:1110179`, see *Known gap* — so 545 go.

`detecting` was added on 2026-09-09, taking the filter from 532 terms to 546. Matching only
`measuring` had left four of the same construct in the index, and one of them —
`OBI:1110207 assay detecting IFN-gamma production` — was chosen **four times** in a 30-paper
mapping run, twice in place of `OBI:0600031` for entries the papers called an ELISpot: the exact
failure this prune exists to prevent, surviving it on a verb.

They are ~30% of the assay branch and they outrank the plain family terms in similarity search:
43 of the 45 ELISPOT-ish labels are compositional, so an "IFN-γ ELISPOT" query buried
`OBI:0600031 enzyme-linked immunospot assay` beneath cytokine-specific variants. This was
producing wrong mappings in committed output until 2026-08-19.

## Why the domain prune

A second pass on 2026-09-08 cut the index from 1262 to 703, and pinning X-ray crystallography on
2026-09-09 brought it to 704; widening the compositional filter the same day left **700** — 548
removed by this stage. Pinning the MHC tetramer term on 2026-10-13 made it **701**. Same
failure mode, different source: the assay branch carries whole domains that never appear in an
immunology or biomedical paper, and they sit close enough in embedding space to crowd out the
terms we want. There is **no similarity threshold** in the mapper — `_top_k_candidates` returns
the top 10 unconditionally, however low the scores, and abstention is prompt-side only — so
removing a decoy from the pool is the only structural defence.

| tier | subtree root | terms | domain |
|---|---|---|---|
| A | `OBI:21xxxxx` band, specimen/instrument/panel-qualified | 333 | hospital analyzer panels |
| B | `OBI:0002695` insecticide resistance assay | 33 | entomology |
| C | `OBI:0002441` physical examination of an organism | 51 | clinical exam, not an assay |
| D | `OBI:0002176` electrophysiology assay | 31 | neuro/cardiac |
| E | `OBI:0000870` `OBI:0002036` `OBI:0002162` `OBI:0002438` | 61 | nucleic-acid structure mapping |
| F | `OBI:0600045` 3D structure determination assay | 22 | crystallography/cryo-EM |
| G | `OBI:0002732` `OBI:0003290` blood meal / mosquito feeding | 4 | vector biology |
| H | 10 metrology roots (length, speed, temperature, acidity, …) | 17 | not bioassays |
| I | `OBI:0000944` `OBI:0003725` `OBI:0003734` `OBI:0000117` | 6 | surveys and instruments |

Union is 558, not the column sum — the tiers overlap through multiple inheritance.

**Tier A is the big one and the only one needing care.** `OBI:21xxxxx` is a separate
clinical-chemistry namespace holding 402 terms, 32% of the old index. It mixes hospital analyzer
constructs a paper never names (*"GEM4000 ANLCOOX arterial blood glucose assay"*, *"CBC with
manual differential venous blood neutrophil count assay"*) with plain analyte readouts a paper
does cite (*"C-reactive protein assay"*, *"lymphocyte count assay"*). So the band is filtered by
**label**, never dropped wholesale — `OBI:2100402 pooled clone sequencing assay` lives in it and
is a real assay. Where a qualified term goes, its plain sibling stays: `OBI:2100006 neutrophil
count assay` and `OBI:0000630 hematology assay` both survive.

### KEEP_WHITELIST — families that would be left with nothing

Two exceptions are pinned by `KEEP_WHITELIST` in the prune script, both for the same reason: the
tier would remove a family's *only* usable term, and a term with no surviving sibling is a hole,
not a decoy. It is subtracted from the whole dropped set, so it rescues from any tier.

- **Immunoglobulins.** There is no bare *"IgG assay"*, so `OBI:2100177`/`2100178`/`2100179` and
  `OBI:2100234` (IgG/IgM/IgA/IgE) survive tier A. Without them `Anti-Diphtheria IgG` loses
  `OBI:2100177` — the only committed mapping either prune would have changed.
- **X-ray crystallography.** Tier F takes all four crystallography terms, and unlike cryo-EM
  (`OBI:0001631 electron microscopy imaging assay`) and NMR (`OBI:0000623 NMR spectroscopy
  assay`) this family keeps no parent outside the tier — the index was left with nothing
  crystallography-shaped at all. Surfaced by comparing the index against ImmPort's 102-term assay
  vocabulary, which lists `X-Ray Crystallography`. `OBI:0000912` is pinned; its three
  epitope/MHC-complex siblings still go.

  Note this restores a *retrieval target*, not an exact-match key: `OBI:0000912` has no synonyms
  and its label is `X-ray crystallography 3D molecular structure determination assay`, so
  ImmPort's short form still routes through the embedding + LLM step.

**The prune is behaviour-neutral on committed output.** All 53 OBI ids ever chosen across
`data/claims/` survive it. That is the point: ~95% of the old vocabulary had never once been
selected.

## The vectors

`obi_assay_pruned_embeddings.json` holds exactly the index's 701 terms, in index order. Since
2026-10-02 each row is embedded from **`label | synonyms | definition`** (`embed_input`); before
that it was `label | synonyms` over the unpruned 1262 terms. Adding the definition changes
retrieval, so benchmark results from before that date are not directly comparable.

Each row also keeps `text` = `label | synonyms` without the definition, because the mapper
splits `text` on `|` to show the pick LLM a candidate's synonyms.

`scripts/build_obi_embeddings.py` reuses a vector only when its row's `embed_input` is unchanged,
re-embeds the rest, and drops rows no longer in the index — so after a rebuild of the index, a
rerun embeds only what changed (a full build is ~30 K tokens, well under a cent).

The mapper still reconciles vectors with the index **by id** in `_top_k_candidates`
(`allowed_ids = _term_ids(terms_path)`), so a stale extra row could never be retrieved anyway.

## Rebuilding

One command. It reads `obi.obo`, takes the assay branch, applies both prunes, adds `definition`
and `n_descendants`, and rewrites `obi_assay_pruned_index.json`. Idempotent — rebuilding always lands on the same terms in the same
order, so a rerun is a no-op.

```bash
./.venv/bin/python scripts/prune_obi_domain.py                  # rebuild the index
./.venv/bin/python scripts/prune_obi_domain.py --dry-run        # counts only, writes nothing
./.venv/bin/python scripts/prune_obi_domain.py --show-dropped   # list the 558 removed terms
```

Stage 1 reuses `_is_generic_assay_label` from the mapper, so the `\bmeasuring\b` rule has exactly
one definition. Stage 2's roots live in `OUT_OF_SCOPE_ROOTS` / `CLINICAL_PANEL_QUALIFIERS` /
`KEEP_WHITELIST` in the script — edit those, rerun, and the index follows.

Entries are copied through untouched and in source order. **Order is load-bearing:**
`_build_lookup` indexes synonyms with `setdefault`, so index order decides which term wins a
synonym collision.

`apps/api/tests/test_assay_obi_mapper.py::test_index_is_reproducible_from_the_full_source`
re-derives the index and asserts it equals the committed file exactly — that check is what makes
it safe not to commit the removed lists.

```bash
# After any index change: re-embed changed rows, drop removed ones (a no-op otherwise).
./.venv/bin/python scripts/build_obi_embeddings.py
```

## Notes

- **The load-time filter is still applied** on top of this pre-pruned index, so it is a no-op
  for the default vocabulary. It stays because `run_obi_map.py --terms` can point the mapper at
  any term list, including the unpruned assay branch (`prune_obi_domain.assay_branch`).
- This folder is the **only** location for OBI vocabularies. The former copies under
  `.claude/skills/extract-assay-methods/references/` were deleted on 2026-08-19; `run_obi_map.py`
  imports the mapper and so reads these files transparently. Recover the old ones from git
  history if ever needed.
- `obi.obo` — full OBI release 2026-05-08 (5218 terms), the upstream ontology and the **only**
  source: `scripts/prune_obi_domain.py` derives the assay branch, the `is_a` graph, definitions
  and descendant counts from it. **Not** on the serving path. To move to a newer OBI release,
  replace this file and rerun both scripts under *Rebuilding*. `obi_assay_full_index.json` is
  the same 1794-term branch written out in the index's format (restored 2026-10-26 by
  `scripts/build_obi_assay_terms.py`; the 2026-10-02 version had only id, label and synonyms).
- The domain prune is expressed as **subtree roots, not label keywords**, so it survives an OBI
  release bump. Depth cutoffs, leaf/internal splits and keyword lists were all evaluated and
  rejected: the branch is too shallow (705 of the old 1262 terms sat at depth 2) and domain
  keywords collide with terms we need (`sequencing`, `imaging`, `microscopy`).
- The removed terms were briefly committed as `obi_compositional_dropped.json` and
  `obi_domain_dropped.json`; both were deleted on 2026-09-09 as derived data. Use
  `--show-dropped`, or recover a historical copy with
  `git show <rev>:data/OBI/obi_compositional_dropped.json`.

## Known gap

Two common assays have **no** generic term: the plain `intracellular cytokine staining assay`
(`OBI:0000665`) and `MHC multimer staining assay` (`OBI:0000667`) are **obsolete** in OBI, so
they are outside the assay branch. The two are handled differently, following what `obi.obo`
names as each one's replacement:

- **Intracellular cytokine staining** — `OBI:0000665 replaced_by OBI:0000916`. Since 2026-09-11
  it is not pinned by an override map: the extractor's `standard_technique_name` records the measurement
  technique ("flow cytometry"), which maps to `OBI:0000916` exactly.
- **MHC multimer staining** — `OBI:0000667 replaced_by OBI:1110179` *MHC tetramer/multimer assay
  measuring binding of a T cell epitope:MHC:TCR complex*. That label is compositional, so the
  filter dropped it and a tetramer stain fell back to flow cytometry, where the round-5 merge
  folded it into the paper's other flow panels (SDY212's "tetramer staining" was lost that way).
  Since 2026-10-13 it is pinned by `_COMPOSITIONAL_KEEP`. It `is_a` both `OBI:0000916` and
  `OBI:0003128 T cell epitope assay`, so it stays comparable to a benchmark that uses either.

The `assay detecting X` family (e.g. `OBI:1110207 assay detecting IFN-gamma production`) was
added to the compositional filter on 2026-09-09 and is no longer in the index; a benchmark citing
such a term can never be matched by the pipeline.
