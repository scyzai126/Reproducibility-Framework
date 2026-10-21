# Assay pipeline: 31-paper re-run with the 2026-10-19 workflow

All 31 benchmark papers were re-run with the current pipeline (commits `09a94f3`…`4c1726e` on
`feature/immport-llm-fallback`: 3-way voted extraction, `return_exceptions` on round 1,
word-boundary alias check, never-fold-on-`identity_review`; the BROAD fold rule was tried and
withdrawn the same day). Output: `data/31paper_assays/stability/<pmid>_<SDY>/`, one folder per
paper; every other folder that used to live under `stability/` was removed first. The scored
`data/31paper_assays/assay_result_v1/` was not touched.

- SDY2189, SDY1640, SDY1655 were run singly earlier in the day (44 + 31 + 18 calls).
- The other 28 ran sequentially in one batch: **707 calls, 11 minutes, 0 failures**
  (estimate was ~679).

## Score against `benchmark_assay_v4` (comparator run in memory; nothing under `comparison/` rewritten)

| | benchmark rows | agent entries | matched | exact OBI | missed | extra | recall | exact / bench |
|---|---|---|---|---|---|---|---|---|
| OLD `assay_result_v1` | 155 | 151 | 149 | 134 | 6 | 2 | 0.961 | 0.865 |
| NEW `stability` | 156 | 154 | 149 | 128 | 7 | 3 | 0.955 | 0.821 |

(The benchmark-row count differs by one because the comparator folds leftover curated rows onto
a paired row with the same OBI id, and that depends on what the agent produced — a known
comparator artefact, see the Tier 3 notes in the plan.)

**Net: recall flat (149 matched both ways), exact-term agreement down 6.** 19 papers are
identical; 12 changed. The changes are dominated by two things today's code did not set out to
change — OBI-picker variance between runs, and the vote dropping 1-of-3 entries — plus one
visible cost of the new "keep, never fold" policy for doubted identities.

### Papers that improved
| paper | change | cause |
|---|---|---|
| SDY1654 | +1 matched (proliferation assay now found) | extraction |
| SDY1655 | +1 matched (HD71 panel kept), −1 extra (ELISA no longer extracted) | judge ruled HD71 SUPPORTED this time; prompt from `281e006` |
| SDY1991 | −1 extra (IFN-γ Capture Assay gone) | extraction |
| SDY1264 | +1 exact (RT-PCR term) | OBI picker |
| SDY1393 | +1 exact (bulk RNA-seq) | OBI picker |

### Papers that got worse
| paper | change | cause |
|---|---|---|
| SDY1288 | −2 matched: `virus isolation` (1 of 3 extractions → MINORITY, not delivered); `viral titer assays` now extracted as a wording of real-time RT-PCR instead of its own entry, so the curated `One-Step RT-PCR` row has nothing to pair with | vote; extraction |
| SDY984 | −1 matched (`tandem MS-MS` → MINORITY 1 of 3); +2 extra (`nested PCR analysis` newly extracted; CBA now mapped to OBI:0003799 so it no longer folds with the multiplex on OBI:0000920) | vote; extraction; OBI picker |
| SDY1328 | multiplex ELISA now found (+1 matched) but `commercially available kit` (identity NOT_SUPPORTED → REVIEW UNFOLDED) scores as SPLIT, and `MONOLISA Anti-HBs kit` → `surface HBV antibody assay` is EXTRA; −2 exact | never-fold policy; extraction; OBI picker |
| SDY1630 | `measuring degranulation by NK cells` (REVIEW UNFOLDED) scores as SPLIT; −1 exact | never-fold policy |
| SDY1289 | `lysis plaque assay` not extracted; CBA term one level more specific than curator's | extraction; OBI picker |
| SDY1293, SDY1294 | one OBI-term conflict each (real-time PCR; immunofluorescence) | OBI picker |

### Reading
- The 3-way vote with identical calls behaves as the review predicted: it removes 1-of-3 noise
  (Trypan blue, a stray flow panel, a Results-only CPE) but also drops 1-of-3 *hits* the curator
  counts (`virus isolation`, `tandem MS-MS`). Nine MINORITY lines in 28 papers; at least two were
  real assays.
- Exact-term agreement moved on 9 papers with no extraction change — the OBI picker is the
  largest source of run-to-run variance, as the Tier 2/3 notes said.
- REVIEW UNFOLDED does what it was meant to (a doubted name never becomes a supported entry's
  name), but the comparator scores the resulting second entry on the same term as SPLIT. Both
  cases (SDY1328, SDY1630) are purpose phrases / product descriptions the judge was right about.

## Every flagged line, by paper (28-paper batch)

Totals: 39 REVIEW · 14 MERGED · 9 MINORITY · 3 UNMAPPED · 3 REVIEW UNFOLDED · 1 CORRECT FAILED ·
1 CORRECT REFUSED · 0 WARNING / REJECT / DROPPED / EXTRACT FAILED / ERROR.
(REVIEW = the judge did not support ≥1 field; identity SUPPORTED unless stated. Pre-correction verdicts.)

**SDY1264** — REVIEW plaque reduction neutralization test · MINORITY neutralizing antibodies by CPE (1/3) · MERGED plaque reduction neutralization test → serum neutralization of viral infectivity assay · CORRECT FAILED plaque reduction neutralization test / sample_type: JSONDecodeError (unterminated string)
**SDY1289** — REVIEW IL-1β ELISA · REVIEW BD Th1/Th2 CBA array · REVIEW FACS analysis · MERGED FACS analysis, CD4+ T cell stimulation assay → flow cytometry assay
**SDY1293 (PDF)** — REVIEW Real-time polymerase chain reaction
**SDY1276 / 21357945 (PDF)** — REVIEW Microarray Analysis · REVIEW Hemagglutination inhibition (HAI) tests
**SDY1291 (PDF)** — REVIEW Affymetrix Exon Arrays · REVIEW Agilent 3′ Arrays · REVIEW Quantitative Real-Time PCR · MINORITY PBMC supernatants multiplex cytokine analysis (1/3) · MERGED Agilent 3′ Arrays → transcription profiling by array assay
**SDY1364 / 23266342** — MERGED chemokine receptor surface staining → flow cytometry assay
**SDY180** — REVIEW Hemagglutinin Inhibition · REVIEW Virus-neutralization assays
**SDY1276 / 23878721** — REVIEW Hemagglutination inhibition tests
**SDY1260** — REVIEW cytokine ELISA · MERGED cytokine ELISA → enzyme-linked immunosorbent assay · MERGED DC activation flow cytometry → flow cytometry assay
**SDY80** — REVIEW flow cytometric analyses
**SDY404 (PDF)** — REVIEW Western Blot Analysis
**SDY212** — REVIEW ELISA · REVIEW Quantification of IAV in infected lung tissue (identity NOT_SUPPORTED) · MERGED phosphoflow analysis → flow cytometry assay · REVIEW UNFOLDED Quantification of IAV in infected lung tissue: "a section heading describing a purpose/end-point rather than a technique name"
**SDY1328** — REVIEW GM1-ELISA · REVIEW MONOLISA Anti-HBs PLUS kit · REVIEW commercially available kit (identity NOT_SUPPORTED) · REVIEW microarray · REVIEW multiplex ELISA protocol Human Inflammation multianalyte profiling · MINORITY commercially available kit for Anti-Tetanus IgG (1/3) · REVIEW UNFOLDED commercially available kit: "too vague to identify a specific assay technique" · UNMAPPED complete blood count · UNMAPPED multiplex ELISA protocol Human Inflammation multianalyte profiling
**SDY1325** — REVIEW microarray · REVIEW flow cytometric characterisation of B cells and plasma cells · REVIEW Quantitative real-time PCR
**SDY984** — MINORITY tandem MS-MS experiments (1/3) · MERGED Zostavax-specific and total IgG B cell ELISPOT → enzyme-linked immunospot assay
**SDY1294** — REVIEW NK-mediated ADCC assay · REVIEW plaque reduction neutralization test (PRNT) · MINORITY plaque reduction neutralization test (1/3; a second wording) · MERGED T cell function → flow cytometry assay
**SDY1389** — REVIEW Human T cell receptor (TCR) sequencing and analysis
**SDY1288** — REVIEW multiplex ELISA · MINORITY virus isolation (1/3) · MERGED real-time RT–PCR → real time reverse-transcription PCR assay · MERGED Inhibition ELISA → enzyme-linked immunosorbent assay
**SDY1654** — REVIEW flow cytometry
**SDY1596** — MINORITY Whole blood assay (1/3) · MINORITY cytokine/chemokine measurements (1/3) · MERGED Bacterial viability stain → flow cytometry assay · UNMAPPED culturable microbial count assay
**SDY1630** — REVIEW measuring degranulation by NK cells (identity NOT_SUPPORTED) · MERGED High-dimensional flow cytometric analysis of NK cell subsets, In vitro cytokine stimulation and functional assays of NK cells → flow cytometry assay · REVIEW UNFOLDED measuring degranulation by NK cells: "a purpose clause/readout description rather than a clearly named assay technique"
**SDY1669** — REVIEW PCR quantitation of bacterial 16S rRNA · REVIEW TLR4-based reporter assay · REVIEW highly sensitive ELISA enabled by SIMoA · MERGED SIMoA ELISA → enzyme-linked immunosorbent assay · CORRECT REFUSED TLR4-based reporter assay / evidence: replacement quote not in document
**SDY1995** — REVIEW anti-DENV IgG and IgM ELISA · REVIEW Reverse transcription-PCR
**SDY1991** — REVIEW DENV-specific IgG ELISAs · REVIEW flow cytometry-based neutralization assays · MINORITY flow cytometry (1/3)
**SDY1373, SDY1393, SDY1708, SDY1364 / 23844129** — no flagged lines.

Earlier single runs: **SDY2189** — 3 REVIEW, 1 MINORITY (plasma IFNγ ELISA), 1 MERGED (two FRNT
write-ups, after the BROAD rule was withdrawn); **SDY1640** — 2 MERGED, 1 UNMAPPED (lateral flow
assay); **SDY1655** — 1 MINORITY (Trypan blue), 1 MERGED.

## Files
- Per-paper outputs: `data/31paper_assays/stability/<pmid>_<SDY>/assays_benchmark.json`
  (deliverable), `assays.json`, `assays_OBI.json`, `assays_raw.json`, `assays_minority.json`.
- Nothing committed; `data/benchmark_assay/comparison/benchmark_vs_agent.json` is still the
  pre-`281e006` scoring and is stale for at least SDY1640.
