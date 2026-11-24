# Map every agent assay (31 papers) to the study's ImmPort experiments

## Context

For the 31 benchmark papers the agent delivered 176 assay entries (`data/benchmark_agent_assays/assay_result_v3/<pmid>_<SDY>/`). ImmPort records 133 experiments for the same 29 studies, each labelled with one of 79 technique names that carries one OBI id (`experiment.measurement_technique` → `lk_exp_measurement_tech.link`).

What exists today only answers the opposite question:

- `scripts/check_immport_measurements.py` grades **ImmPort technique → best agent entry** (one-directional by design; 83 pairs: 62 EXACT, 9 DESCENDANT, 3 EXPNAME, 3 SIBLING, 6 MISS).
- `scripts/build_assay_three_way.py` (untracked) attaches each ImmPort technique to **one** agent row; other agent entries on the same term (`flow cytometry assay (2)`) get no link, and there is no list of agent assays ImmPort lacks.
- `apps/api/app/agent/assay_immport.check_rows` does go agent → experiment, but on `assay_result_v1`, by `LIKE` needing a unique hit plus a paid LLM fallback, with no OBI-graph grading.

Missing: for **each agent assay**, which ImmPort technique and which experiment row(s) it corresponds to, and which agent assays have no ImmPort counterpart.

## Approach: two levels, deterministic, no LLM call

### Level 1 — agent assay → ImmPort technique (the reliable link)

For each paper, take the study's informative `(technique, ontology ids, experiment names)` groups and grade every agent entry against every group by calling the existing `classify()` with a **one-entry list**. That reuses the tested rules unchanged:

| Level | Meaning |
|---|---|
| EXACT | same OBI id |
| DESCENDANT | agent term is more specific than ImmPort's |
| ANCESTOR | agent term is broader |
| NAME | ImmPort technique name equals an agent name/alias |
| EXPNAME | an `experiment.name` matches an agent name/alias (rescues ImmPort mislabels) |
| SIBLING | shared direct parent, hub parents excluded |
| NONE | no technique in the study matches → **agent-only assay** |

Keep the best-ranked technique per agent entry (all ties kept). SIBLING is reported as a weak link, not counted as mapped.

### Level 2 — agent assay → experiment row(s) under that technique

- Technique has **one** experiment → link it (`SINGLE`).
- Technique has **several** (21 technique groups in these studies) → score each experiment by whole-word overlap between `experiment.name` + `experiment.description` and the agent entry's `name_in_paper`, `aliases`, `sample_type`, `readouts` (via `normalize`). A unique top scorer above zero → `NAMED`; otherwise `AMBIGUOUS`, listing every candidate experiment. Never guess.

`AMBIGUOUS` is an expected, honest outcome: ImmPort experiment names are free text ("T reg", "IM_panel_BD") and OBI cannot separate them, as the SDY1252 example showed.

### Also reported

- **ImmPort experiments no agent assay claimed** (reverse leftovers), so the two directions reconcile with the existing 6 MISS.
- Per-paper and overall counts by level and by experiment status.

## Files

| File | Change |
|---|---|
| `scripts/map_agent_assays_to_immport.py` | **New.** Imports `classify`, `our_entries`, `term_ids`, `mysql_url`, `UNINFORMATIVE` from `scripts/check_immport_measurements.py` and `ObiGraph`, `normalize` from `scripts/compare_assay_benchmark.py`. Own query selects `experiment_accession, name, description, measurement_technique` for the 29 studies (pattern: `immport_studies()` in `build_assay_three_way.py`). Flags: `--registry-dir` (default v3), `--study`, `--json`, `--report`. Read-only SELECTs. |
| `apps/api/tests/test_map_agent_assays_immport.py` | **New.** No DB: fake technique groups and entries covering each level, tie handling, SINGLE / NAMED / AMBIGUOUS, agent-only, and unclaimed experiments. |
| `data/benchmark_agent_assays/assay_result_v3/comparison/agent_to_immport.json` | **New output.** One record per agent entry: `pmid, study, key, obi_id, level, technique, experiment_status, experiments[], candidates[]`. |
| `docs/agent_to_immport_mapping_2026-11.md` | **New generated report** (tables above, plus the AMBIGUOUS and agent-only lists in full). |
| `docs/plan/agent_to_immport_mapping_plan.md` | Copy of this plan, per the repo convention. |

`check_immport_measurements.py`, `build_assay_three_way.py` and `assay_immport.py` are not modified. `our_entries()` does not load `sample_type`/`readouts`, so the new script reads them from `assays_OBI.json` itself rather than changing the shared helper.

## Known limits (stated in the report)

- ImmPort's grain is the technique; most links will be solid at Level 1 and partly ambiguous at Level 2.
- An agent assay with no ImmPort match is normal (ImmPort registers only deposited data), not an agent error.
- 4 studies have ImmPort papers we do not hold; their unclaimed experiments may belong to those papers (reuse the existing `complete` flag).
- Not included: an LLM pass to settle AMBIGUOUS pairs. It would be a paid step (one call per ambiguous agent entry); propose it separately with a call count if the deterministic result leaves too many open.

## Verification

1. `pytest apps/api/tests/test_map_agent_assays_immport.py apps/api/tests/test_check_immport_measurements.py` from the repo-root `.venv`; then the full `pytest` in `apps/api/` (10 pre-existing subject-query failures are the known baseline).
2. Run the script on all 31 papers (free, needs local MySQL). Check: 176 agent entries in, every one has a level; the set of techniques reached at EXACT/DESCENDANT/EXPNAME agrees with the existing coverage report (74 of 83 pairs); SDY1252-style multi-experiment techniques show as NAMED or AMBIGUOUS, never silently one experiment.
3. Spot-check three papers by hand against the database: one single-experiment study (SDY1260 ELISA → EXP16730), one multi-experiment technique, one with an agent-only assay.
