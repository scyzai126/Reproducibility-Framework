# OntoGPT (SPIRES) baseline

*2026-11-02. `run_ontogpt.py`, template `assay_paper.yaml`. Status: installed and smoke-tested on
two sentences; **the 31-paper run has not been made** (dry run: 31 extractions, one model call
each, ~343k input tokens).*

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

Tests: `tests/test_run_ontogpt.py` (a stored output shape; no call).
