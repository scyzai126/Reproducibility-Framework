# SDY1264 (PMID 19029902): assay extraction v2 vs v1 vs benchmark

v2 = new extract_assays.txt / resolver_obi_assay.txt (run 2026-10-05, 32 calls, JATS XML).
v1 = data/31paper_assays/assay_result_v1/19029902_SDY1264.
Benchmark = data/benchmark_assay/SDY1264_Assay_Hailong.json (4 assays).

## Benchmark assays

| Benchmark | Benchmark OBI | v1 | v2 |
|---|---|---|---|
| microarray | OBI:0001985 microarray assay | ✅ same | ✅ same |
| Luminex assay | OBI:0000920 cytometric bead array | ✅ same (name "Multiplex analysis") | ✅ same (name "Multiplex analysis") |
| Flow cytometric analysis | OBI:0000916 flow cytometry assay | ✅ same | ✅ same |
| YFV neutralizing antibody assay | OBI:0003796 pathogen neutralization assay | ⚠️ CPE and PRNT as 2 separate entries, no OBI term | ⚠️ CPE + PRNT merged into 1 entry, OBI:0000872 serum neutralization of viral infectivity assay |

Recall: v1 4/4, v2 4/4. OBI agreement: v1 3/4 (no term for the neutralization assay), v2 3/4 (a different term for it).
generate_claim is true for every entry in v1, v2 and the benchmark.

## Assays outside the benchmark (in both v1 and v2)
RT-PCR (OBI:0001170), Immunofluorescence → immunocytochemistry (OBI:0002174), ELISA (OBI:0000661), immunoblot analysis.
- The immunoblot mapping changed: v1 had OBI:0001978 immunoblot assay, v2 has OBI:0000854 western blot assay.
- v1: 9 final entries. v2: 8 final entries (CPE and PRNT folded together).

## Wording
v2 has no aliases on 6 entries where v1 had them (v1: 24-plex Luminex assay, Flow cytometry, transcriptional profiling, Fluorescence microscopy). Neither run writes "Luminex" into name_in_paper. Both use the section heading "Multiplex analysis", which the v2 verifier flagged NOT_SUPPORTED.

## v2 pipeline notes
- REVIEW: Multiplex analysis (name_in_paper NOT_SUPPORTED: it is only a heading). Also cytopathic effect (CPE), whose sample_type was NOT_SUPPORTED and was REPLACED in round 3.
- MERGED: PRNT → serum neutralization of viral infectivity assay (OBI:0000872).
- WARNING name_in_paper differs from the key for 7 entries. This is expected now that entries are keyed by their OBI label.
