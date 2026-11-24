# Add a "Comment" column to the agent vs ImmPort tables

## Context

The section "Agent assays vs ImmPort experiments, study by study" in
`docs/assay_same_term_grain_question_2026-11-20.html` shows, per study, a 6-column table
(Agent assay | Agent OBI term | Match | ImmPort technique | ImmPort OBI term | ImmPort experiment).

The paper-by-paper review has produced a reason for most rows that are not a clean match
(SDY1655: ImmPort's "Protein microarray" is a bead assay; RT-qPCR vs qPCR are sibling terms because
ImmPort has no reverse-transcription option; SDY180 Nanostring is in neither article nor supplement;
SDY1289 PRNT is only in Supplemental Table 2). Today those reasons exist only in the chat. The
professor reading the page sees "Agent only" or "ImmPort only" with no explanation.

**Recommendation: yes, add the column**, with two rules so it stays honest and maintainable:

1. Only rows that are not a same-term match get a comment (blank for EXACT rows).
2. A comment is either written by hand from the review, or a short automatic line that says only
   what the rule knows. Rows in studies not yet reviewed say "not reviewed yet" rather than a guess.

## Design

### Where the comments live

New file `data/benchmark_agent_assays/assay_result_v3/comparison/agent_to_immport_comments.json`,
hand-edited, kept in the repo so the review survives a regeneration:

```json
{
  "SDY1655": {
    "reviewed": true,
    "agent": {
      "cytometric bead array assay": {
        "verdict": "same assay, ImmPort label questionable",
        "match": ["EXP29870"],
        "comment": "Eve Technologies HD71 panel is bead-based; ImmPort files it as Protein microarray. Paper: 'Human Cytokine Array/Chemokine Array 71-403 Plex Panel (HD71)'."
      }
    },
    "immport": {
      "EXP29874": {"verdict": "not in paper", "comment": "Saliva RT-PCR is in neither the article nor the supplement."}
    }
  }
}
```

- `match` (optional) pairs an agent row with experiments by hand; `agent_only: true` (optional)
  removes a rule match. These replace the `HAND_MATCH` / `HAND_AGENT_ONLY` dicts now hard-coded in
  the generator, so every hand correction carries its reason in the same place.
- `verdict` is a short fixed label shown in bold before the comment: `same assay, different term` /
  `in supplement only` / `not in paper` / `belongs to another paper` / `not deposited in ImmPort` /
  `ImmPort label questionable`.

### Automatic comment (when no hand comment exists)

| Row | Automatic text |
|---|---|
| EXACT | blank |
| DESCENDANT / ANCESTOR | "Agent term is more specific / broader than ImmPort's." |
| EXPNAME | the evidence string already computed (`name_evidence`) |
| SIBLING | "Terms share a parent; weak link, not counted." |
| Agent only, ImmPort only | "Not reviewed yet." if the study is not marked `reviewed`; in a study with other ImmPort papers also "Study has N other papers." |

### Generator

The page generator is a temporary file in the session scratchpad and will be lost. Move it into the
repo as `scripts/build_agent_immport_section.py` (same logic, reads `agent_to_immport.json` and the
comments file, rewrites only the text between `<!-- BEGIN agent-vs-immport -->` and
`<!-- END agent-vs-immport -->`). Add the 7th column "Comment", and a count line per study of how
many non-matching rows have a reviewed comment.

### Comments to enter now (from the review already done)

SDY80, SDY180, SDY212, SDY404, SDY984, SDY1264, SDY1289, SDY1655, SDY1669 — every non-matching row,
using the findings already established. The other 20 studies stay "Not reviewed yet" and are filled
as the review continues. For SDY1655's bead array comment, state that the bead-platform claim comes
from the vendor, not the paper.

## Files

| File | Change |
|---|---|
| `scripts/build_agent_immport_section.py` | New (moved from scratchpad) + Comment column, reads comments file |
| `data/benchmark_agent_assays/assay_result_v3/comparison/agent_to_immport_comments.json` | New, hand-written review comments and hand matches |
| `apps/api/tests/test_build_agent_immport_section.py` | New: hand comment wins over automatic; blank for EXACT; `match` / `agent_only` applied; unreviewed study says "Not reviewed yet"; unknown key in the comments file is reported, not ignored |
| `docs/assay_same_term_grain_question_2026-11-20.html` | Regenerated section only |

`scripts/map_agent_assays_to_immport.py` and its output are not changed.

## Verification

1. `pytest apps/api/tests/test_build_agent_immport_section.py apps/api/tests/test_map_agent_assays_immport.py`,
   then the full suite from `apps/api/` (10 known subject-query failures are the baseline).
2. Regenerate the page; totals must be unchanged apart from SDY1655's bead array row moving from
   unmatched to hand-matched. Open the page and check SDY180, SDY1655 and SDY1669 rows by eye.
3. The generator prints any comment key that matches no agent row or experiment, so a typo in the
   comments file cannot silently drop a comment.
