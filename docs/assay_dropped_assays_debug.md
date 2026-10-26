# Why the agent dropped an assay in SDY180, SDY1654, SDY1655 and SDY2189

Written 2026-10-23, following the adjudication in
[benchmark_v5_vs_agent_v1_adjudication.md](benchmark_v5_vs_agent_v1_adjudication.md), which blamed
the agent for one missing assay in each of four papers.

**Three of the four were already fixed before this investigation started.** The report that showed
them reads `data/31paper_assays/assay_result_v1/`, written on 2026-10-12 by the pre-vote pipeline:
round 1 was a single extraction call, with no 3-way consensus vote and no `assays_raw.json` trace.
The vote landed on 2026-10-19 in commit `281e006`, and only 3 of the 31 v1 directories were ever
re-run under it, which is why 28 of them have no raw file.

`data/31paper_assays/assay_result_v3/` is the full corpus on the current pipeline and was already
scored at `assay_result_v3/comparison/benchmark_v5_vs_agent.html`.

| | v1, the report that was reviewed | v3, current |
|---|---|---|
| recall | 0.953 | 0.993 |
| precision | 0.934 | 0.887 |
| missed, whole corpus | 7 | **1** |

## SDY1655, the HD71 cytokine array: the verifier deleted a correct entry

Extraction found it with the right quote from its own Methods paragraph. The verifier then marked
`sample_type`, `readouts` and `evidence.quote` all SUPPORTED, and set the record's identity to
CONTRADICTED on `name_in_paper`, with this reason:

> This is a product/panel name rather than an assay technique name.

`assay_corrector.drop_rejected` deletes any record whose identity is CONTRADICTED, and identity is
deliberately non-repairable, so the paper's only cytokine measurement was gone. The verifier had
applied a technique-name test to the field that holds the paper's own wording. The run's
`assays_rejected.json` recorded only the other rejection, Trypan blue, so the deletion was not even
visible in the audit file.

Already fixed. `apps/api/app/prompts/verify_assays.txt:187-194` now states that a product, panel,
kit, platform or vendor name is not grounds for REJECT, and names HD71 as its example. In v3 the
entry is delivered as `cytometric bead array assay` and no rejected file is written.

## SDY180, the pneumococcal immunoassays: extraction never proposed it

The phrase appears in no v1 stage file, so nothing downstream dropped it. This was not a coverage
problem either: the two assays named in the immediately adjacent sentences, hemagglutination
inhibition and virus neutralization, were both extracted from the same paragraph. The extractor
skipped a clause whose only name is a generic product category.

Already fixed. `verify_assays.txt:91-93` now rules that a name too vague to identify a technique is
NOT_SUPPORTED, which reaches REVIEW rather than removal, and quotes "commercial immunoassays"
verbatim. In v3 the entry is delivered and carries an `identity_review` with that verdict.

## SDY1654, the proliferation assay: one entry per methods heading

The paper's methods heading is "Flow cytometry and proliferation assays". v1 emitted a single entry
named "flow cytometry" for the whole section, absorbing a distinct assay that runs cells for 120
hours with a proliferation dye. The same collapse explains the SDY1630 and SDY1328 merge faults in
the adjudication.

Already fixed. v3 emits `cell proliferation assay` as its own entry and SDY1654 scores 4 of 4.

## SDY2189, SIMOA: still missing, and a real bug

`assays_raw.json` in v3 shows that none of the three extraction calls proposed it, so this is not a
lost vote. The paper names SIMOA three times and the parser removes two of them.

| Mention | Fate |
|---|---|
| Author contributions, "K.H. and M.R. performed SIMOA" | dropped, author contributions is on the section denylist |
| Extended Data Fig. 7 legend, "IFNα2 measured by SIMOA" | dropped, `jats_parser.py` skips any figure whose label contains "extended data" |
| Results, "just over the assay limit of the highly sensitive single-molecule array (SIMOA)" | kept |

Both statements that say the measurement was performed are removed. What survives is an aside about
a detection limit. Pass 1 of the extractor builds its inventory from Methods only and SIMOA has no
methods subsection; pass 2 admits a Results-only assay just when the sentence says the technique was
run on this study's samples, which that sentence does not do.

The 120 000-character cap in the parser is not involved. SDY2189 parses to 50 722 characters.

### The fix

`parse_jats_xml` now takes `include_extended_data`, default False. The assay pipeline passes True,
from `assay_service.paper_source_text` and from `run_assay_verify.paper_text`; both have to change
together, because the verifier re-parses the paper to check quotes and a parse that differed from
the extractor's would misattribute sentence ids. Every claim-path caller keeps the old behaviour.

The exclusion came in with `090fc22`, a general JATS cleanup aimed at the claim path, not a response
to any assay problem. Lifting it for the assay path affects three papers in `data/JAT_XML/` and only
two in the benchmark corpus:

| Paper | Extended Data captions | Characters added |
|---|---|---|
| SDY2189 | 12 | 15 050 |
| SDY1655 | 9 | 8 085 |
| SDY1648, not in the corpus | 3 | 1 631 |

SDY2189's parse goes from 50 722 to 66 056 characters and its SIMOA mentions from 1 to 3, including
the legend sentence "IFNα2 measured by SIMOA".

### Still to do

Re-running the two affected papers is a paid step and has not been done. The dry-run estimate is
about 45 calls for SDY2189 and about 17 for SDY1655. Until then, v3's registries for those two
papers were produced by the old parse.

If the re-run still misses SIMOA, the fallback is a pass-2 wording change in
`apps/api/app/prompts/extract_assays.txt:77-80`, admitting a Results sentence that attributes a
measurement to a named technique. That loosens admission corpus-wide and precision is already the
weaker axis in v3, so it is worth trying only if the bounded parser change proves insufficient.
