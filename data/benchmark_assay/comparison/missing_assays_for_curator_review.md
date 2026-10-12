# Curator review: 3 benchmark assays the registry did not extract

**What this is.** When the assay registry (`data/claims/assay_registries/<pmid>_<SDY>/assays_benchmark.json`) was compared with the benchmark (`data/benchmark_assay/`), 3 of the 125 benchmark assays had no counterpart in the registry. For each one, this file gives the benchmark entry, the paper text it rests on, what the registry has instead, and our assessment. **The curator decides** whether each benchmark entry should stay as a separate assay.

All quotes below were copied verbatim from the paper's JATS XML in `data/JAT_XML/`.

**None of the three was extracted and then dropped.** They do not appear at any pipeline stage: not in round 1 (`assays_precorrection.json`), not in the verifier or corrector logs (`assays_verification.json`, `assays_corrections.json`) and not in the final files. The extractor never picked them up.

| # | Paper | Benchmark assay | Our assessment |
|---|---|---|---|
| 1 | SDY180 / PMID 23601689 | In Vitro Stimulation with Innate Immune Ligands | A stimulation experiment whose readout (microarray) the registry already has. **Curator decision on the rule needed.** |
| 2 | SDY984 / PMID 28502771 | In vitro stimulation of PBMCs with Zostavax® | A stimulation experiment whose readouts (flow cytometry, CBA) the registry already has. **Curator decision on the rule needed.** |
| 3 | SDY2189 / PMID 34252919 | Single-molecule array (SIMOA) | A distinct assay. **Benchmark looks correct; the registry missed it.** |

---

## 1. SDY180 / PMID 23601689 — "In Vitro Stimulation with Innate Immune Ligands"

**Benchmark entry** (`benchmark_assay/SDY180_assays_AS_v2_edit.json`)
- name_in_paper: *In Vitro Stimulation with Innate Immune Ligands*
- aliases: in vitro stimulation data set; in vitro treatment of blood; in vitro culture of blood with TLR agonists and cytokines; in vitro-derived gene lists; in vitro signature
- OBI: **OBI:0001463 transcription profiling by array assay**. This is the same term the benchmark gives its separate "Microarray Assay" entry for this paper.
- generate_claim: true

**Paper evidence** (Experimental Procedures, subsection *In Vitro Stimulation with Innate Immune Ligands*)
> "Fresh whole blood of four healthy subjects was incubated for 6 hr at 37°C with 18 different stimuli or left unstimulated and followed by RNA stabilization with Tempus reagent and sample storage at −20°C until RNA extraction, as described above. Stimulation conditions included PAM3, Zymosan, Poly IC, E-LPS, Flagellin, R837, CpG Type A, heat-killed Legionella pneumophila (HKLP), heat-killed Acholeplasma laidlawii (HKAL), and heat-killed Staphylococcus aureus (HKSA) (all from Invivogen); IL-18, TNF-α, IFN-α2b, IFN-β, IFN-γ (all from Peprotech); heat-killed Escherichia coli (in house preparation), live influenza A virus and live respiratory syncytial virus (RSV)."

**What the registry has.** `microarray assay`, with name_in_paper "microarray" and aliases "whole-genome arrays" and "whole-genome transcriptional profiles". Its evidence is the Microarray Assay subsection:
> "Amplified RNA was hybridized to Illumina HT-12 V3 beadchips (48,803 probes) and scanned on an Illumina Beadstation 500."

It has no entry or alias for the in vitro stimulation experiment.

**Assessment and reasoning**
- The experiment is real. It has its own Methods subsection and its own results (Figure 4 maps the in vivo vaccine response against the in vitro response).
- The measurement itself is not a new technique. The stimulated blood goes through the same RNA extraction and microarray ("as described above"). The benchmark confirms this by giving it the same OBI term as its microarray entry.
- So whether this is "missing" depends on what one benchmark entry stands for:
  - **If one entry = one measurement technique:** the registry's `microarray assay` already covers it, and this benchmark entry duplicates the microarray entry.
  - **If one entry = one experiment or dataset:** the benchmark is right and the registry missed it.

**Question for curator:** keep it as its own assay, fold it into "Microarray Assay" (for example as an alias), or remove it?

---

## 2. SDY984 / PMID 28502771 — "In vitro stimulation of PBMCs with Zostavax®"

**Benchmark entry** (`benchmark_assay/SDY984_assays_AS_v2.json`)
- name_in_paper: *In vitro stimulation of PBMCs with Zostavax®*
- aliases: in vitro PBMC stimulation; intracellular cytokine staining by flow cytometry; intracellular FACS staining; in vitro flow cytometry; in vitro analysis of IFN response
- OBI: **OBI:0000916 flow cytometry assay**. This is the same term as the benchmark's separate "Flow cytometry" entry.
- generate_claim: true

**Paper evidence** (Methods, subsection *In vitro stimulation of PBMCs with Zostavax®*; full subsection)
> "PBMCs isolated from healthy donors were cultured in RPMI and stimulated with Zostavax® (Zos at multiplicity of infection; 0.00028 or 0.0011 or 0.0045) or TLR9 ligand CpG-A (8 μg/ml, invivogen) or R848 (1 μg/ml, invivogen) for 20 hours. Following live/dead staining using zombie fixable viability kit (Biolegend), surface staining of cells was done to identify different innate cell populations and also for the expression of activation marker, CD80 and HLA-DR. For intracellular staining, cells were fixed and permeabilized (BD Fix/Perm kits) and stained for VZV-gI to detect the replication of VZV and that of IL-6 in CD14+ monocytes and CD1c+ myeloid DCs (mDCs), and IFN-α in CD123hi plasmacytoid DCs (pDCs) to analyze the cytokine production. Multi-color flow cytometry acquisition was performed on a BD LSR II and data was analyzed using FlowJo (Treestar). Cell-free culture supernatants collected were analyzed for cytokines and chemokines, including IL-6, TNF, CXCL8, CCL2, CXCL9 and CXCL10 using Cytokine Bead Array (CBA) kits (BD Biosciences, San Diego, US)"

**What the registry has.** The experiment uses two readouts, and the registry has both techniques:
- `flow cytometry assay` (name_in_paper "Flow cytometry"). Its evidence is the general Flow cytometry subsection, not this experiment:
  > "Flow cytometry analysis was done on either heparinized whole blood or cryopreserved PBMCs. All samples were run on an LSR II (BD Biosciences) and analyzed via FlowJo software. Each cell population was quantified as percentage of total PBMC."
- `cytometric bead array assay` (name_in_paper "Luminex assays", "Cytokine Bead Array (CBA)"). "Cytokine Bead Array (CBA)" comes from the last sentence of this subsection, so the registry did pick up the supernatant CBA readout of this experiment.

**Assessment and reasoning**
- This is the same pattern as #1. It's a real experiment with its own Methods subsection, but its readouts are flow cytometry and CBA, which the registry already lists. The benchmark also has separate "Flow cytometry" and "Cytokine Bead Array (CBA)" entries for this paper.
- Two details the curator may want to weigh:
  - The benchmark's aliases for this entry ("intracellular cytokine staining by flow cytometry", "intracellular FACS staining") name the readout, not the stimulation. That points to an entry about technique, which already exists.
  - The benchmark gives this entry only the flow cytometry OBI term, but the experiment also has a CBA readout.

**Question for curator:** keep it as its own assay, fold it into "Flow cytometry" (and/or "Cytokine Bead Array (CBA)"), or remove it? Use the same rule as for #1.

---

## 3. SDY2189 / PMID 34252919 — "Single-molecule array" (SIMOA)

**Benchmark entry** (`benchmark_assay/SDY2189_assays_AS_v2.json`)
- name_in_paper: *Single-molecule array*
- aliases: SIMOA; single-molecule array; highly sensitive single-molecule array
- OBI: none (null)
- generate_claim: true

**Paper evidence.** SIMOA has no Methods subsection. It is mentioned in three places:
- Results, *Innate immune responses*:
  > "The concentration of IFNα2 (type I interferon) was not significantly increased on days 1 and 2 after vaccination, and the responses were just over the assay limit of the highly sensitive single-molecule array (SIMOA) (16 fg ml−1) (Extended Data Fig. 7c, d)."
- Extended Data Fig. 7 legend, *Plasma cytokine analysis*:
  > "Plasma levels of CXCL10 (a) and IL-10 (b) determined by Olink, and IFNα2 measured by SIMOA (c). d, Kinetic plots of IFNα2 in plasma of female or male participants measured by SIMOA."
- Author contributions:
  > "K.H. and M.R. performed SIMOA"

**What the registry has.** Nothing for SIMOA. The closest entry is `Olink assay` (plasma cytokines by Olink PEA), but that is a different platform. The legend above lists Olink and SIMOA side by side as separate measurements.

**Assessment and reasoning**
- SIMOA is a distinct assay: a digital, bead-based ELISA platform (Quanterix) with its own analyte (plasma IFNα2), its own data (Extended Data Fig. 7c, d) and named people who performed it.
- It is not a stimulation protocol or a duplicate of another entry, so the rule in #1 and #2 doesn't apply. **The benchmark looks correct and the registry missed it.**
- A likely cause: SIMOA is described only in Results and a figure legend, not in Methods. By contrast, in SDY1669 (PMID 32788292) the paper describes SIMoA in its own sentence and the registry did extract it (as "highly sensitive ELISA enabled by single molecule array (SIMoA) technology").
- For the OBI field: SDY1669's registry mapped SIMoA to OBI:0000661 "enzyme-linked immunosorbent assay". The curator may want to use the same term here instead of null.

**Question for curator:** confirm the entry. Should it get an OBI term (for example enzyme-linked immunosorbent assay, OBI:0000661) instead of null?

---

## Effect on the comparison
From `assay_comparison_registry_folders.md`, step 1 is currently 122 / 125 found.
- If #1 and #2 are folded into existing entries: 122 / 123 found, and SIMOA is the only real miss.
- If #1 and #2 are kept as separate assays: the result stays 122 / 125.
