# Who is wrong: benchmark_assay_v5 vs assay_result_v1, issue by issue

Scored report: `data/benchmark_assay/comparison/benchmark_v5_vs_agent_v1.html`
Benchmark: `data/benchmark_assay/benchmark_assay_v5/`
Agent registries: `data/31paper_assays/assay_result_v1/`
Adjudicated: 2026-10-23. Read-only; nothing in `data/` was changed.

The comparison holds 158 rows over 31 papers. 127 are clean `MATCH`. The other **31 rows** are the
issues adjudicated here, each against the paper text (`data/JAT_XML/*.xml`), the OBI release
(`data/OBI/obi.obo`), the curator's JSON and the agent's registry.

Reported totals: recall 0.953, precision 0.934, F1 0.943, OBI exact rate 0.901.

> **Superseded for the agent side. Read this first.**
>
> `assay_result_v1` was written on 2026-10-12 by the pre-vote pipeline. Round 1 had no 3-way
> consensus vote then; that landed on 2026-10-19 in commit `281e006`. Only 3 of the 31 v1
> directories were ever re-run under it. The current corpus is
> `data/31paper_assays/assay_result_v3/`, scored at
> `assay_result_v3/comparison/benchmark_v5_vs_agent.html`: recall 0.993, precision 0.887,
> and **1 missed assay in the whole corpus** instead of 7.
>
> Fixed since this adjudication was written: the pneumococcal immunoassay in SDY180, the
> proliferation assay in SDY1654, the HD71 array in SDY1655, and the merge faults in SDY1289,
> SDY1328 and SDY1630. The only agent miss that survives is SIMOA in SDY2189, diagnosed in
> [the drop analysis](assay_dropped_assays_debug.md).
>
> The curator-side findings below are unaffected: the SDY1669 brace defect, the mistyped CFSE
> id, the SDY1289 qPCR mapping and the three blank OBI ids all still stand against
> benchmark v5.

## Summary

| Fault | Rows |
|---|---|
| Agent | 14 |
| Curator, judgement or unfilled OBI id | 5 |
| Curator file malformed, content correct | 6 |
| Scorer artifact, neither side wrong | 1 |
| Neither, the ontology cannot express both | 4 |
| Shared | 1 |

Two findings matter more than the per-row verdicts.

**The largest block is not a disagreement.** All five SDY1669 `EXTRA` rows and its one
`MATCH_OBI_CONFLICT` come from a brace error in `SDY1669_assays_AS_v2.json`. Six curator entries
sit *inside* the `"Flow cytometry analysis of PBMCs"` object instead of beside it, so the loader
sees 3 entries where the curator wrote 9. The agent found exactly those six. Repairing the file
converts 6 issue rows to matches and lifts precision from 0.934 to roughly 0.967.

**The agent's weakness is under-calling, not over-calling.** Nine of its fourteen faults are a
dropped assay or two distinct assays merged onto one OBI key. Only three are over-splitting. The
merge pattern recurs: a shared parent term plus a shared technique name currently folds assays that
differ in platform, sample or analyte.

## Agent at fault (14)

| Paper | Row | Why |
|---|---|---|
| SDY1264 | RT-PCR conflict | Methods name a custom TaqMan plate and normalize to cycling-threshold values, so the assay is real-time. The curator's `OBI:0000911` is right; the agent's generic `OBI:0001170` drops the real-time fact. |
| SDY1288 | EXTRA RT-PCR, "viral titer assays" | The same CHIKV viral-load qRT-PCR the agent already filed as real-time RT-PCR, entered a second time under the less precise term. |
| SDY1289 | MISSED cytometric bead assay | The paper runs two distinct bead cytokine assays: the BD Th1/Th2 CBA array on PBMC supernatants, and a Beadlyte 22-plex Luminex on MIMIC co-culture supernatants. The agent folded both into one entry; the curator correctly kept them apart. |
| SDY1289 | EXTRA viral plaque assay | Titration of the viral stock, not an assay on study samples. The agent's own rules rejected Trypan blue in SDY1655 on the same grounds. Minor and arguable. |
| SDY1328 | MISSED multiplex ELISA, RBM 45-plex | Distinct from the GM1-ELISA for anti-CTB IgG in platform and analytes. The agent merged both under one ELISA key. |
| SDY1373 | Multiplex granularity | Read on a Bio-Plex Luminex-200, a flow-based bead reader, so the curator's `OBI:0003799` fits. The agent stopped at the parent `OBI:0000920`. Minor. |
| SDY1393 | RNA-seq granularity | Whole blood on an Illumina NovaSeq, plainly bulk. The curator's `OBI:0003090` is right; the agent used the generic `OBI:0001271`. Minor. |
| SDY1630 | MISSED in-vitro cytokine stimulation | The agent captured the section name but folded the functional assay into `flow cytometry assay`. The paper gives it its own methods subsection with IL-12/15/18 stimulation, intracellular cytokine staining and CD107a degranulation. The curator's term, `OBI:1110207`, covers only the IFN-gamma half. |
| SDY1654 | MISSED proliferation assay | Methods: "stimulation/proliferation assays ... stained cells with Cell Proliferation Dye eFluor 450". `OBI:0000891` exists. The agent kept only the flow entry. |
| SDY1655 | MISSED HD71 cytokine array | Its own methods paragraph: sera shipped to Eve Technologies for the Human Cytokine/Chemokine Array 71-403 Plex Panel. Absent from the registry and from `assays_rejected.json`, so extraction never saw it. |
| SDY1655 | EXTRA ELISA | The paper's only "ELISA" is a loose results-section word for those same cytokine measurements. The agent took the loose word and missed the real assay. |
| SDY180 | MISSED commercial immunoassays | Methods: "Antibody response to 14 pneumococcal polysaccharides was measured by using commercial immunoassays." Plain miss. |
| SDY2189 | MISSED single-molecule array | SIMOA measures plasma IFN-alpha2 in the results and appears in the author contributions. Plain miss. |
| SDY984 | EXTRA tandem mass spectrometry | MS/MS used only to confirm metabolite identity inside the metabolomics workflow, `generate_claim` false. The curator folded it. Over-split but defensible. |

## Curator at fault (5, plus 1 shared)

| Paper | Row | Why |
|---|---|---|
| SDY1289 | CFSE conflict | The curator's id is `OBI:00003582`, one zero too many. The agent's `OBI:0003582` is the same term, spelled correctly. Data entry. |
| SDY1289 | qPCR conflict | Verifying microarray gene expression requires reverse transcription. The agent's `OBI:0000911` is right; the curator's `OBI:0000893` drops the RT step. |
| SDY1260 | SBA unmapped | The curator left the id blank. `OBI:0003797 bacterial neutralization assay`, which the agent found, is correct. |
| SDY1264 | Immunofluorescence unmapped | Curator blank. OBI has no immunofluorescence assay term; `CHMO:0000087` is imported into this obo release and is the right pick. |
| SDY1640 | Lateral flow unmapped | Curator blank. `OBI:0002773`, a single-value antibody-binding readout, is sound for a colloidal-gold lateral flow test. |
| SDY1260 | Luminex granularity (**shared**) | The paper's design table lists "Anti-DT IgG (Luminex)" and "27-plex cytokines (Luminex)" as separate assays. The curator captured only the first; the agent merged both onto the parent term. The curator's `OBI:0003116` is right for the anti-DT IgG assay alone. |

## Curator file malformed, content correct (6)

All six rows are SDY1669: the `EXTRA` rows for Olink, ELISA, bulk RNA-seq, 16S qPCR and the TLR4
reporter assay, plus the `MATCH_OBI_CONFLICT` that paired the curator's flow row against the
agent's CITE-seq. Every one of those entries is present in the curator's file, nested one level too
deep. The scorer's in-memory repair only strips trailing commas and closes brackets, so it cannot
reach them. No judgement by either side is wrong here.

## Scorer artifact (1)

SDY1991, `EXTRA  IFN-γ Capture Assay`. The curator mapped that assay to `OBI:0000916 flow cytometry
assay`. `match_tier` in `scripts/compare_assay_benchmark.py` tests the OBI relation before names,
so the curator's row bound the agent's `flow cytometry assay` entry on the `obi_exact` tier and
orphaned the agent entry carrying the identical name. Neither side is wrong about the paper.
Separately worth noting: the agent left this assay unmapped where `OBI:1110207` exists.

## Neither side wrong (4)

- **SDY1264, immunoblot vs western blot.** `OBI:0000854` is a child of `OBI:0001978`, and the
  procedure described is a western blot. The agent's term is the more precise of two correct ones.
- **SDY1373, RNA-seq.** The quote names NEBNext Poly(A) selection, so the curator's `OBI:0002571`
  is evidence-backed; the agent's `OBI:0003090` is equally true of the same experiment. The two
  terms are siblings, so one entry cannot hold both facts.
- **SDY1596, colony-forming units.** OBI has no CFU term. Both sides correctly left it unmapped.
- **SDY984, metabolomics.** The curator chose the platform, `liquid chromatography mass
  spectrometry`; the agent chose the purpose, `metabolomics by mass spectrometry`. Both describe
  the same experiment.

## Follow-ups available

Each is a separate decision, none taken here.

1. Repair the nesting in `data/benchmark_assay/benchmark_assay_v5/SDY1669_assays_AS_v2.json` and
   rerun `scripts/compare_assay_benchmark_v2.py`. It is a curator data file, so it should not be
   edited without the curators' agreement.
2. Rank the name tier ahead of `obi_exact` in `match_tier`, or make pairing globally optimal rather
   than greedy, to stop the SDY1991 class of orphaned entry.
3. Revisit round-5 folding against the four merge faults (SDY1289, SDY1328, SDY1260, SDY1630): a
   shared parent term plus a shared technique name is currently enough to fold assays that differ
   in platform, sample or analyte.

## Checking the claims

```bash
# the six buried curator entries
python3 -I -c "import json;d=json.load(open('data/benchmark_assay/benchmark_assay_v5/SDY1669_assays_AS_v2.json'));print(list(d.keys()));print(list(d['Flow cytometry analysis of PBMCs'].keys()))"

# two Luminex assays in SDY1260, two bead assays in SDY1289
grep -o "27-plex cytokines (Luminex)" data/JAT_XML/SDY1260_24336226.xml
grep -o "Beadlyte human 22-plex" data/JAT_XML/SDY1289_19047440.xml

# assays the agent missed
grep -o "commercial immunoassays" data/JAT_XML/SDY180_23601689.xml
grep -o "Chemokine Array 71" data/JAT_XML/SDY1655_32717743.xml
grep -o "Cell Proliferation Dye eFluor 450" data/JAT_XML/SDY1654_31624246.xml
```
