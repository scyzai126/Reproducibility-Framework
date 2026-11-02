# Dictionary baseline

*2026-11-02. `run_dictionary.py`; results in `comparison/summary.md`. Free: no model call.*

The OBI assay vocabulary string-matched against the paper: every label and synonym, as whole
words, longest match first, one entry per term found. It is the "why not just grep for the
ontology" arm, with no model on either side. Four variants: the agent's 701 pruned terms or all
1794 assay terms, over the whole paper or its Methods sentences only.

## Result (31 papers, benchmark v5, strict scorer)

| | agent | pruned, paper | pruned, methods | full, paper | full, methods |
|---|---|---|---|---|---|
| entries | 177 | 484 | 349 | 494 | 354 |
| matched of 158 | 156 | 141 | 124 | 141 | 124 |
| MISSED | 2 | 17 | 34 | 17 | 34 |
| EXTRA | 4 | 341 | 224 | 351 | 229 |
| exact OBI term | 140 | 79 | 63 | 79 | 63 |
| OBI ok (same or parent/child) | 145 | 108 | 91 | 108 | 91 |
| wrong term (CONFLICT) | 5 | 31 | 31 | 31 | 31 |
| recall | 98.7% | 89.2% | 78.5% | 89.2% | 78.5% |
| precision | 88.1% | 29.1% | 35.5% | 28.5% | 35.0% |
| F1 | 0.931 | 0.439 | 0.489 | 0.433 | 0.484 |

Default-scorer numbers are in `comparison/summary.md`; they differ by a row or two.

**Reading.** The dictionary finds most curated assays by name (recall 89% over the whole paper)
but names the wrong term for 44% of them (79 exact of 141 matched) and delivers 3.4 entries for
every one it should: `protein assay`, `immune response assay`, `blood assay`, `cytokine assay`
and `monocyte assay` are matched in 19-29 papers each, because their labels are everyday words
(83 distinct EXTRA terms in all). Restricting to Methods removes a third of the EXTRA entries and
17 curated assays with them. The full vocabulary adds 10 entries and no match: the 1,093 terms
the agent's prune removes name nothing the papers say.

The 31 wrong terms are mostly one pattern: `microarray assay` where the curator wrote
`transcription profiling by array assay` (15 papers), and `real time polymerase chain reaction
assay` where the curator's term is the RT-PCR child (5). The 17 misses are the paper's own
wordings, which no OBI label or synonym carries and which the agent's retrieval and pick resolve:
CBA, RT-qPCR, SBA, plaque assay, tetramer staining, ADCC, "flow cytometric analyses",
"Single-molecule array", "virus_isolation".

## Rules (so the arm is neither a strawman nor a cheat)

- Forms: the label, each synonym, and the label without a trailing "assay" ("flow cytometry"
  names `flow cytometry assay`). Whole words, case-insensitive; a hyphen or slash inside a form
  matches itself or a space ("real-time PCR" = "real time PCR").
- A 3-character form is an acronym and must match in its own case (`PCR`, not "pcr"); a form
  shorter than that, or a single all-lowercase word of 4 letters or fewer, is dropped. Dropped
  from both vocabularies: `5C`, `FM`, `HA`, `HI`, `IA`, `OM`, `iron`, `lung`, `milk`.
- Overlaps: the longest span wins, so "real-time PCR" is one term, not PCR plus real-time PCR.
- A 4-letter form is still case-insensitive, so `ChIP` matches the "chip" of a BeadChip in 8
  papers. That is a property of dictionary matching, not a bug, and it is left in.
- Methods scope: the sentences under a `[methods]` heading of the JATS parse. The four PDF papers
  (SDY404, SDY1293, SDY1276 (21357945), SDY1291) have no headings and are matched whole in both
  scopes; `matches.json` records `scope_applied` per paper.

```
./.venv/bin/python experiment/dictionary_baseline/run_dictionary.py run      # runs/<vocab>_<scope>/
./.venv/bin/python experiment/dictionary_baseline/run_dictionary.py score    # comparison/<variant>{,_strict}.{json,html}
./.venv/bin/python experiment/dictionary_baseline/run_dictionary.py report   # comparison/summary.md
```

Tests: `tests/test_run_dictionary.py`.
