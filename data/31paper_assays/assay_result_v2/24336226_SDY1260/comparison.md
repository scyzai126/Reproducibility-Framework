# SDY1260 (PMID 24336226): assay extraction v2 vs v1 vs benchmark

v2 = new extract_assays.txt / resolver_obi_assay.txt (run 2026-10-05, 25 calls, JATS XML).
v1 = data/31paper_assays/assay_result_v1/24336226_SDY1260.
Benchmark = data/benchmark_assay/SDY1260_Assay_Hailong.json.

## Assay-level (OBI term)

| Benchmark | Benchmark OBI | v1 | v2 |
|---|---|---|---|
| ELISA | OBI:0000661 ELISA | ✅ same | ✅ same |
| Luminex | OBI:0000920 cytometric bead array | ✅ same | ✅ same |
| flow cytometry | OBI:0000916 flow cytometry assay | ✅ same | ✅ same |
| ELISpot | OBI:0600031 ELISpot | ✅ same | ✅ same |
| SBA | (none) | OBI:0003797 bacterial neutralization assay | OBI:0003797 bacterial neutralization assay |
| microarray | OBI:0001985 microarray assay | ✅ OBI:0001985 microarray assay | ❌ OBI:0001463 transcription profiling by array assay |

Both v1 and v2 find all 6 benchmark assays (recall 6/6), no extras, and set generate_claim=true for all 6, as the benchmark does.
OBI agreement with the benchmark: v1 5/5, v2 4/5 (SBA has no benchmark OBI, so it is left out of the score).

## Wording differences (name_in_paper / aliases)

| Assay | Benchmark | v1 | v2 |
|---|---|---|---|
| microarray | microarray; aliases DNA microarray, Blood transcriptome analysis | DNA microarray; aliases DNA microarrays, gene expression profile | DNA microarray; no aliases |
| Luminex | Luminex | Luminex | "anti-Diphtheria IgG by Luminex" (a section heading, not an assay name) |
| flow cytometry | flow cytometry; alias FACS | flow cytometry; alias FACS | FACS, FACS staining; alias flow cytometry (name and alias swapped) |
| SBA | SBA; alias serum bactericidal activity assay | serum bactericidal titers (SBA); aliases SBA, Serum bactericidal assay (SBA) | serum bactericidal titers (SBA); alias SBA |
| ELISA | ELISA | ELISA, ELISA kits | ELISA, ELISA kits |
| ELISpot | ELISpot | ELISpot | ELISpot |

## v2 pipeline notes
- Round 1 extracted 9 entries (v1: 6), including duplicates: two "ELISA" keys, "ELISA kits", "FACS" and "FACS staining". Round 5 folded these back to 6.
- The verifier sent 3 entries to REVIEW (name_in_paper NOT_SUPPORTED): "FACS", "FACS staining", "ELISA kits".
- WARNING name_in_paper differs from the key for 4 entries (DNA microarray, Luminex, SBA, ELISpot). These warnings are expected because v2 now keys entries by their OBI label.

## Verdict
v2 matches v1 at the assay level, but it is slightly worse on detail: the microarray OBI term changed away from the benchmark's, the Luminex name now carries the heading text, the flow cytometry name and alias are swapped, and round 1 produced more duplicate entries.
