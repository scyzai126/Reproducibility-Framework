# Who is right — curator or agent? Adjudication of every MISSED / EXTRA / SPLIT row

Source: `data/benchmark_assay/comparison/benchmark_vs_stability.html` (benchmark v4 vs the
2026-10-19 `stability/` re-run). 7 MISSED, 3 EXTRA, 2 SPLIT rows. Each was checked against the
paper's own Methods text (parsed JATS, `assay_service.paper_source`), the curator's quote, the
agent's evidence, and the three raw extraction replies in `assays_raw.json`. Rule applied, per
the user: an assay counts only if Methods describes it as performed in this study; reagent
titration / QC steps and sub-steps of a described assay are not separate assays.

| # | paper | row | status | verdict | why |
|---|---|---|---|---|---|
| 1 | SDY1288 | One-Step RT-PCR | MISSED | **agent** | "SuperScript III One-Step RT-PCR System" (S203) is the reagent kit *inside* the TaqMan real-time RT-PCR viral-titer protocol (S199–S207). The curator counted the kit as a second RT-PCR assay; the agent has one entry with both wordings. |
| 2 | SDY1288 | virus isolation | MISSED | **curator** (minor) | Methods S155: cases "laboratory-confirmed by … real-time RT-PCR, in some cases followed by virus isolation". A case-classification test, which the extraction rules admit. 2 of 3 runs mentioned it, 1 made it an entry → voted to MINORITY. Curator marks `generate_claim: false`; no result derives from it. |
| 3 | SDY1289 | lysis plaque assay | MISSED | **agent** | S149/S151: viral stock titrated and inactivation confirmed by plaque assay — reagent preparation QC, which the extraction rules exclude. 0 of 3 runs took it; curator also marks it `generate_claim: false`. |
| 4 | SDY1630 | in vitro cytokine stimulation and functional assays | MISSED | **curator** | S122–S128: sorted NK cells stimulated with IL-12/15/18 then ICS, and CD107a degranulation vs K562 — functional assays, a different measurement from the phenotyping panels even though both are read on a cytometer. The agent kept the heading only as a *wording* of `flow cytometry assay`, then inconsistently split off "measuring degranulation" as a doubted entry (row 12). The curator's OBI term (OBI:1110207) is one the pruned vocabulary cannot reach, so even a correct extraction would score MATCH_OBI_UNMAPPED. |
| 5 | SDY180 | Commercial immunoassays (pneumococcal polysaccharide antibody) | MISSED | **curator** | S138 in Methods: "Antibody response to 14 pneumococcal polysaccharides was measured by using commercial immunoassays." Performed here; 0 of 3 extraction runs produced it. A genuine recall miss — the sentence names no technique word, which is what the extractor keys on. |
| 6 | SDY2189 | Single-molecule array | MISSED | **agent** (by rule) | No Methods description; one Results sentence citing the assay limit, an Extended Data legend the parser drops, and an author-contribution line. Excluded by design (decided earlier today). |
| 7 | SDY984 | tandem_ms | MISSED | **agent** | S267: "Metabolite confirmation was performed with tandem MS-MS experiments" — a confirmation sub-step of the plasma metabolomics assay. All 3 runs mentioned it; 2 folded it into metabolomics, 1 listed it → MINORITY. Curator `generate_claim: false`. |
| 8 | SDY1328 | MONOLISA Anti-HBs PLUS kit → surface HBV antibody assay | EXTRA | **agent** | S138–S145: full protocol quantifying anti-HBsAg antibodies in serum, WHO-standardised. The curator has no row for it. |
| 9 | SDY984 | nested PCR analysis | EXTRA | **curator** | S234–S242: a second-round PCR on samples negative in the first round, same VZV ORF63 target, same "Viral DNA detection" experiment — a sensitivity step of the curated real-time PCR assay, not a separate assay. |
| 10 | SDY984 | Cytokine Bead Array (CBA) | EXTRA | **agent** | S257: BD CBA kits on *culture supernatants* after in-vitro Zostavax stimulation — distinct from the curated plasma Luminex 10-plex (S248–S250). Two assays, different specimen, kit and section; the curator lists one. (The old run hid this by folding both onto OBI:0000920.) |
| 11 | SDY1328 | "commercially available kit" vs GM1 ELISA | SPLIT | **agent on substance, poor name** | S146–S153: anti-diphtheria IgG ELISA (Sekisui Virotech EC129.00), and S154–S161 anti-tetanus IgG ELISA (EC124.00) — two further kit ELISAs the curator does not list at all. The agent delivered the diphtheria one under the vague name "commercially available kit" (the judge rightly flagged the name) and lost the tetanus one to MINORITY. |
| 12 | SDY1630 | "measuring degranulation by NK cells" | SPLIT | **neither** | Same material as row 4. The agent should have delivered one functional-assay entry (stimulation + ICS + degranulation) rather than merging it into phenotyping and splitting a purpose clause out. |

## Tally
- **Agent right: 6** (rows 1, 3, 6, 7, 8, 10) — three curator over-counts (a reagent kit, a
  stock-titration QC, a confirmation sub-step), one by the Methods-only rule, two assays the
  curator omitted.
- **Curator right: 4** (rows 2, 4, 5, 9) — two real agent misses (SDY180 commercial
  immunoassays, SDY1630 functional assays), one vote casualty (virus isolation), one agent
  over-split (nested PCR).
- **Partial: 2** (rows 11, 12).

## Curator omissions this surfaced
- SDY1328: anti-HBsAg (MONOLISA), anti-diphtheria IgG and anti-tetanus IgG kit ELISAs — three
  Methods-described serology assays absent from the curated list (it has only the GM1 ELISA).
- SDY984: CBA on stimulation supernatants (only the plasma Luminex is curated).

## Agent errors this surfaced
- SDY180: a Methods sentence with no technique noun ("commercial immunoassays") is skipped 3/3.
- SDY1630: a functional-assay section is absorbed into phenotyping as a wording; a purpose clause
  is then split out with a doubted identity.
- SDY1288 virus isolation and SDY984 tandem MS: 1-of-3 entries discarded by the vote — right
  call for tandem MS, wrong for virus isolation. The vote cannot tell these apart; the verifier could.
- SDY984 nested PCR: a within-experiment second round delivered as its own assay.

## Net
On the disputed rows the agent is right more often than the curator (6 vs 4), and most curator
"misses" charged to the agent are curator over-counts or omissions. The benchmark's own
inconsistencies (kit-as-assay in SDY1288, QC-as-assay in SDY1289, missing serology in SDY1328)
cap the achievable score below 1.0 regardless of pipeline quality. The two agent errors worth
fixing are the technique-noun dependence (SDY180) and the functional-assay handling (SDY1630).
