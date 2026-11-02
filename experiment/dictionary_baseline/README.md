# Dictionary baseline

*2026-11-02. `run_dictionary.py`; results in `comparison/summary.md`. Free: no model call.*

The OBI assay vocabulary string-matched against the paper: every label and synonym, as whole
words, longest match first, one entry per term found. It is the "why not just grep for the
ontology" arm, with no model on either side. Four variants: the agent's 701 pruned terms or all
1794 assay terms, over the whole paper or its Methods sentences only.

## Result (31 papers, benchmark v5, strict scorer)

| | agent | pruned, paper | pruned, methods | full, paper | full, methods |
|---|---|---|---|---|---|
| entries | 177 | 410 | 286 | 418 | 290 |
| matched of 158 | 156 | 135 | 114 | 135 | 114 |
| MISSED | 2 | 23 | 44 | 23 | 44 |
| EXTRA | 4 | 274 | 172 | 282 | 176 |
| exact OBI term | 140 | 69 | 52 | 69 | 52 |
| OBI ok (same or parent/child) | 145 | 95 | 75 | 95 | 75 |
| wrong term (CONFLICT) | 5 | 38 | 37 | 38 | 37 |
| recall | 98.7% | 85.4% | 72.2% | 85.4% | 72.2% |
| precision | 88.1% | 32.9% | 39.9% | 32.3% | 39.3% |
| F1 | 0.931 | 0.475 | 0.514 | 0.469 | 0.509 |

Default-scorer numbers are in `comparison/summary.md`; they differ by a row or two.

**Reading.** The dictionary finds most curated assays by name (recall 85% over the whole paper)
but names the wrong term for half of them (69 exact of 135 matched) and delivers 2.7 entries for
every one it should: `protein assay`, `immune response assay`, `blood assay`, `cytokine assay`
and `binding assay` are matched in 13-27 papers each, because their labels are everyday words.
Restricting to Methods halves the EXTRA count and drops 21 curated assays with it. The full
vocabulary adds 8 entries and no match: the 1,093 terms the agent's prune removes name nothing
the papers say.

Where it loses a curated row it is the paper's wording: Luminex, PRNT, CBA, SIMOA, "Taqman" --
names no OBI label or synonym carries, which the agent's retrieval and pick resolve.

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
