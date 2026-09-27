# Round-1 (extract-only) output vs. the curated benchmark

*Generated 2026-09-26. Here the agent's answer is taken to be the round-1 extraction alone, `data/31paper_assays/<pmid>_<SDY>/assays_precorrection.json`, before verify (round 2), correct (3), OBI mapping (4) and merge (5). It is scored against the same 31 curator files as `evaluation.md`. The row-level result is in `comparison_round1.json`. Pairing reuses the matching code of `scripts/compare_assay_benchmark.py`. No LLM calls were made.*

**Scope: extraction only.** Round 1 assigns no OBI terms, so there is nothing to score for OBI here. Pairing uses the name, alias, name-containment and quote tiers only. The model's own `normalized_name` counts as an extra alias. OBI results for the final registry are in `evaluation.md`.

---

## 1. Headline: round 1 vs. the final registry

| | Round 1 (extract) | Final (after rounds 2–5) |
|---|---:|---:|
| Entries in the registry | 171 | 149 |
| **Benchmark assays found (recall)** | **144 / 147 = 98.0%** | **143 / 147 = 97.3%** |
| True misses | 3 | 4 |
| Benchmark assays sharing an entry with another benchmark assay | 5 | 15 |
| Entries not in the benchmark (EXTRA) | 26 | 20 |
| `generate_claim` agreement (rows where the curator filled it in) | 122 / 130 = 93.8% | 121 / 128 = 94.5% |

The script's raw count is also 144 for round 1, but for two offsetting reasons, the same two as in the final run:
- It misses the SDY1264 YFV-neutralization row. Round 1 does have that assay, as `cytopathic effect (CPE)` + `plaque reduction neutralization test (PRNT)`, but neither name overlaps the curator's.
- It wrongly credits the SDY1654 proliferation assay. The pair comes only from a curator alias, "NME1 protein expression by flow cytometry", which contains "flow cytometry". Our entry is plain surface-marker flow cytometry.

**Bottom line.** Rounds 2–5 do not improve recall; they cost one assay. Round 1 already has everything the final registry has, plus the SDY1655 cytokine panel, which the verifier then rejected by mistake. What the later rounds do change is the **shape** of the registry. Two true non-assays are removed, and 19 entries are folded together. That fold collapses 10 benchmark assays that round 1 had kept as separate entries.

---

## 2. Round-1 misses (3 true)

| Study | Benchmark assay | Why round 1 missed it |
|---|---|---|
| SDY180 | Commercial immunoassays (pneumococcal polysaccharide antibody) | One vague sentence, and the assay is never named |
| SDY2189 | Single-molecule array (SIMOA) | Mentioned only in passing in Results. In SDY1669, round 1 *did* extract a SIMOA mention from Results, so round 1 is inconsistent here rather than following a rule |
| SDY1654 | proliferation assay | A sub-assay under the heading "Flow cytometry and proliferation assays". Round 1 took only the flow cytometry part |

The SDY1655 HD71 cytokine panel is **found** in round 1. It is missing from the final registry only because round 2 rejected it.

---

## 3. What rounds 2–5 changed

### Verifier rejections (round 2): 3 entries, 1 of them wrong

| Study | Entry | Verifier's reason | Judgement |
|---|---|---|---|
| SDY1655 | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | "a product/panel name rather than an assay technique name" | **Wrong.** It is a benchmark assay (serum cytokine measurement) |
| SDY1655 | Trypan blue staining | "a sample quality/quantity check" | Correct (cell-viability QC) |
| SDY1995 | cell sorting | "a sample-isolation step rather than an assay" | Correct |

In rounds 2–3, only the rejections changed which entries exist. Round 3 corrects fields inside entries but never adds or removes one.

### Merge by OBI term (round 5): 19 entries folded

Round 5 keys each entry by its OBI term and folds entries that share one. 171 − 3 rejected − 19 folded = 149 final entries.

About half of the folds are harmless. They combine a single assay written up twice:
- two ELISA write-ups (SDY1640 OC43/NL63 vs SARS-CoV-2 RBD, SDY1260 "ELISA" + "ELISA kits")
- two array platforms (SDY1291 Agilent + Affymetrix)
- the FRNT variant runs (SDY2189)
- CBA + multiplex cytokine (SDY984)

The rest remove distinctions the curator kept. The number of benchmark assays that share an entry with another benchmark assay rises from **5 in round 1 to 15 in the final registry**:
- **SDY1640**: round 1 has separate entries for *ex vivo phenotyping*, *Activation induced cell marker assay* and *Intracellular cytokine staining assay*. Round 5 folds all three into one `flow cytometry assay`.
- **SDY1630**: *NK functional assays* and *degranulation* are separate in round 1, then folded into flow cytometry.
- **SDY1389**: *T cell proliferation assays* is its own entry in round 1, then folded into flow cytometry.
- **SDY1288 / SDY1328**: the multiplex cytokine panel is its own entry in round 1 (`multiplex ELISA`), but round 1 already gives it the normalized name "ELISA". Round 4 follows that to the `ELISA` term, and round 5 folds it into the antibody-ELISA entry. Here the error starts at extraction, not at mapping.

This confirms the point in `evaluation.md` §1–3: the loss of detail mostly comes from round 4 choosing a generic OBI term, and round 5 makes it permanent. The round-1 extraction keeps the flow-based assays apart correctly. For multiplex panels, round 1's `normalized_name` is already too generic.

---

## 4. Round-1 extras (26)

| Group | Count | Entries |
|---|---:|---|
| Also extra in the final registry | 18 | SDY1264 CPE, PRNT, RT-PCR, immunofluorescence, immunoblot, C3a ELISA · SDY1288 virus isolation, viral titer RT-PCR · SDY1293 thick-smear microscopy · SDY1294 NK ADCC · SDY1389 HLA multimer · SDY1596 CFU count · SDY1640 viral PCR · SDY1655 ELISA · SDY1669 intracellular staining · SDY1991 diagnostic RT-PCR · SDY984 amplicon sequencing, tandem MS |
| Variants later folded into a matched entry by round 5 | 6 | SDY1288 IgM capture ELISA · SDY1291 Agilent arrays · SDY1328 anti-CTB ELISA · SDY1640 OC43/NL63 ELISA · SDY2189 FRNT against variants · SDY984 Cytokine Bead Array |
| True non-assays removed by the verifier | 2 | SDY1655 Trypan blue staining · SDY1995 cell sorting |

Round 1 therefore produces only **2 genuine false positives out of 171 entries (1.2%)**, and the verifier catches both. The other extras are real assays the benchmark does not list, as judged in `evaluation.md` §5.

---

## 5. Per-paper table

\* adjusted by hand as explained in §1: SDY1264 +1 (the script misses the pair), SDY1654 −1 (the script's pair is not real).

| Study | PMID | Bench | Round-1 entries | Rejected by verifier | Folded by round 5 | Final entries | Found (round 1) | Found (final) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| SDY1260 | 24336226 | 6 | 7 | 0 | 1 | 6 | 6 | 6 |
| SDY1264 | 19029902 | 4 | 9 | 0 | 0 | 9 | 4\* | 4\* |
| SDY1276 | 21357945 | 3 | 3 | 0 | 0 | 3 | 3 | 3 |
| SDY1276 | 23878721 | 4 | 4 | 0 | 0 | 4 | 4 | 4 |
| SDY1288 | 30150281 | 5 | 8 | 0 | 2 | 6 | 5 | 5 |
| SDY1289 | 19047440 | 12 | 8 | 0 | 2 | 6 | 12 | 12 |
| SDY1291 | 23151505 | 4 | 5 | 0 | 1 | 4 | 4 | 4 |
| SDY1293 | 20078211 | 2 | 3 | 0 | 0 | 3 | 2 | 2 |
| SDY1294 | 28687661 | 4 | 5 | 0 | 0 | 5 | 4 | 4 |
| SDY1325 | 28137280 | 5 | 5 | 0 | 0 | 5 | 5 | 5 |
| SDY1328 | 26742691 | 4 | 5 | 0 | 1 | 4 | 4 | 4 |
| SDY1364 | 23266342 | 3 | 3 | 0 | 0 | 3 | 3 | 3 |
| SDY1364 | 23844129 | 5 | 5 | 0 | 0 | 5 | 5 | 5 |
| SDY1373 | 28854372 | 4 | 4 | 0 | 0 | 4 | 4 | 4 |
| SDY1389 | 30111633 | 5 | 6 | 0 | 1 | 5 | 5 | 5 |
| SDY1393 | 36656789 | 3 | 3 | 0 | 0 | 3 | 3 | 3 |
| SDY1596 | 32005538 | 2 | 3 | 0 | 0 | 3 | 2 | 2 |
| SDY1630 | 32059780 | 3 | 4 | 0 | 2 | 2 | 3 | 3 |
| SDY1640 | 32473127 | 6 | 8 | 0 | 3 | 5 | 6 | 6 |
| SDY1654 | 31624246 | 4 | 3 | 0 | 0 | 3 | 3\* | 3\* |
| SDY1655 | 32717743 | 3 | 5 | 2 | 0 | 3 | 3 | 2 |
| SDY1669 | 32788292 | 7 | 9 | 0 | 1 | 8 | 7 | 7 |
| SDY1708 | 34128959 | 3 | 3 | 0 | 0 | 3 | 3 | 3 |
| SDY180 | 23601689 | 6 | 5 | 0 | 0 | 5 | 5 | 5 |
| SDY1991 | 35455361 | 4 | 6 | 0 | 0 | 6 | 4 | 4 |
| SDY1995 | 35062294 | 4 | 5 | 1 | 0 | 4 | 4 | 4 |
| SDY212 | 25834109 | 7 | 9 | 0 | 2 | 7 | 7 | 7 |
| SDY2189 | 34252919 | 10 | 10 | 0 | 1 | 9 | 9 | 9 |
| SDY404 | 25367297 | 3 | 3 | 0 | 0 | 3 | 3 | 3 |
| SDY80 | 24725414 | 4 | 4 | 0 | 0 | 4 | 4 | 4 |
| SDY984 | 28502771 | 8 | 11 | 0 | 2 | 9 | 8 | 8 |
| **Total** | | **147** | **171** | **3** | **19** | **149** | **144** | **143** |

---

## 6. Takeaways

1. **Round-1 extraction is the strongest step:** 98.0% recall and 2 false positives out of 171 entries. The 3 misses are all brief or nested mentions.
2. **The verifier gains little on this set.** It removes 2 non-assays but costs 1 real assay (SDY1655). Its rejection rule should not fire on commercial panel names (fix 6 in `evaluation.md`).
3. **Round 5 undoes round-1 granularity** whenever round 4 picks a generic OBI term. Two changes would keep what round 1 got right: better term selection in round 4 (fixes 1–3 in `evaluation.md`), or not folding entries whose `readouts` differ.
