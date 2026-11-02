# NCBO BioPortal Annotator baseline

*2026-11-02. `run_ncbo.py`. Status: **run on all 31 papers**, both scopes; replies cached under
`runs/raw/`, scores in `comparison/summary.md`. Needs a BioPortal API key (free:
https://bioportal.bioontology.org/accounts/new) in `.env` as `BIOPORTAL_API_KEY` only to re-fetch.*

The NCBO Annotator is the standard published service for finding ontology classes in free text
(dictionary lookup over the labels and synonyms of the ontologies BioPortal hosts, OBI among
them). It is the external arm a reviewer expects beside the home-made dictionary in
`experiment/dictionary_baseline/`. No model on either side; one HTTP request per paper and scope,
cached under `runs/raw/` so reruns are free.

Settings: `ontologies=OBI`, `longest_only=true`, synonyms on, whole words only, numbers excluded.
Classes outside the assay vocabulary (devices, roles, specimens) are dropped before scoring, under
the same two vocabularies as the dictionary arm (701 pruned / 1794 full), over the same two
scopes (whole paper / Methods sentences; the four PDF papers have no headings and are sent whole).

```
./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py fetch    # runs/raw/<scope>/<registry>.json  (network)
./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py build    # runs/<vocab>_<scope>/            (free)
./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py score    # comparison/<variant>{,_strict}   (free)
./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py report   # comparison/summary.md            (free)
```

Two things the run needed: the framework Python this repo runs on ships no CA bundle, so the
request uses certifi's; and SDY1669's headings carry no Methods section, so its Methods-scope
text is empty, which the Annotator rejects (400) -- the fetch writes an empty reply there, as the
dictionary arm writes 0 entries.

## Result (strict scorer, 158 curated rows; `comparison/summary.md` has both modes)

| | agent | pruned / paper | pruned / methods | full / paper |
|---|---|---|---|---|
| entries | 177 | 94 | 79 | 96 |
| matched | 156 | 60 | 48 | 60 |
| EXTRA | 4 | 34 | 31 | 36 |
| exact OBI term | 140 | 47 | 37 | 47 |
| recall / precision / F1 | 98.7% / 88.1% / 0.931 | 38.0% / 63.8% / 0.476 | 30.4% / 60.8% / 0.405 | 38.0% / 62.5% / 0.472 |

The Annotator matches whole words against OBI's labels and synonyms exactly, and that decides
both numbers:

- **It finds an assay only where the paper writes OBI's string.** `flow cytometry assay` is
  found in 10 papers, every one of them through the synonym `FACS` (36 hits); the words "flow
  cytometry" never match, because OBI's label carries "assay" and has no bare synonym. So the
  curators' most frequent term is missed in 18 papers, `transcription profiling by array assay`
  in 13 ("microarray"), `cytometric bead array assay` in 8 ("Luminex"), `serum neutralization of
  viral infectivity assay` in 7, `bulk RNA-seq assay` in 7 ("RNA-seq"). What it does find is the
  terms whose everyday name is an OBI synonym: ELISA (13 papers), FACS (10), HAI (6), CyTOF (5),
  ELISPOT (3).
- **Its extras are OBI's acronym synonyms taken literally.** `LPS` grounds to both
  `bacterial lipopolysaccharide detection in plasma assay` and `... in feces assay` (7 papers);
  `RPA` to `RNA protection assay` (4); `CMV` to `serum anti-cytomegalovirus antibody level assay`
  (4); `TAQMAN` to `fluorogenic PCR assay` (3); `GCP` to `global chromatin profiling by mass
  spectrometry assay` (2); `IMMUNOASSAY` to `single-value binding of antibody with reporter to
  antigen assay` (2). That is 24 of the 34 extras.

The home-made dictionary in `experiment/dictionary_baseline/` matches 141 of the same rows from
the same vocabulary because it also matches a label without its trailing "assay" and keeps a
3-letter acronym case-sensitive; the two arms together show that a lexical method's recall is
set by the ontology's synonym list, not by the matcher.

Tests: `tests/test_run_ncbo.py` (a stored reply shape, the empty-scope fetch, no network).
