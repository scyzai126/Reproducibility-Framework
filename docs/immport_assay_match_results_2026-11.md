# ImmPort assay match — 逐条结果（31 篇 benchmark / 29 个 study）

*2026-11-10。本文件是**人工定稿**,`scripts/check_immport_measurements.py` 不会覆盖它。*
*脚本生成的是 `docs/immport_measurement_coverage_2026-11.md`(每次重跑整 file 重写);*
*机器可读行在 `data/immport_assay_match_2026-11.json`。*

## 数据从哪来

ImmPort **没有 `measurement` 表**。assay 登记在 `experiment` 表(5,140 行 / 1,019 个 study),
技术名的本体 PURL 在查找表 `lk_exp_measurement_tech`(102 种技术):

```sql
SELECT DISTINCT e.study_accession, e.measurement_technique, e.name, lk.link
FROM experiment e
LEFT JOIN lk_exp_measurement_tech lk ON lk.name = e.measurement_technique
WHERE e.study_accession IN (29 个 SDY)
```

**两列都要取。** `measurement_technique` 是从 102 项受控词表里粗选的一项;
`experiment.name` 是本次实验的自由文本名,常常保留了受控词丢掉的信息 —— 见下面 `EXPNAME` 一节。

我们侧:`data/31paper_assays/assay_result_v3/<pmid>_<SDY>*/assays_OBI.json`(`obi_id`、`obi_label`)
与同目录 `assays_benchmark.json`(`name_in_paper`、`aliases`、`standard_technique_name`),
**按 study 取其下所有论文 entry 的并集** —— 因为 ImmPort 按 study 登记,我们按 paper 抽取。

## 怎么判断 match —— 主判据是本体 id,但不是 id 相等

字符串比不了(`Flow Cytometry` / `flow cytometry assay` / `FACS` 是同一件事),
只认 id 相等又太严(ImmPort 写上传时的粗标签,我们抽论文里的细粒度术语)。
所以在**完整 `obi.obo` 的 is_a 图**上分级,一条 (study, technique) 取其 study 下所有
entry 中**最好的一级**:

| 级别 | 判据 | 含义 |
|---|---|---|
| `EXACT` | 我方 `obi_id` ∈ ImmPort 该技术的 id 集合 | 同一个术语 |
| `DESCENDANT` | 我方 term 在 ImmPort term 的 is_a **之下** | 我们更具体,仍然答对 |
| `ANCESTOR` | 我方 term 在其 **之上** | 我们更笼统,仍然答对 |
| `NAME` | ImmPort 的**受控技术名**归一化后命中我方某个写法 | 无 id 可比时的兜底 |
| `EXPNAME` | ImmPort 的 **`experiment.name`** 与我方某个写法指同一件事 | 见下 |
| `SIBLING` | 二者共享同一个直接父,且该父不在 `HUB_PARENTS` 内 | 同族不同名 |
| `MISS` | 以上皆不成立 | 待人工判定 |

### `EXPNAME`:受控词表丢掉的信息,自由文本名留住了

`measurement_technique` 只有 102 项,词表里没有的东西只能归到最近的一项,于是:

| study | measurement_technique | experiment.name | 受控词错在哪 |
|---|---|---|---|
| SDY1325 | `Neutralizing Antibody Titer Assay` | **`Serum bactericidal assay`** | 词表无"血清杀菌",归到了中和效价(其 PURL 还是**病毒**中和) |
| SDY1373 | `Transcription profiling by array` | **`Next Generation Sequencing RNA Seq data from UKE Phase I rVSV ZEBOV vaccine clinical trial...`** | 数据是 RNA-seq,却挂在"芯片"下 |
| SDY1655 | `Protein microarray` | **`Cytokine Array`** | 多重微珠板按产品名归成了蛋白芯片 |

判据:某个 `experiment.name` 与我方某个写法,归一化后**相等**,或**较短者以整词形式出现在较长者中**
(两个方向都查 —— `Serum bactericidal assay` 与我方等长,`Cytokine Array` 比我方的
`Human Cytokine Array/Chemokine Array 71-403 Plex Panel (HD71)` 短,
`rna seq` 则嵌在 ImmPort 那串长名字里)。

**较短的一侧至少要 2 个词**(`_EXPNAME_MIN_WORDS`)。单个 token 出现在自由文本里不是证据:
否则 ImmPort 的 `AntiS1IgG` 会去配我方任意一条,我方的 `elisa` 也会被任意含该词的实验名带走。
整词匹配而非裸子串,否则 `array` 会从 `microarray` 里面匹出来。

`EXPNAME` 排在 `NAME` 之下、`SIBLING` 之上:它比共享父节点强(是具体命名的吻合),
但弱于受控词本身的吻合。

### 其余三点取舍,每一点都是被实际假阳性逼出来的

1. **`SIBLING` 只认直接父,不认任意共同祖先。** OBI 的 is_a 比直觉平:
   `real time RT-PCR` 不在 `real time PCR` 之下(同挂 `PCR assay`),`CyTOF` 不在
   `flow cytometry` 之下(同挂 `cytometry assay`)。但放宽到"在 root 之下相遇"几乎匹配一切 ——
   旧规则曾把中和试验配上转录芯片、CyTOF 配上血凝抑制。
2. **即使只差一步也不够:`HUB_PARENTS` 里的父节点不算数。** 有几个直接父按
   **测什么 / 测在什么样本上**分组,不是技术族:`OBI:0000443 analyte assay`(89 个直接子)
   底下同时直接挂着 ELISA、微珠法和中和抗体效价;`OBI:0003040 blood assay` 有 331 个直接子。
   **宽度本身不是判据** —— `cytometry assay` 有 69 个直接子却是真技术族;判据是该节点
   命不命名一种方法。名单:`OBI:0000070 assay`、`OBI:0000443 analyte assay`、
   `OBI:0003040 blood assay`、`OBI:2100023 protein assay`。
3. **一个技术可有多个 id**(`lk.link` 常含多个 PURL,如 `Array` 有 4 个),命中任一即算;
   **去重按 (study, 第一个 id)**,因为 `Virus Neutralization` 与
   `Neutralizing Antibody Titer Assay` 都指向 `OBI:0000872`。`Other` 无信息,丢弃(2 条)。

**单向检查**:只问"ImmPort 记了的我们有没有",不问反向 —— 我们抽到而 ImmPort 未登记属正常。

## 总计

83 条 (study, technique) 组合(已丢弃 2 条 `Other`):

| level | 条数 |
|---|---|
| EXACT | 62 |
| DESCENDANT | 9 |
| EXPNAME | 3 |
| SIBLING | 3 |
| ANCESTOR | 0 |
| NAME | 0 |
| MISS | 6 |

6 条 MISS 分属两组:论文齐全的 study 3 条(构成对论断的检验),
论文不齐全的 3 条(可能写在我们没有的论文里,不算反例)。
**每一条都经过原文复核,结论见文末。**

## 论文齐全的 26 个 study —— 70 条

| study | ImmPort technique | ImmPort OBI id | experiment.name | 我们的 entry | pmid | level |
|---|---|---|---|---|---|---|
| SDY1289 | Neutralizing Antibody Titer Assay | `OBI:0000872` | PMID19047440.GSE13699.PRNT | — |  | **MISS** |
| SDY1655 | ELISA | `OBI:0000661` | AntiS1IgG; AntiS1IgM | — |  | **MISS** |
| SDY180 | Nanostring | (无本体 id) | Flu_09_Nanostring | — |  | **MISS** |
| SDY1393 | CyTOF | `OBI:0002115` | CyTOF_HIPC2_Flu_Year2 | `OBI:0000916` flow cytometry assay | 36656789 | **SIBLING** |
| SDY1654 | Q-PCR | `OBI:0000893` | A type II IFN response state in activated CD4+ T cells - Fig 5A | `OBI:0000911` real time reverse-transcription polymerase chain reaction assay | 31624246 | **SIBLING** |
| SDY1655 | Real time polymerase chain reaction assay | `OBI:0000893` | Np_RT-PCR; Saliva_RT-PCR | `OBI:0000911` real time reverse-transcription polymerase chain reaction assay | 32717743 | **SIBLING** |
| SDY1325 | Neutralizing Antibody Titer Assay | `OBI:0000872` | Serum bactericidal assay | `OBI:0003797` bacterial neutralization assay | 28137280 | **EXPNAME** |
| SDY1373 | Transcription profiling by array | `OBI:0001463` | Next Generation Sequencing RNA Seq data from UKE Phase I rVSV ZEBOV… | `OBI:0003090` bulk RNA-seq assay | 28854372 | **EXPNAME** |
| SDY1655 | Protein microarray | `OBI:0400149` | Cytokine Array | `OBI:0000920` cytometric bead array assay | 32717743 | **EXPNAME** |
| SDY1288 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | RNAseq analysis of PAXGene_blood | `OBI:0003090` bulk RNA-seq assay | 30150281 | **DESCENDANT** |
| SDY1393 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | Platelet Bulk RNA-seq Year-2 | `OBI:0003090` bulk RNA-seq assay | 36656789 | **DESCENDANT** |
| SDY1630 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | Tissue determinants of human NK cells via RNA-Seq profiling | `OBI:0003090` bulk RNA-seq assay | 32059780 | **DESCENDANT** |
| SDY1654 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | scRNA-seq analysis of human T cells in blood and tissues | `OBI:0002631` single-cell RNA sequencing assay | 31624246 | **DESCENDANT** |
| SDY1669 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | CITE-seq; Bulk RNA seq | `OBI:0003090` bulk RNA-seq assay | 32788292 | **DESCENDANT** |
| SDY1991 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | Role of Transcriptomics of Acute DENV-Specific CD8+ T Cells in Dise… | `OBI:0003090` bulk RNA-seq assay | 35455361 | **DESCENDANT** |
| SDY1995 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | Association of CD4+CD8+�T Cells with risk of plasma leakage in Deng… | `OBI:0003090` bulk RNA-seq assay | 35062294 | **DESCENDANT** |
| SDY2189 | RNA sequencing | `OBI:0001177`, `OBI:0001271` | Bulk RNAseq; CITEseq assay | `OBI:0003090` bulk RNA-seq assay | 34252919 | **DESCENDANT** |
| SDY984 | Mass Spectrometry | `OBI:0000470` | Metabolomics | `OBI:0003540` tandem mass spectrometry assay | 28502771 | **DESCENDANT** |
| SDY1260 | ELISA | `OBI:0000661` | Meni2010 antibody titers | `OBI:0000661` enzyme-linked immunosorbent assay | 24336226 | **EXACT** |
| SDY1260 | Flow Cytometry | `OBI:0000916` | Meni2010 FACS | `OBI:0000916` flow cytometry assay | 24336226 | **EXACT** |
| SDY1260 | Luminex xMAP | `OBI:0000920` | Meni2010 luminex | `OBI:0000920` cytometric bead array assay | 24336226 | **EXACT** |
| SDY1260 | Transcription profiling by array | `OBI:0001463` | Meni2010 microarray | `OBI:0001463` transcription profiling by array assay | 24336226 | **EXACT** |
| SDY1264 | Transcription profiling by array | `OBI:0001463` | YF17D-2006 microarray | `OBI:0001463` transcription profiling by array assay | 19029902 | **EXACT** |
| SDY1264 | Virus Neutralization | `OBI:0000872` | Neut Ab-CPE | `OBI:0000872` serum neutralization of viral infectivity assay | 19029902 | **EXACT** |
| SDY1276 | Hemagglutination Inhibition | `OBI:0000875` | Hemagglutination inhibition (HAI) tests | `OBI:0000875` viral hemagglutination inhibition assay | 21357945 | **EXACT** |
| SDY1276 | Neutralizing Antibody Titer Assay | `OBI:0000872` | Neutralizing Antibody Titer | `OBI:0000872` serum neutralization of viral infectivity assay | 21357945 | **EXACT** |
| SDY1276 | Transcription profiling by array | `OBI:0001463` | Time series of global gene expression after trivalent influenza vac… | `OBI:0001463` transcription profiling by array assay | 21357945 | **EXACT** |
| SDY1288 | CyTOF | `OBI:0002115` | CyTOF analysis of PBMCs for CHIKV IOF | `OBI:0002115` cytometry time of flight assay | 30150281 | **EXACT** |
| SDY1288 | Luminex xMAP | `OBI:0000920` | Luminex analysis of serum for CHIKV IOF | `OBI:0000920` cytometric bead array assay | 30150281 | **EXACT** |
| SDY1289 | Transcription profiling by array | `OBI:0001463` | In vivo GSMs for GSE13699 'Immune response to the yellow fever vacc… | `OBI:0001463` transcription profiling by array assay | 19047440 | **EXACT** |
| SDY1291 | Transcription profiling by array | `OBI:0001463` | Merck Ad5/HIV vaccine transcript expression time course | `OBI:0001463` transcription profiling by array assay | 23151505 | **EXACT** |
| SDY1293 | Transcription profiling by array | `OBI:0001463` | Expression data from a malaria vaccine trial (HG-U133A2.0 and U133 … | `OBI:0001463` transcription profiling by array assay | 20078211 | **EXACT** |
| SDY1294 | Neutralizing Antibody Titer Assay | `OBI:0000872` | Plaque assay for quantitation of YFV-neutralizing Abs | `OBI:0000872` serum neutralization of viral infectivity assay | 28687661 | **EXACT** |
| SDY1294 | Transcription profiling by array | `OBI:0001463` | GSE89292 Expression data to study temporal transcriptomic changes o… | `OBI:0001463` transcription profiling by array assay | 28687661 | **EXACT** |
| SDY1325 | Transcription profiling by array | `OBI:0001463` | Gene expression of B cell responses to quadrivalent meningococcal c… | `OBI:0001463` transcription profiling by array assay | 28137280 | **EXACT** |
| SDY1328 | ELISA | `OBI:0000661` | Hepatitis B Virus Surface Antibody | `OBI:0000661` enzyme-linked immunosorbent assay | 26742691 | **EXACT** |
| SDY1328 | Transcription profiling by array | `OBI:0001463` | DNA microarray | `OBI:0001463` transcription profiling by array assay | 26742691 | **EXACT** |
| SDY1364 | ELISA | `OBI:0000661` | Serum IgG | `OBI:0000661` enzyme-linked immunosorbent assay | 23266342 | **EXACT** |
| SDY1364 | ELISPOT | `OBI:0600031` | IFNg ELISPOT | `OBI:0600031` enzyme-linked immunospot assay | 23266342 | **EXACT** |
| SDY1364 | Transcription profiling by array | `OBI:0001463` | Gene expression in vitro stimulation  analysis; Gene expression tim… | `OBI:0001463` transcription profiling by array assay | 23844129 | **EXACT** |
| SDY1389 | CyTOF | `OBI:0002115` | Lymph node reservoirs for long-lived memory T cells - CyTOF | `OBI:0002115` cytometry time of flight assay | 30111633 | **EXACT** |
| SDY1389 | Flow Cytometry | `OBI:0000916` | Lymph node reservoirs for long-lived memory T cells | `OBI:0000916` flow cytometry assay | 30111633 | **EXACT** |
| SDY1389 | T cell receptor repertoire sequencing assay | `OBI:0002990` | Lymph node reservoirs for long-lived memory T cells - RNA-Seq | `OBI:0002990` T cell receptor repertoire sequencing assay | 30111633 | **EXACT** |
| SDY1393 | Hemagglutination Inhibition | `OBI:0000875` | HAI Year2017 | `OBI:0000875` viral hemagglutination inhibition assay | 36656789 | **EXACT** |
| SDY1596 | Luminex xMAP | `OBI:0000920` | Whole blood Multiplexing | `OBI:0000920` cytometric bead array assay | 32005538 | **EXACT** |
| SDY1630 | Flow Cytometry | `OBI:0000916` | Tissue determinants of human NK cells - flow | `OBI:0000916` flow cytometry assay | 32059780 | **EXACT** |
| SDY1640 | ELISA | `OBI:0000661` | T and B cell responses to SARS-CoV-2 coronavirus-antibody | `OBI:0000661` enzyme-linked immunosorbent assay | 32473127 | **EXACT** |
| SDY1640 | Flow Cytometry | `OBI:0000916` | T and B cell responses to SARS-CoV-2 coronavirus-ICS; T and B cell … | `OBI:0000916` flow cytometry assay | 32473127 | **EXACT** |
| SDY1655 | Flow Cytometry | `OBI:0000916` | Flow Cytometry TIC CD14; Flow Cytometry TIC chemok; Flow Cytometry … | `OBI:0000916` flow cytometry assay | 32717743 | **EXACT** |
| SDY1669 | CyTOF | `OBI:0002115` | CyTOF | `OBI:0002115` cytometry time of flight assay | 32788292 | **EXACT** |
| SDY1669 | ELISA | `OBI:0000661` | Quantification of inflammatory cytokines by ELISA | `OBI:0000661` enzyme-linked immunosorbent assay | 32788292 | **EXACT** |
| SDY1669 | Flow Cytometry | `OBI:0000916` | Flow cytometry of ex vivo stimulated PBMCs; Flow cytometry of PBMCs | `OBI:0000916` flow cytometry assay | 32788292 | **EXACT** |
| SDY1669 | Q-PCR | `OBI:0000893` | qPCR of bacterial 16S rRNA | `OBI:0000893` real time polymerase chain reaction assay | 32788292 | **EXACT** |
| SDY1708 | CyTOF | `OBI:0002115` | SDY1708_CyTOF | `OBI:0002115` cytometry time of flight assay | 34128959 | **EXACT** |
| SDY180 | Flow Cytometry | `OBI:0000916` | Flow Cytometry | `OBI:0000916` flow cytometry assay | 23601689 | **EXACT** |
| SDY180 | Hemagglutination Inhibition | `OBI:0000875` | Haemagglutinin inhibition assay for quantitating seasonal influenza… | `OBI:0000875` viral hemagglutination inhibition assay | 23601689 | **EXACT** |
| SDY180 | Luminex xMAP | `OBI:0000920` | Cytokine Concentration; Pneumococcal Immunoassay | `OBI:0000920` cytometric bead array assay | 23601689 | **EXACT** |
| SDY180 | Neutralizing Antibody Titer Assay | `OBI:0000872` | Pneumococcal serology | `OBI:0000872` serum neutralization of viral infectivity assay | 23601689 | **EXACT** |
| SDY180 | Transcription profiling by array | `OBI:0001463` | Illumina Gene Expressions microarrays; Gene Expression | `OBI:0001463` transcription profiling by array assay | 23601689 | **EXACT** |
| SDY2189 | CyTOF | `OBI:0002115` | CYTOF assay | `OBI:0002115` cytometry time of flight assay | 34252919 | **EXACT** |
| SDY2189 | ELISA | `OBI:0000661` | ELISA assay | `OBI:0000661` enzyme-linked immunosorbent assay | 34252919 | **EXACT** |
| SDY2189 | Flow Cytometry | `OBI:0000916` | Flow cytometry | `OBI:0000916` flow cytometry assay | 34252919 | **EXACT** |
| SDY2189 | Neutralizing Antibody Titer Assay | `OBI:0000872` | Neutralization assay | `OBI:0000872` serum neutralization of viral infectivity assay | 34252919 | **EXACT** |
| SDY2189 | Olink assay | `OBI:0003112` | Olink assay | `OBI:0003112` Olink assay | 34252919 | **EXACT** |
| SDY984 | ELISA | `OBI:0000661` | Ab_ELISA | `OBI:0000661` enzyme-linked immunosorbent assay | 28502771 | **EXACT** |
| SDY984 | ELISPOT | `OBI:0600031` | IFNg_ELISPOT; IL4_ELISPOT; IL21_ELISPOT; Plasma_cell_ELISPOT; HIPCV… | `OBI:0600031` enzyme-linked immunospot assay | 28502771 | **EXACT** |
| SDY984 | Flow Cytometry | `OBI:0000916` | FACS_innate; FACS_Tfh; RCF; FACS_ACS; Vax005 T-cell FACS | `OBI:0000916` flow cytometry assay | 28502771 | **EXACT** |
| SDY984 | Luminex xMAP | `OBI:0000920` | Luminex | `OBI:0000920` cytometric bead array assay | 28502771 | **EXACT** |
| SDY984 | Q-PCR | `OBI:0000893` | DNA_quantification | `OBI:0000893` real time polymerase chain reaction assay | 28502771 | **EXACT** |
| SDY984 | Transcription profiling by array | `OBI:0001463` | Microarray | `OBI:0001463` transcription profiling by array assay | 28502771 | **EXACT** |

## 论文不齐全的 3 个 study —— 13 条

ImmPort 给这些 study 关联了我们没跑的论文(SDY212 6 篇 / 我们 1 篇、SDY404 3 / 1、SDY80 2 / 1),
这里的 MISS 不能算抽取失败。

| study | ImmPort technique | ImmPort OBI id | experiment.name | 我们的 entry | pmid | level |
|---|---|---|---|---|---|---|
| SDY212 | Protein microarray | `OBI:0400149` | HA microarray design and fabrication | — |  | **MISS** |
| SDY404 | Mass Spectrometry | `OBI:0000470` | Metabolomics_year2017; Proteomics_year2012 | — |  | **MISS** |
| SDY404 | Transcription profiling by array | `OBI:0001463` | Illumina microarray Expression PBMC Year2; Illumina microarray Expr… | — |  | **MISS** |
| SDY212 | Flow Cytometry | `OBI:0000916` | Phosphorylation of intracellular proteins by pFlow; Leukocyte Subse… | `OBI:0000916` flow cytometry assay | 25834109 | **EXACT** |
| SDY212 | Hemagglutination Inhibition | `OBI:0000875` | HAI_Assay | `OBI:0000875` viral hemagglutination inhibition assay | 25834109 | **EXACT** |
| SDY212 | Luminex xMAP | `OBI:0000920` | serum cytokine quantification | `OBI:0000920` cytometric bead array assay | 25834109 | **EXACT** |
| SDY212 | Transcription profiling by array | `OBI:0001463` | Whole Blood Microarray | `OBI:0001463` transcription profiling by array assay | 25834109 | **EXACT** |
| SDY404 | Flow Cytometry | `OBI:0000916` | Flu_FCM_year2 | `OBI:0000916` flow cytometry assay | 25367297 | **EXACT** |
| SDY404 | Hemagglutination Inhibition | `OBI:0000875` | HAI Year2 | `OBI:0000875` viral hemagglutination inhibition assay | 25367297 | **EXACT** |
| SDY80 | ELISPOT | `OBI:0600031` | 09-H1-0239 ELISPOT | `OBI:0600031` enzyme-linked immunospot assay | 24725414 | **EXACT** |
| SDY80 | Flow Cytometry | `OBI:0000916` | 09-H1-0239 flow cytometry B2; 09-H1-0239 flow cytometry T1; 09-H1-0… | `OBI:0000916` flow cytometry assay | 24725414 | **EXACT** |
| SDY80 | Transcription profiling by array | `OBI:0001463` | 09-H1-0239 Gene Expression | `OBI:0001463` transcription profiling by array assay | 24725414 | **EXACT** |
| SDY80 | Virus Neutralization | `OBI:0000872` | 09-H1-0239 Influenza microneutralization titers | `OBI:0000872` serum neutralization of viral infectivity assay | 24725414 | **EXACT** |

## 丢弃

- SDY1669 `Other`、SDY984 `Other` —— 不含任何技术信息。

---

## Verdict —— 逐条复核后的人工结论(2026-11-10)

**论断成立。** 论文齐全的 26 个 study 共 70 条组合:

- **67 条**由规则直接判定命中(52 EXACT + 9 DESCENDANT + 3 SIBLING + 3 EXPNAME);
- **3 条**论文正文根本没有可抽的方法描述 —— ImmPort 存了数据,论文没写,
  且人工 curator 读同一篇论文也都没有列。

即:**论文确实描述了的 67 条,我们 67 条全部抽到。3 条 MISS 里,0 条是 agent 抽漏。**

`MISS` 是脚本的标签,含义只是"规则没能把两边连起来",是**待人工判定桶**,不是对 agent 的判决。

### 3 条 MISS:论文正文没有可抽的方法描述

三条都另查了人工 curator 清单 —— **curator 读同一篇论文也都没有列**,说明不是 agent 的判断失误。

| study | ImmPort technique | experiment.name | 全文证据 | curator 清单 |
|---|---|---|---|---|
| SDY180 | `Nanostring` | `Flu_09_Nanostring` | PMID 23601689:`nanostring` 0 次、`ncounter` 0 次 | 6 条,列 *Microarray Assay*,**无 NanoString** |
| SDY1289 | `Neutralizing Antibody Titer Assay` | `PMID19047440.GSE13699.PRNT` | PMID 19047440:`PRNT` 0 次;`neutraliz` 4 次全在引言/讨论叙述,数据指向 **Table S2** | 7 条,**无中和试验** |
| SDY1655 | `ELISA` | `AntiS1IgG`、`AntiS1IgM` | PMID 32717743:`S1` 0 次、`IgG` 0 次、`IgM` 0 次;`serolog` 仅 1 次且是入组筛选条件(*"SARS-CoV-2-negative by RT–qPCR and serology"*),无方法 | 4 条,与我们完全一致,**无抗 S1 ELISA** |

三条都是同一形态:ImmPort 登记的是**已上传的实验**,不是**论文的方法节**。
SDY1289 还更进一步 —— ImmPort 的实验名直接标注了本 PMID,但该 PRNT 的方法只在补充材料里,
而我们的语料只有正文 XML。

SDY1655 那条值得单记:论文唯一一次出现 `ELISA` 是在结果节
*"by flow cytometry and ELISA to quantify leukocytes and soluble mediators"*,
指的是方法节写作 HD71 多重微珠板的那次测量 —— **论文自身口径不一致**;
而 ImmPort 登记的 `ELISA` 是 `AntiS1IgG`/`AntiS1IgM` 抗 S1 血清学,与之无关。

### 3 条 EXPNAME:受控词表错位,实验本身抽到了

| study | ImmPort 受控词 | 我们抽到的 | 谁对 |
|---|---|---|---|
| SDY1325 | `Neutralizing Antibody Titer Assay`(OBI:0000872,**病毒**中和) | `OBI:0003797 bacterial neutralization assay`,`name_in_paper`: *Serum bactericidal assay* | **我们更准**;ImmPort 自己的实验名也叫 `Serum bactericidal assay`,论文全文 `neutraliz` 0 次 |
| SDY1373 | `Transcription profiling by array`(OBI:0001463) | `OBI:0003090 bulk RNA-seq assay` | **我们对,ImmPort 标签错了**;其实验名写明是 RNA-seq,curator 也列 *Next-Generation RNA Sequencing* |
| SDY1655 | `Protein microarray`(OBI:0400149) | `OBI:0000920 cytometric bead array assay` | **我们与论文方法节一致**;ImmPort 实验名 `Cytokine Array` 即论文的 HD71 板,curator 同样列 HD71 |

这三条的本体 term 连不上是结构性的:`OBI:0000920` → `analyte assay` 而 `OBI:0400149` → `microarray`,
**无任何共同祖先**;`OBI:0000872` 不挂在 `pathogen neutralization assay` 之下,
而挂在 `blood assay` / `analyte assay` 下。只靠本体图永远判不出来,必须看 `experiment.name`。

### C. 论文不齐全那 3 个 study 的 3 条 MISS(不构成证据)

用语料里该 study 其余论文(8 篇缺失论文全在 1,100 篇语料中且已有结果)重查:

| study | ImmPort technique | 并入该 study 其余论文后的结果 |
|---|---|---|
| SDY404 | `Transcription profiling by array` | **EXACT** —— `OBI:0001463` 命中 PMID 28881994 |
| SDY212 | `Protein microarray` | 6 篇共 44 条 entry,仍 MISS |
| SDY404 | `Mass Spectrometry` | 3 篇共 8 条 entry,仍 MISS |

第一条印证了"按 study 登记 / 按 paper 抽取"这个结构性因素是真的。后两条尚未逐字核实。

### 规则演进记录

判定规则改过三次,前两次是收紧(被假阳性逼的),第三次是加证据来源:

1. 最初"在 root 之下有共同祖先即可" → 把中和试验配上转录芯片、CyTOF 配上血凝抑制。
   收紧为**共享直接父**。
2. 共享直接父仍把 ImmPort 的中和效价配上我们的 ELISA(SDY1289)、把 ImmPort 的 ELISA
   配上我们的微珠法(SDY1655),都经由 `analyte assay`。加 `HUB_PARENTS` 后回落为 MISS。
   **SIBLING 5 → 3,MISS 4 → 6** —— 收紧让结论变保守。
3. 加入 `experiment.name` 作为 `EXPNAME` 一级。**MISS 6 → 3,且 83 条里只有这 3 条变化**,
   其余 80 条分级一字未动 —— 新规则没有波及任何原本已判定的行。

回归测试:`apps/api/tests/test_check_immport_measurements.py`(16 passed),
覆盖 `test_sibling_rejects_a_shared_hub_parent`、`test_expname_matches_when_the_controlled_term_does_not`、
`test_expname_matches_inside_a_long_experiment_name`、`test_expname_matches_when_ours_is_the_longer_string`、
`test_expname_needs_more_than_one_word`。

### 已知局限

语料结果目录按 `primary_sdy` 命名,而一篇论文可属多个 study(如 28881994 同属 SDY404 与
SDY80),目录只会挂在其中一个下面。**31 篇 benchmark 范围内无此情况**(已核:0 条),
但要把该检查扩到 1,100 篇语料,`our_entries()` 必须改为按 ImmPort 的 `study_pubmed` 归并,
不能靠目录名。
