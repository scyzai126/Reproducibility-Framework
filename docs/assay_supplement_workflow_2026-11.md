# Supplement workflow on the benchmark papers — 2026-11-20

`scripts/run_assay_pipeline.py --supplement` reads main text + supplement as one document
(`docs/plan/assay_supplement_workflow_plan.md`). This is its first run over the 31 benchmark
papers.

## Result

**No assay was evidenced from a supplement in any of the 10 papers that could be run.** Not one
entry carries `in_supplement: true`, and the run printed no `SUPPLEMENT` line. Against the
curated benchmark the supplement workflow scores slightly below the main-text workflow on the
same papers, and neither difference comes from the supplement.

| 10 papers, strict scorer | main text (`assay_result_v3`) | supplement (`assay_supplement_v1`) |
|---|---|---|
| benchmark assays | 50 | 50 |
| agent entries | 56 | 55 |
| matched | 50 | 49 |
| exact OBI term | 46 | 45 |
| missed | 0 | 1 |
| extra | 1 | 2 |
| split | 4 | 3 |
| recall | 100% | 98.0% |
| precision (matched / agent entries) | 89.3% | 89.1% |

Precision "without `SUPPLEMENT` entries" is the same number: there are none.

Cost: $3.76 for the 10 papers (ledger rows of 2026-11-20), 264 calls by the script's count.
A first run of SDY1373 on the earlier wording of the prompt cost a further $0.27.

## What differs from the main-text result

Eight of the ten papers deliver the same entries under the same keys. The two that do not:

- **SDY1288 (30150281): 6 entries, was 8; one benchmark assay now missed.** `virus isolation`
  (S155, a benchmark row) is not extracted. `CHIKV viral titer assays` is no longer an entry of
  its own: two of three extractions made it an alias of real-time RT–PCR, and the third's
  `viral titer assays` is the `MINORITY` line below. Both passages are main-text Methods.
- **SDY1328 (26742691): 8 entries, was 7.** New: `Anti-Tetanus IgG kit` →
  `antigen specific antibodies assay` (S154, main-text Methods). The benchmark does not list it,
  so it scores as an extra.

Seven entries elsewhere kept their key and moved their quote to a neighbouring main-text
sentence (SDY1289 ×3, SDY1288 ×2, SDY1654 ×2, SDY1640 ×1), and SDY1995's RT-PCR quote, unplaced
in v3, is now placed at S33.

None of these involves supplement text. They are what a different prompt and a re-extraction
change; the main-text workflow re-run on the same papers would be the control that separates the
two, and it was not run.

## Why the supplements added nothing here

- **Only 3 of the 10 have supplementary methods the heading rule found** (SDY1373, SDY1288,
  SDY1393). In all three the main text has a full Methods section and the supplement repeats or
  extends it. The other 7 contributed figure legends and table notes only.
- **The papers whose methods live in the supplement could not be run.** SDY1669 (no Methods
  section in the XML at all), SDY1264, SDY180 and SDY1260 have no supplement text on disk yet.
- **The quote rule points at the main text.** After the first SDY1373 run moved ELISA's evidence
  to a figure fragment in the supplement ("d 14,28,56,84,180 ELISA An9body level"), the prompt
  was changed: a technique the main text states was performed is quoted from the main text. The
  re-run put ELISA back on its main-text sentence. A supplement quote now means the main text
  could not have evidenced the assay — and on these 10 papers that never happened.

## Every line the runs printed

Full logs: `data/benchmark_agent_assays/assay_supplement_v1/logs/<pmid>_<SDY>.log`. All ten:
every quote verbatim, none miscited or missing, every entry source-aligned; no `WARNING`,
`REJECT`, `DROPPED`, `MERGED`, `UNMAPPED` or `SUPPLEMENT` line.

**SDY1289 (19047440)** — 9 entries, $0.55
- REVIEW gene array analysis of whole-blood and VaxDesign samples → transcription profiling by array assay (identity SUPPORTED)
- REVIEW qPCR validation → real time reverse-transcription polymerase chain reaction assay (identity SUPPORTED)
- REVIEW cytometric bead assay → analyte detection by flow based bead assay (identity SUPPORTED)
- MINORITY Ki67 flow cytometry: 1 of 3 extractions; not delivered
- VOTE flow cytometry of long-term vaccine-specific CD4+ T helper phenotype → flow cytometry assay (2): 2 of 3; delivered
- REVIEW not folded: flow cytometry of long-term vaccine-specific CD4+ T helper phenotype kept apart from flow cytometry assay (readouts differ) — JUDGED DIFFERENT: short-term cytokine/activation markers after 6 h stimulation vs a marker set defining long-term central memory Th1/Th2 phenotype
- REVIEW not folded: CD4+ T cell stimulation assay kept apart from flow cytometry assay (sample_type: PBMC vs CD4 positive T cells) — JUDGED DIFFERENT: specimens and marker panels differ

**SDY1364 (23844129)** — 5 entries, $0.26. No flagged line.

**SDY1328 (26742691)** — 8 entries, $0.56
- REVIEW commercially available kit → enzyme-linked immunosorbent assay (2) (identity NOT_SUPPORTED)
- REVIEW Anti-Tetanus IgG kit → antigen specific antibodies assay (identity SUPPORTED)
- REVIEW microarray → transcription profiling by array assay (identity SUPPORTED)
- REVIEW not folded: commercially available kit kept apart from enzyme-linked immunosorbent assay (readouts differ) — JUDGED DIFFERENT: anti-Cholera toxin B subunit IgG vs anti-Diphtheria IgG

**SDY1325 (28137280)** — 5 entries, $0.33
- REVIEW flow cytometric characterisation of B cells and plasma cells → flow cytometry assay (identity SUPPORTED)
- REVIEW Quantitative real-time PCR → real time reverse-transcription polymerase chain reaction assay (identity SUPPORTED)

**SDY1373 (28854372)** — 4 entries, $0.20
- REVIEW Cytokine and Chemokine Multiplex Analysis → cytometric bead array assay (identity SUPPORTED)

**SDY1288 (30150281)** — 6 entries, $0.56
- DROPPED ALIAS real-time RT–PCR: 'real-time reverse-transcription polymerase chain reaction' does not appear in the source text
- REVIEW IgM capture ELISA → enzyme-linked immunosorbent assay (identity SUPPORTED)
- REVIEW Inhibition ELISA → enzyme-linked immunosorbent assay (2) (identity SUPPORTED)
- REVIEW mass cytometry → cytometry time of flight assay (identity SUPPORTED)
- REVIEW multiplex ELISA → cytometric bead array assay (identity SUPPORTED)
- MINORITY viral titer assays: 1 of 3 extractions; not delivered
- REVIEW not folded: Inhibition ELISA kept apart from enzyme-linked immunosorbent assay (readouts: seroconversion vs anti-CHIKV antibody titer increase) — JUDGED DIFFERENT: IgM seroconversion by IgM capture ELISA vs >4-fold titer increase by inhibition ELISA

**SDY1654 (31624246)** — 4 entries, $0.43
- REVIEW flow cytometry → flow cytometry assay (identity SUPPORTED)
- MINORITY intracellular staining of NME1: 1 of 3 extractions; not delivered
- VOTE proliferation assays → cell proliferation assay: 2 of 3; delivered

**SDY1640 (32473127)** — 7 entries, $0.41
- VOTE lateral flow assay → single-value binding of antibody with reporter to antigen assay: 2 of 3; delivered
- REVIEW not folded: OC43 and NL63 coronavirus RBD ELISA kept apart from enzyme-linked immunosorbent assay (sample_type: plasma vs serum) — JUDGED DIFFERENT: different RBD antibody analytes and different specimens
- REVIEW not folded: Intracellular cytokine staining assay kept apart from flow cytometry assay (readouts differ) — JUDGED DIFFERENT: leukocyte subset frequencies vs peptide-stimulated intracellular cytokine production in CD8+ T cells

**SDY1995 (35062294)** — 4 entries, $0.24
- REVIEW anti-DENV IgG and IgM ELISA → enzyme-linked immunosorbent assay (identity SUPPORTED)
- REVIEW Reverse transcription-PCR → reverse transcription polymerase chain reaction assay (identity SUPPORTED)

**SDY1393 (36656789)** — 3 entries, $0.23
- REVIEW flow cytometry → flow cytometry assay (identity SUPPORTED)
- REVIEW RNA-seq → bulk RNA-seq assay (identity SUPPORTED)

## The 21 papers not run

- **PDF only, no JATS XML (4):** SDY1293, SDY1276 (21357945), SDY1291, SDY404.
- **Supplement to be downloaded by hand (13):** SDY1264, SDY180, SDY80, SDY212 (25834109),
  SDY984, SDY1294, SDY1389, SDY1630, SDY2189, SDY1260, SDY1596, SDY1655, and SDY1669 (on the
  publisher's site). List: `docs/supplement_manual_downloads.xlsx`.
- **Supplement has no readable text (4):** SDY1364 (23266342), SDY1276 (23878721), SDY1708,
  SDY1991 — tables and images only, or no supplement at all.

## Addendum, same day: SDY1669 (32788292), the one paper with no main-text Methods

Its supplement was downloaded by hand from the publisher and re-read: 24,618 characters of
supplementary methods found ("Materials and Methods" / "Methods"), 41,621 characters of
supplement in a 74,019-character document. Cost $0.54, 45 calls by the script's count.

**This is the one paper where the supplement changed the outcome.** 10 entries against the
main-text workflow's 8, and all 9 benchmark assays matched where v3 matched 8:

- **Recovered: `Flow cytometry for immune cell phenotyping` → `flow cytometry assay (2)`** — the
  benchmark's "Flow cytometry analysis of PBMCs", which v3 missed. Quote: main-text Figure 5
  caption, S229.
- **Added: `highly sensitive ELISA enabled by single molecule array (SIMoA) technology` →
  `enzyme-linked immunosorbent assay (2)`** (S110). The benchmark has one ELISA row, so the
  scorer counts this as a split, not an extra.
- The other 8 are v3's entries on the same sentences, now named from the supplement's Methods
  headings ("Phospho-CyTOF analysis of peripheral blood mononuclear cells", "Bulk
  transcriptomics", "Quantitation of LPS in plasma") instead of the Results wording.

**No entry is marked `in_supplement`, and no `SUPPLEMENT` line was printed** — every quote is a
main-text sentence, as the quote rule requires. What the supplement supplied is the Pass 1
inventory: with a `[methods]` section to read, the paper is no longer structure 3, and the two
flow-cytometry measurements are separate Methods subsections there. So `in_supplement` does not
show this contribution; the entry names do. That it was the supplement and not the prompt or a
re-extraction is the likely reading, not a measured one — the control (the main-text workflow
re-run) was not made.

Lines printed: `VOTE` highly sensitive ELISA enabled by single molecule array (SIMoA)
technology → enzyme-linked immunosorbent assay (2), 2 of 3, delivered. `REVIEW not folded`
Flow cytometry for immune cell phenotyping kept apart from flow cytometry assay (readouts
differ) — `JUDGED DIFFERENT`: intracellular functional responses after TLR stimulation vs
baseline cell-surface phenotyping markers. `REVIEW not folded` SIMoA ELISA kept apart from
enzyme-linked immunosorbent assay (readouts differ) — `JUDGED DIFFERENT`: EN-RAGE, TNFSF14 and
OSM vs interferon-alpha. 10/10 quotes verbatim and source-aligned; verify 10 ACCEPT; no
`WARNING`, `REJECT`, `DROPPED`, `MINORITY`, `MERGED`, `UNMAPPED`.

The MDAR checklist PDF rode along as `[other]` text and produced no entry.

### All 11 papers

| strict scorer | main text (`assay_result_v3`) | supplement (`assay_supplement_v1`) |
|---|---|---|
| benchmark assays | 59 | 59 |
| agent entries | 64 | 65 |
| matched | 58 | 58 |
| exact OBI term | 54 | 54 |
| missed | 1 (SDY1669) | 1 (SDY1288) |
| extra | 1 | 2 |
| split | 4 | 4 |
| recall | 98.3% | 98.3% |
| precision (matched / agent entries) | 90.6% | 89.2% |

Total spent on the 11: $4.30, plus $0.27 for the first SDY1373 run.
