# OntoGPT (SPIRES) baseline

*2026-11-02. `run_ontogpt.py`, template `assay_paper.yaml`. Status: **run on all 31 papers**
(31 extractions, one model call each, 337,777 prompt tokens, 1,977 completion, nothing cached);
raw replies under `runs/r1/<registry>/`, scores in `comparison/summary.md`.*

OntoGPT (Monarch Initiative, Caufield et al. 2024, *Bioinformatics*) is the closest published
system to this agent: a LinkML schema tells the model what to list, the model answers in free
text, and each answer is grounded to an ontology term by lexical lookup over the ontology's
labels and synonyms (OAK's annotator; here `sqlite:obo:obi`). It is run as it ships, with the
agent's model (`OPENAI_MODEL`, gpt-5.4), on the same paper text the agent's round 1 reads. No
vocabulary in the prompt, no retrieval, no vote, no verification, no fold.

The smoke test shows the shape of what to expect: given "Luminex multiplex assay", "plaque
reduction neutralization test (PRNT)", "flow cytometry" and "RNA-seq", the model lists all four
and the grounder places none of them (`AUTO:` ids), because none is an OBI label or synonym;
given "ELISA" and "flow cytometry assay" it grounds both (synonym and exact label). Grounding to
a class outside the assay subtree ("Luminex" is `OBI:0001443`, an instrument) is scored as
unmapped (`outside_vocabulary`).

## Install (its own virtualenv; the project's cannot host it)

```
/Library/ManagedFrameworks/Python/Python3.framework/Versions/3.10/bin/python3 -m venv experiment/ontogpt/.venv
experiment/ontogpt/.venv/bin/pip install "ontogpt==1.2.0"
experiment/ontogpt/.venv/bin/pip install -U litellm          # 1.97.0, the version OntoGPT pins for
                                                             # Python 3.10, fails to build its reply
                                                             # model ("`Message` is not fully defined");
                                                             # 1.106.6 works
experiment/ontogpt/.venv/bin/pip install "openai==2.30.0"    # the project's version
experiment/ontogpt/.venv/bin/runoak -i sqlite:obo:obi info OBI:0000916   # fetches obi.db (~35 MB) once
```

Versions used: ontogpt 1.2.0, oaklib 0.7.4, litellm 1.106.6, openai 2.30.0, pydantic 2.14.2,
Python 3.10.11. The venv is gitignored.

## Run

```
./.venv/bin/python experiment/ontogpt/run_ontogpt.py run --dry-run      # count, free
./.venv/bin/python experiment/ontogpt/run_ontogpt.py run                # 31 calls -> runs/r1/<registry>/{input.txt, output.json, ontogpt.log}
./.venv/bin/python experiment/ontogpt/run_ontogpt.py build              # both vocabularies, free
./.venv/bin/python experiment/ontogpt/run_ontogpt.py score [--vocab pruned]
./.venv/bin/python experiment/ontogpt/run_ontogpt.py report [--vocab pruned]
```

Scoring: an entity grounded to a term of the assay vocabulary (full 1794 by default; the agent's
701 pruned with `--vocab pruned`) is a mapped entry; `AUTO:` and out-of-subtree groundings are
unmapped entries keyed by the model's wording. The quote is the sentence of the entity's first
span in the text OntoGPT read. Token usage is read off the `-vv` log, which carries the raw
model reply.

`runs_pruned/` is a staging copy that `score --vocab pruned` makes from the `_pruned` files; it
is derived and gitignored. On this corpus the two vocabularies score identically (28 grounded
terms, all inside the 701).

## Result (strict scorer, 158 curated rows; `comparison/summary.md` has both modes)

| | agent | OntoGPT |
|---|---|---|
| entries | 177 | 263 |
| matched | 156 | 155 |
| EXTRA | 4 | 107 |
| exact OBI term | 140 | 22 |
| OBI ok (same or parent/child) | 145 | 23 |
| UNMAPPED | 6 | 129 |
| recall / precision / F1 | 98.7% / 88.1% / 0.931 | 98.1% / 58.9% / 0.736 |

The model lists the assays (155 of 158 curated rows are matched) and the grounder cannot name
them: of 263 entities, 28 are grounded to a term of the assay vocabulary, 10 to an OBI class
outside it (`Luminex`, an instrument), and 225 stay `AUTO:`. The 22 exact terms are the ones
whose everyday name is an OBI label or synonym: ELISA (7 papers), HAI (4), CyTOF (4), real-time
PCR (2), CITE-seq (2). The unmapped curated rows are the rest of the corpus: `flow cytometry
assay` 28 times (the model writes "flow cytometry"; OBI's label has "assay" and its only synonym
is FACS), `transcription profiling by array assay` 14 ("microarray analysis", "DNA microarray"),
`cytometric bead array assay` 8 ("Luminex"), `bulk RNA-seq assay` 8 ("RNA-seq"), `ELISA` 8
("IgM capture ELISA", "Inhibition ELISA"), `ELISPOT` 7 ("ELISpot" is not the synonym
"ELISPOT assay"). Only 3 rows carry a wrong term.

The 107 extras are what the bare call also lists and the agent's verifier removes: analysis
steps (principal component analysis, GSEA, WGCNA, viSNE, nearest-centroid classification), `cell
sorting`, `in vitro stimulation`, and a second entity for the same assay under another wording
(`flow cytometry` beside `polychromatic flow cytometry`). Its F1 is below the bare call's
(0.736 vs 0.761) for that reason; its term accuracy is the bare call's with ids as given (22 vs
13 exact).

Tests: `tests/test_run_ontogpt.py` (a stored output shape; no call).
