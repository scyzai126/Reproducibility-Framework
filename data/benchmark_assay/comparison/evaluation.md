# Assay extraction & OBI mapping — evaluation against the curated benchmark

*Generated 2026-09-26 from the current registries (`data/31paper_assays/*/assays_benchmark.json` + `assays_OBI.json`, rewritten 2026-09-26 ~10:10) against the 31 curator files in `data/benchmark_assay/`. The row-by-row pairing is in `comparison.md` / `comparison.json` (re-generated for this report by `scripts/compare_assay_benchmark.py`, no LLM calls). Every non-exact row was then judged by hand. Those judgements are what this file adds.*

---

## 1. Headline

| Metric | Result | How it's computed |
|---|---:|---|
| **Assay capture (recall)** | **143 / 147 = 97.3%** | benchmark assays that appear in our final registry, by name or alias. The script also says 143, but for two offsetting reasons: it misses the SDY1264 YFV-neutralization row, which our registry has as CPE + PRNT without an OBI term; and it wrongly credits the SDY1654 proliferation assay, which it pairs with our plain flow-cytometry entry only through a curator alias (see §2) |
| Capture before the verifier | 144 / 147 = 98.0% | the verifier wrongly rejected one real assay (SDY1655). Full round-1 scoring: `evaluation_round1.md` |
| **OBI: exact same ID as curator** | **88 / 133 = 66.2%** | over captured assays where the curator gave an OBI ID |
| **OBI: correct after adjudication** | **96 / 133 = 72.2%** | exact, plus cases where our term is as good as or better than the curator's (curator ID errors, equally valid sibling terms, ours more specific) |
| **OBI: correct or right lineage** | **112 / 133 = 84.2%** | adds cases where our term is a correct *ancestor* of the curator's (e.g. `RNA sequencing assay` vs `bulk RNA-seq assay`) |
| **OBI: clearly wrong or unmapped** | **21 / 133 = 15.8%** | see §3; 20 of the 21 come from 4 repeating patterns |
| **End-to-end** (captured *and* correct OBI) / all 147 | **101 / 147 = 68.7%** strict · **119 / 147 = 81.0%** lenient | strict = exact or ours-as-good; lenient adds ours-broader-but-correct. The 9 captured rows where the curator gave no OBI ID are judged by hand (5 correct, 2 broader, 2 wrong) |
| `generate_claim` agreement | 121 / 128 = 94.5% | on matched rows where the curator filled it in (14 are `null` in the benchmark). All 7 disagreements: we said `true` 5 times where the curator said `false`, and `false` twice where the curator said `true` |

**Bottom line.** **Extraction is strong.** We find almost every assay the curator listed, and each of the 4 misses has a specific cause. **OBI mapping is the weaker step.** About a third of our terms differ from the curator's. Half of those differences are defensible granularity choices. The other half are 21 real errors, and almost all of them are the mapper picking the **technology** term (`microarray assay`, `flow cytometry assay`, `real time PCR`) instead of the **purpose** term the curator uses (`transcription profiling by array`, `ICS` / `proliferation`, `real time RT-PCR`). Every curator term involved is in our 700-term retrieval pool, so these are selection errors, not coverage gaps.

Caveat: the benchmark is a recall reference, not an exhaustive list, so no precision is reported. Our 20 extra assays are judged in §5, and ~17 of them are real assays the curator did not list.

---

## 2. Extraction — the 5 misses (4 true, 1 pairing-only)

| Study | Benchmark assay | What happened | Stage at fault |
|---|---|---|---|
| SDY1264 | Assay for YFV neutralizing antibodies (OBI:0003796) | **Extracted** as two entries, `cytopathic effect (CPE)` and `plaque reduction neutralization test (PRNT)`, but both were left **without an OBI term**, so they could not pair with the curator's `pathogen neutralization assay`. The pool has `pathogen neutralization assay` and `viral plaque assay`. | OBI mapping, not extraction |
| SDY1655 | Human Cytokine/Chemokine Array 71-403 Plex (HD71) | Extracted with normalized name "multiplex bead immunoassay". The verifier then **rejected** it as "a product/panel name rather than an assay technique" (`assays_rejected.json`). The multiplex cytokine measurement is a real assay. | Verifier (false reject) |
| SDY180 | Commercial immunoassays (pneumococcal polysaccharide antibody) | Not in any registry file. It is one short sentence ("Antibody response to 14 pneumococcal polysaccharides was measured by using commercial immunoassays"), and the assay is never named. | Extractor (vague wording) |
| SDY2189 | Single-molecule array (SIMOA) | Not in any registry file. It is mentioned only in passing in Results ("…just over the assay limit of the highly sensitive single-molecule array (SIMOA)"). | Extractor (Results-only mention) |
| SDY1654 | proliferation assay (OBI:0000891) | Not extracted as an assay. Our only flow entry covers surface-marker and NME1 staining, and its evidence sits in the section "Flow cytometry and proliferation assays". The comparison script counts it as found only because the curator listed "NME1 protein expression by flow cytometry" among the proliferation assay's aliases. | Extractor (sub-assay under a shared heading) |

### Capture that is real but collapsed

Round 5 (canonicalize) **merges every entry that maps to the same OBI term**. When the mapper picks a generic term, distinct assays end up folded into one entry. The curator's assay is still "captured" (its wording survives in `name_in_paper`), but it no longer has its own row, evidence or term. Across the 31 papers, **15 benchmark assays share an entry with another benchmark assay**. The costly cases:

- **SDY1289**: Ki67 proliferation, CFSE labeling, ICS, Th1/Th2 phenotyping and MIMIC co-culture flow → one `flow cytometry assay` entry (5 benchmark rows → 1).
- **SDY1640**: ex vivo phenotyping + **AIM assay** + **ICS** → one `flow cytometry assay`.
- **SDY1288 / SDY1328**: the **multiplex Luminex cytokine** panel was mapped to `ELISA` and merged into the antibody-ELISA entry.
- SDY1630, SDY1389: NK functional / T cell proliferation assays folded into `flow cytometry assay`.

Some merges are harmless: two ELISPOTs in SDY984, two ELISAs in SDY1640. The harm comes from the generic mapping upstream (§3 pattern B). The merge only makes it permanent.

---

## 3. OBI mapping — where we differ from the curator

All 46 non-exact rows where the curator gave an OBI ID, grouped by cause:

### Our errors (21)

| # | Pattern | Rows | Our term → curator's term | Studies |
|---|---|---:|---|---|
| A | **Expression array mapped to the platform, not the purpose** | 12 | `microarray assay` OBI:0001985 → `transcription profiling by array assay` OBI:0001463 (unrelated in OBI's is_a tree, so it is not even an ancestor) | SDY1276 ×2, SDY1289 ×2, SDY1291, SDY1293, SDY1294, SDY1328, SDY1364, SDY180, SDY80, SDY984 |
| B | **Functional flow assay mapped to plain flow cytometry** | 4 | `flow cytometry assay` → CFSE staining (OBI:0002106), immuno staining / cytokine assay for **ICS** (OBI:0001632, OBI:0002766), IFN-γ production (OBI:1110207) | SDY1289, SDY1640, SDY2189, SDY1630 |
| C | **qPCR on RNA mapped without the reverse-transcription step** | 3 | `real time PCR` OBI:0000893 → `real time RT-PCR` OBI:0000911 | SDY1291, SDY1293, SDY2189 |
| D | **Multiplex bead cytokine panel mapped to ELISA** | 1 (+1 below) | `ELISA` → `cytometric bead array assay` | SDY1328 (and SDY1288, where the curator gave no ID) |
| E | **Left unmapped though a pool term exists** | 1 | `complete blood count` → none; curator `hematology assay` OBI:0000630 | SDY1328 |

(SDY1264's CPE/PRNT, left unmapped though `pathogen neutralization` / `viral plaque` terms exist, belongs in pattern E too. It is counted as the §2 miss.)

### Ours broader, but in the right lineage (16)

| Our term | Curator's (more specific) term | Rows | Studies |
|---|---|---:|---|
| `RNA sequencing assay` OBI:0001177 | `RNA-seq assay` / `bulk RNA-seq` / `scRNA-seq` | 8 | SDY1373, SDY1630, SDY1654, SDY1708, SDY1991, SDY1995, SDY2189, SDY1288 (ours `RNA-seq assay` vs bulk) |
| `proximity extension assay` | `Olink assay` | 2 | SDY1669, SDY2189 |
| `flow cytometry assay` | `T cell activation induced marker assay` (AIM) | 1 | SDY1640 |
| `cytometric bead array assay` | `analyte detection by flow based bead assay` | 1 | SDY1640 |
| `serum neutralization of viral infectivity` | `96-well neutralization assay` | 1 | SDY80 |
| `pathogen neutralization assay` | `serum neutralization of viral infectivity assay` | 1 | SDY1276 |
| `genotyping assay` | `genotyping by array assay` | 1 | SDY1276 |
| `polymerase chain reaction assay` | `real time PCR assay` | 1 | SDY1669 |

These are not wrong, but they lose detail the paper states outright ("single-cell", "bulk", "Olink"). Note that the mapper is inconsistent here: it picks OBI:0001177 in most papers but OBI:0001271 in SDY1288 for the same kind of assay.

### Ours as good as or better than the curator's (8)

| Study | Ours | Curator | Judgement |
|---|---|---|---|
| SDY1260, SDY1264 | `microarray assay` | OBI:0002631 **single-cell RNA sequencing assay** for a row keyed "microarray" | **Curator ID error** |
| SDY212 | `genotyping by SNP array` | `genotyping by array` | Ours more specific and correct |
| SDY1389 | `T cell receptor repertoire sequencing` | `amplicon sequencing` | Ours more specific (TCR-Vβ amplicons) |
| SDY1995 | `reverse transcription PCR` | `real time RT-PCR` | The paper describes conventional RT-PCR, so ours fits better |
| SDY1291 / SDY1373 | `multiplex bead-based protein state immunoassay` ↔ `cytometric bead array assay` | the reverse, in each paper | Sibling terms. The curators themselves use them interchangeably |
| SDY1294 | `immuno staining assay` | CHMO:0000087 `fluorescence microscopy assay` (not an OBI ID) | Both defensible |

### Rows where the curator gave no OBI ID (9)

We mapped 5 correctly (SBA → `bacterial neutralization` ×2, flow cytometry, TLR4 reporter → `reporter cell line analyte detection bioassay`, and lateral flow → none, since no term exists). We mapped 2 to broader terms (bulk RNA-seq → `RNA sequencing assay` ×2) and 2 wrongly (multiplex Luminex → `ELISA`; T cell proliferation → `flow cytometry`).

---

## 4. Per-paper table

"OBI broader" = our term is an ancestor of the curator's. "OBI differs" = conflict, or one side has no ID (before the hand adjudication in §3). "Shared" = benchmark assays paired onto an entry already used by another benchmark assay.

| Study | PMID | Input | Bench | Ours | Captured | Missed | Extra | OBI exact | OBI broader | OBI differs | Shared |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SDY1260 | 24336226 | text | 6 | 6 | 6 | 0 | 0 | 4 | 0 | 2 | 0 |
| SDY1264 | 19029902 | text | 4 | 9 | 3 | 1 | 6 | 2 | 0 | 1 | 0 |
| SDY1276 | 21357945 | PDF | 3 | 3 | 3 | 0 | 0 | 2 | 0 | 1 | 0 |
| SDY1276 | 23878721 | text | 4 | 4 | 4 | 0 | 0 | 1 | 1 | 2 | 0 |
| SDY1288 | 30150281 | text | 5 | 6 | 5 | 0 | 2 | 3 | 1 | 1 | 1 |
| SDY1289 | 19047440 | text | 12 | 6 | 12 | 0 | 0 | 9 | 0 | 3 | 6 |
| SDY1291 | 23151505 | PDF | 4 | 4 | 4 | 0 | 0 | 1 | 0 | 3 | 0 |
| SDY1293 | 20078211 | PDF | 2 | 3 | 2 | 0 | 1 | 0 | 0 | 2 | 0 |
| SDY1294 | 28687661 | text | 4 | 5 | 4 | 0 | 1 | 2 | 0 | 2 | 0 |
| SDY1325 | 28137280 | text | 5 | 5 | 5 | 0 | 0 | 3 | 0 | 2 | 0 |
| SDY1328 | 26742691 | text | 4 | 4 | 4 | 0 | 0 | 1 | 0 | 3 | 0 |
| SDY1364 | 23266342 | text | 3 | 3 | 3 | 0 | 0 | 3 | 0 | 0 | 0 |
| SDY1364 | 23844129 | text | 5 | 5 | 5 | 0 | 0 | 4 | 0 | 1 | 0 |
| SDY1373 | 28854372 | text | 4 | 4 | 4 | 0 | 0 | 2 | 1 | 1 | 0 |
| SDY1389 | 30111633 | text | 5 | 5 | 5 | 0 | 1 | 2 | 0 | 3 | 1 |
| SDY1393 | 36656789 | text | 3 | 3 | 3 | 0 | 0 | 3 | 0 | 0 | 0 |
| SDY1596 | 32005538 | text | 2 | 3 | 2 | 0 | 1 | 2 | 0 | 0 | 0 |
| SDY1630 | 32059780 | text | 3 | 2 | 3 | 0 | 0 | 1 | 1 | 1 | 1 |
| SDY1640 | 32473127 | text | 6 | 5 | 6 | 0 | 1 | 2 | 2 | 2 | 2 |
| SDY1654 | 31624246 | text | 4 | 3 | 4 | 0 | 0 | 2 | 1 | 1 | 1 |
| SDY1655 | 32717743 | text | 3 | 3 | 2 | 1 | 1 | 2 | 0 | 0 | 0 |
| SDY1669 | 32788292 | text | 7 | 8 | 7 | 0 | 1 | 3 | 2 | 2 | 0 |
| SDY1708 | 34128959 | text | 3 | 3 | 3 | 0 | 0 | 2 | 1 | 0 | 0 |
| SDY180 | 23601689 | text | 6 | 5 | 5 | 1 | 0 | 4 | 0 | 1 | 0 |
| SDY1991 | 35455361 | text | 4 | 6 | 4 | 0 | 3 | 3 | 1 | 0 | 1 |
| SDY1995 | 35062294 | text | 4 | 4 | 4 | 0 | 0 | 2 | 1 | 1 | 0 |
| SDY212 | 25834109 | text | 7 | 7 | 7 | 0 | 0 | 6 | 1 | 0 | 1 |
| SDY2189 | 34252919 | text | 10 | 9 | 9 | 1 | 0 | 5 | 2 | 2 | 0 |
| SDY404 | 25367297 | PDF | 3 | 3 | 3 | 0 | 0 | 3 | 0 | 0 | 0 |
| SDY80 | 24725414 | text | 4 | 4 | 4 | 0 | 0 | 2 | 1 | 1 | 0 |
| SDY984 | 28502771 | text | 8 | 9 | 8 | 0 | 2 | 7 | 0 | 1 | 1 |
| **Total** | | | **147** | **149** | **143** | **4** | **20** | **88** | **16** | **39** | **15** |

**Text vs. PDF input.** PDF (4 papers): 12/12 captured, 6/12 exact OBI. Text (27 papers): 131/135 captured, 82/122 exact OBI. The lower PDF rate comes from patterns A and C, not from the input format, and n is small.

Two small artifacts of the pairing script: the SDY1991 "IFN-γ Capture Assay" row was paired by OBI ID to our flow cytometry entry, while our same-named but unmapped entry shows as EXTRA. The SPLIT rows in SDY1276 and SDY212 pick up a second, unrelated partner via a shared broader term. Neither changes the counts above. The table is the script's raw output, so it still shows SDY1264 as 3 captured (really 4) and SDY1654 as 4 captured (really 3); §1 and §2 carry the corrected figures.

---

## 5. The 20 extra assays (ours, not in the benchmark)

| Judgement | Count | Examples |
|---|---:|---|
| Real assay the benchmark omitted | 17 | SDY1264: RT-PCR validation, immunofluorescence, immunoblot, C3a ELISA, CPE, PRNT · SDY1288: virus isolation, viral RT-PCR · SDY1293: malaria thick-smear microscopy · SDY1294: NK ADCC · SDY1596: culturable CFU count · SDY1640: viral PCR · SDY1669: intracellular staining flow · SDY1991: diagnostic RT-PCR, flow neutralization · SDY984: amplicon sequencing · SDY1389: HLA-multimer staining (real assay, but named after the reagent) |
| Duplicate / sub-step | 2 | SDY984 tandem MS-MS (a confirmation step inside the LC-MS metabolomics entry) · SDY1991 IFN-γ Capture Assay (pairing artifact, see §4) |
| Weak evidence | 1 | SDY1655 ELISA: its quote is the sentence introducing the flow cytometry analysis, so the entry needs checking against the paper |

Many of the real extras are **diagnostic or confirmatory** assays (virus isolation, diagnostic RT-PCR, thick smears). The curators seem to leave these out on purpose. If we want to match the curators, that scope rule should go into the extraction prompt. If not, these are fine.

---

## 6. Recommended fixes (by expected gain)

1. **Mapper: prefer the purpose term over the platform term** (fixes pattern A, 12 rows, +9 pp on exact OBI). When the readout is gene expression, `transcription profiling by array assay` should win over `microarray assay`. Likewise `real time RT-PCR` should win over `real time PCR` when the template is RNA (pattern C, 3 rows). This is a mapping-prompt rule plus a readout-aware re-rank. Both terms are already in the pool.
2. **Mapper: map functional flow assays to their specific terms** (pattern B, AIM, T cell proliferation; ~8 rows). The pool already has ICS-, CFSE-, AIM- and proliferation-type terms. Because round 5 merges by OBI term, this fix also stops SDY1289/SDY1640-style collapses.
3. **Mapper: multiplex cytokine panels (Luminex, Bio-Plex, LEGENDplex, Eve Technologies) → a bead-array term, never `ELISA`** (pattern D, 2 rows). Consider also not letting round 5 merge an entry whose `readouts` differ sharply from its merge partner's.
4. **Mapper: prefer the most specific RNA-seq term the paper states** (bulk / single-cell / RNA-seq), and use one consistent choice between OBI:0001177 and OBI:0001271 (8 rows now "broader").
5. **Mapper: stop leaving obvious terms unmapped.** CPE / PRNT → `pathogen neutralization` / `viral plaque assay`, complete blood count → `hematology assay`. The SDY1264 "miss" is really this.
6. **Verifier: do not reject an assay because it is named after a commercial panel** (SDY1655). The rejection reason should apply to reagents, not to measurements.
7. **Extractor: catch assays named only in Results, only by what they measure, or only as a sub-assay under a shared heading** (SIMOA, "commercial immunoassays", the SDY1654 proliferation assay). This is lower priority: 3 rows.
8. **Benchmark hygiene** (for the curators): SDY1260 and SDY1264 give the scRNA-seq ID for a microarray; 10 rows have no OBI ID; one uses a CHMO ID; and the curators split between OBI:0000920 and OBI:0002970 for the same kind of bead assay. Fixing these would make the exact-match number more trustworthy.

If fixes 1–5 worked as intended, exact OBI agreement would rise from ~66% to roughly 80–90% on this set. Extraction recall is already near its ceiling.
