# NCBO BioPortal Annotator baseline

*2026-11-02. `run_ncbo.py`. Status: code and tests in place; **not yet run** -- it needs a
BioPortal API key (free: https://bioportal.bioontology.org/accounts/new) in `.env` as
`BIOPORTAL_API_KEY`.*

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

Tests: `tests/test_run_ncbo.py` (a stored reply shape; no network).
