# SDY1260 — whole-PDF vs. JATS-with-passes claim extraction

Two reading logics, one paper (SDY1260 / PMID 24336226, Li et al. *Nat Immunol* 2014), one shared
output schema, scored against a hand-built gold standard.

## Setup

| | Arm A | Arm B |
|---|---|---|
| input | the complete PDF (all pages, rendered panels, legends) | `jats_parser` output, split per panel by `split_panels` |
| logic | one pass — read prose + panel + legend **together**, then draft | two passes per panel — draft from prose alone, then reconcile against the withheld legend |
| prompt | `apps/api/app/prompts/exp_arm_a_wholepdf.txt` | `exp_arm_b_pass1.txt` + `exp_arm_b_pass2.txt` |
| runner | `scripts/exp_run_arm_a.py` | `scripts/exp_run_arm_b.py` |

Both prompts embed the **same** `exp_shared_core.txt` — identical claim definition, split/merge rules,
`claim_type` vocabulary, polarity rule, and output schema. The only variable is the reading logic.
Both ran at `temperature=0` on `gpt-5.4`.

## Gold standard

`gold_standard.json` — 87 assertions enumerated by hand from the Results prose and the figure/table
legends, at the granularity the project's own split/merge rules imply. Two tiers:

- **Tier 1 (36)** — Results section 1, Figure 1 + Table 1. Crisp, enumerable, scored strictly.
  Includes the Figure 1d SBA sentence that `extract_claims_pdf.txt` itself scores as 4 assertions × 2
  groups = 8 claims.
- **Tier 2 (51)** — Results sections 2–6, Figures 2–6 and supplementary. Module/enrichment statements
  have genuinely ambiguous granularity, so these are scored loosely and reported separately.

Two assertions are marked `optional` (they rest on "data not shown"); four are marked `merge_ok`.

## Results

| metric | **Arm A (whole PDF)** | **Arm B (JATS + passes)** |
|---|---|---|
| claims extracted | 92 | 83 |
| correct | **67** | 47 |
| merged (legitimate) | 3 | 1 |
| granularity (under-split) | 1 | 1 |
| duplicate | 12 | 13 |
| **distorted** | **3** | **9** |
| **unsupported** | **6** | **12** |
| precision (strict) | **0.761** | 0.578 |
| **Tier 1 recall** | **1.000** (35/35) | 0.829 (29/35) |
| **Tier 2 recall** | **0.780** (39/50) | 0.400 (20/50) |
| **overall recall** | **0.871** | 0.576 |
| LLM calls | **1** | 14 |
| tokens (prompt + completion) | **43.6k + 17.7k** | 76.7k + 40.5k |

**Arm A wins on every accuracy axis and costs roughly half as much.** It found *every* Tier 1
assertion, including all eight of the SBA sub-assertions and both stated absences (G28, G30).

## Why Arm B lost

**1. Orphaned paragraphs — the dominant cause.** `split_panels` attaches a Results paragraph only to
panels it cross-references via a `<xref>` to a `<fig>`/`<table-wrap>` in the body. Supplementary
figures are not such nodes. **7 of the paper's 24 Results paragraphs are attached to no panel at all**
and Arm B therefore never reads them:

```
ORPHAN  We also identified pathways whose expression were correlated to antibody responses (Supp Fig. 6)...
ORPHAN  The BTM construction process recovered many known protein complexes...
ORPHAN  The distinctive early patterns of the protein recall response ... become less apparent by day 7...
ORPHAN  In summary, our BTM analysis ... T cell activation ... a male-specific module (M240)...
```

Those four paragraphs alone hold G56, G57, G59, G82, G83, G84, G85, G86, G87. Overall **22 of Arm B's
30 Tier-2 misses are supplementary-figure assertions**, versus 4 of Arm A's 11. Arm A reads the PDF
linearly and has no such blind spot.

**2. Polarity flips.** Arm B mislabeled "only a small number of DEGs were identified" as an affirmative
induction rather than a stated absence (claims 38, 39 → G40–G42). Pass 1 fixes polarity from prose
alone and pass 2 never revisits it, because the legend has nothing to say about it. Arm B produced
3× as many `distorted` claims as Arm A (9 vs 3).

**3. Study-design leakage.** Table 1 is a design table stating no findings, but a per-panel loop is
obliged to emit something for it. All 4 of Arm B's Table 1 claims are design statements
("whole blood cells were used for FACS"), not findings. Arm A, reading linearly, never treats Table 1
as a claim source.

*Note:* the v6 production run has a worse version of this — 11 Table 1 claims that are verbatim
duplicates of its own Figure 1 claims, because the shared paragraph is attached to both panels. My
simpler Arm B prompt did **not** reproduce that; its 13 duplicates are all within-panel.

**4. Panel tunnel vision.** Cross-panel comparisons are hard to see one panel at a time. Arm B missed
G25 ("the difference in SBA magnitude was not as pronounced as that in ELISA binding titers"), which
spans Figure 1a and 1d.

## What Arm B did well

The two-pass legend reconciliation genuinely works *within* a panel. On Figure 1 it produced 35 claims
against a gold Tier 1 of 36, and correctly recovered the legend-only DT statement. Its Tier 1 recall of
0.829 is respectable. The failure is one of **coverage**, not of per-panel reasoning.

## Caveats

- **Arm A's precision is understated.** The judge flagged 2 of its 6 `unsupported` claims as real
  assertions the gold standard missed (myeloid DC involvement; day-7 persistence of the protein recall
  pattern). And 5 of its 12 `duplicate` claims are one pattern — it split "PDGFR-β signaling in YF-17D,
  MCV4 and MPSV4" per vaccine where the gold merged them into G55, a granularity disagreement rather
  than an error. True precision is nearer 0.80.
- **n = 1.** One paper, one run per arm, `temperature=0`. The recall gap (0.871 vs 0.576) is far larger
  than run-to-run noise would plausibly explain, but the precision gap is closer and less certain.
- **The gold standard is mine.** Tier 2 granularity in particular is a judgment call; that is why it is
  scored separately from Tier 1.
- Arm B is handicapped by `split_panels`, not only by its prompt. A JATS arm that fed whole Results
  sections (or swept up orphaned paragraphs) would likely close much of the Tier 2 gap.

## Verdict

**Reading the whole PDF with prose, panel and legend in view together is the better logic** — higher
recall, higher precision, fewer distortions, one call instead of fourteen, and half the tokens.

The per-panel pass structure's real weakness is not its reasoning but its **input coverage**: anything
the JATS panel-splitter fails to attach to a figure is invisible to it, and in this paper that is 29% of
the Results section. If the pass architecture is worth keeping for its within-panel precision, the fix
is to change what it is fed — attach supplementary-figure paragraphs, and add a sweep pass over
paragraphs that reference no main panel.

## Reproducing

```bash
.venv/bin/python scripts/exp_run_arm_a.py data/pdf/26papers/SDY1260_24336226.pdf \
    data/experiments/sdy1260_prompt_ab/arm_A
.venv/bin/python scripts/exp_run_arm_b.py data/claims/SDY1260_24336226_jats_figures/raw.xml \
    data/experiments/sdy1260_prompt_ab/arm_B
.venv/bin/python scripts/exp_score.py data/experiments/sdy1260_prompt_ab/arm_A
.venv/bin/python scripts/exp_score.py data/experiments/sdy1260_prompt_ab/arm_B
```
