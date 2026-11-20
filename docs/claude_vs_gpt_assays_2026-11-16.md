# Claude Fable 5.2 vs gpt-5.4 on 5 benchmark papers (2026-11-16)

A first trial of the assay chain on a Claude model. Five XML papers of the 31-paper benchmark
were run once through the full voted chain (`scripts/run_assay_pipeline.py`) with
`claude-fable-5-2`, then once more with `gpt-5.4` on the same code and the same prompt, and
both were scored against `data/benchmark_assay/benchmark_assay_v5/`. The older gpt-5.4 result
in `assay_result_v3` is shown for reference; it was made with an earlier extraction prompt.

| arm | registries | logs |
|---|---|---|
| Claude Fable 5.2 | `data/benchmark_agent_assays/claude_fable_5_2_v1/` | `logs/claude_fable_5_2_v1/` |
| gpt-5.4 rerun | `data/benchmark_agent_assays/gpt_5_4_rerun_v1/` | `logs/gpt_5_4_rerun_v1/` |
| gpt-5.4 v3 (reference) | `data/benchmark_agent_assays/assay_result_v3/` | n/a |

Each directory has its score reports under `comparison/`. The Claude adapter is
`apps/api/app/agent/anthropic_chat.py` (effort `medium`, no temperature or seed, embeddings
still on OpenAI `text-embedding-3-small`).

## Result

On the same prompt the two models are close, and the difference is within what one run on
five papers can show. Claude finds one more benchmark row; gpt-5.4 maps one more row to the
curators' OBI term and delivers fewer entries, at about a seventh of the cost.

Strict scorer, five papers together:

| | benchmark rows | agent entries | matched | exact OBI | missed | extra | split | recall | precision | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Fable 5.2 | 27 | 32 | 26 | 22 | 1 | 2 | 3 | 96.3% | 81.2% | 0.881 |
| gpt-5.4 rerun | 27 | 29 | 25 | 23 | 2 | 1 | 3 | 92.6% | 86.2% | 0.893 |
| gpt-5.4 v3 (old prompt) | 27 | 29 | 26 | 24 | 1 | 1 | 2 | 96.3% | 89.7% | 0.929 |

Default-mode scorer F1: Claude 0.881, gpt-5.4 rerun 0.909, gpt-5.4 v3 0.945.

Per paper (strict; matched / exact / missed / extra, agent entries in brackets):

| paper | bench | Claude Fable 5.2 | gpt-5.4 rerun | gpt-5.4 v3 |
|---|---|---|---|---|
| SDY1364 23266342 | 3 | 3 / 3 / 0 / 0 [3] | 3 / 3 / 0 / 0 [4] | 3 / 3 / 0 / 0 [4] |
| SDY180 23601689 | 6 | 5 / 5 / 1 / 1 [6] | 5 / 5 / 1 / 0 [5] | 6 / 6 / 0 / 0 [6] |
| SDY1328 26742691 | 5 | 5 / 4 / 0 / 1 [8] | 5 / 5 / 0 / 1 [7] | 5 / 5 / 0 / 1 [7] |
| SDY1373 28854372 | 4 | 4 / 2 / 0 / 0 [4] | 4 / 2 / 0 / 0 [4] | 4 / 2 / 0 / 0 [4] |
| SDY1669 32788292 | 9 | 9 / 8 / 0 / 0 [11] | 8 / 8 / 1 / 0 [9] | 8 / 8 / 1 / 0 [8] |

## Where Claude and the gpt-5.4 rerun differ

**Claude better**

- SDY1669: Claude found "Flow cytometry analysis of PBMCs" (HLA-DR expression). gpt-5.4 missed
  that row in both runs.
- SDY1364: Claude delivered one flow cytometry entry; gpt-5.4 split the benchmark's one row
  into cytokine staining and chemokine receptor staining, in both runs.
- SDY1328: Claude named the Diphtheria and Tetanus ELISAs. gpt-5.4 delivered the Diphtheria
  one as "commercially available kit" (identity NOT_SUPPORTED) and lost the Tetanus one to the
  vote (1 of 3 extractions).

**gpt-5.4 better**

- SDY1328: the multiplex ELISA went to `cytokine assay` under Claude; the curators and gpt-5.4
  have `cytometric bead array assay`.
- SDY1669: the TLR4-based reporter assay went to `reporter gene assay` under Claude; the
  curators and gpt-5.4 have `bacterial lipopolysaccharide detection in plasma assay`.
- SDY180: Claude delivered a CBC entry the benchmark does not have.
- SDY1669: Claude delivered CITE-seq as two entries (gene expression, protein expression);
  gpt-5.4 delivered one, as the curators do.

**Same on both**

- SDY180: neither delivered the commercial pneumococcal polysaccharide antibody immunoassay.
  gpt-5.4 v3 had it, so this is not a model difference. SDY180 was run a second time on
  gpt-5.4 with the same result: across the two runs, 0 of 6 extractions listed the assay. In
  v3, 2 of 3 did, so it was delivered there on a bare majority. The second run is not an
  independent sample (fixed seed, temperature 0, 95% of round-1 prompt tokens served from
  cache), so it shows the miss is reproducible under the current prompt, not how often it
  would happen. The paper names the assay in one sentence only.
- SDY1373: both map RNA sequencing to `bulk RNA-seq assay` (curators: polyA-selected RNA
  sequencing) and the multiplex cytokine assay to `cytometric bead array assay` (curators: the
  parent flow-based term).
- SDY1328: both deliver the anti-HBs antibody assay as an extra entry.
- SDY1669: both keep SIMoA as its own entry on the ELISA term.

Claude's lower precision comes from finer splitting (three ELISAs in SDY1328, two CITE-seq
entries in SDY1669). The scorer counts those as splits of a matched row, not as wrong assays.

## Cost

| paper | Claude calls | Claude prompt tok | Claude completion tok | Claude USD | gpt-5.4 calls | gpt-5.4 prompt tok | gpt-5.4 completion tok | gpt-5.4 USD |
|---|---|---|---|---|---|---|---|---|
| SDY1364 | 10 | 114,716 | 6,513 | 0.92 | 12 | 82,350 | 5,411 | 0.20 |
| SDY1373 | 10 | 170,813 | 7,085 | 1.27 | 10 | 111,443 | 4,439 | 0.20 |
| SDY180 | 17 | 246,670 | 14,849 | 2.21 | 15 | 143,051 | 5,313 | 0.25 |
| SDY1328 | 25 | 356,592 | 20,610 | 3.29 | 21 | 315,893 | 7,604 | 0.52 |
| SDY1669 | 26 | 344,321 | 25,947 | 3.45 | 23 | 194,961 | 12,043 | 0.41 |
| total | 88 | 1,233,112 | 75,004 | 11.14 | 81 | 847,698 | 34,810 | 1.58 |

Claude cost about seven times as much. Three things drive it: the list price ($8/$40 against
$2.50/$15 per million tokens), cache hits only on the three identical round-1 calls (18% of
Claude's prompt tokens were cached against 56% of gpt-5.4's), and about twice the completion
tokens. The Claude figure prices cache writes as plain input, so it runs slightly low. Call
counts exclude embedding calls.

## Five more papers on gpt-5.4 (current prompt)

Five further benchmark papers were run on gpt-5.4 only, chosen because they contain
single-cell or receptor sequencing, the subject of the new prompt rules. Registries are in the
same `gpt_5_4_rerun_v1/` directory, so its `comparison/` reports now cover ten papers
(strict: 58 benchmark rows, 62 entries, 55 matched, 52 exact, 3 missed, 1 extra, F1 0.917).

Strict scorer, these five papers (31 benchmark rows):

| | agent entries | matched | exact OBI | missed | extra | recall | precision | F1 |
|---|---|---|---|---|---|---|---|---|
| gpt-5.4 rerun | 33 | 30 | 29 | 1 | 0 | 96.8% | 90.9% | 0.938 |
| gpt-5.4 v3 (old prompt) | 31 | 30 | 30 | 1 | 0 | 96.8% | 96.8% | 0.968 |

| paper | bench | gpt-5.4 rerun (matched / exact / missed / extra [entries]) | gpt-5.4 v3 |
|---|---|---|---|
| SDY212 25834109 | 8 | 8 / 7 / 0 / 0 [10] | 8 / 8 / 0 / 0 [9] |
| SDY1389 30111633 | 6 | 6 / 6 / 0 / 0 [6] | 6 / 6 / 0 / 0 [6] |
| SDY1654 31624246 | 4 | 4 / 4 / 0 / 0 [4] | 4 / 4 / 0 / 0 [4] |
| SDY1708 34128959 | 3 | 3 / 3 / 0 / 0 [3] | 3 / 3 / 0 / 0 [3] |
| SDY2189 34252919 | 10 | 9 / 9 / 1 / 0 [10] | 9 / 9 / 1 / 0 [9] |

Three papers are identical to v3. The differences:

- SDY2189: the rerun delivers a second CITE-seq entry, "TotalSeq-A libraries" (identity
  NOT_SUPPORTED), which the benchmark does not have as its own row. This is the new
  multimodal-library rule taking effect. SIMOA is missed in both.
- SDY212: the SNP array went to `genotyping by array assay`, the parent of the curators'
  `genotyping by SNP array assay` that v3 picked; and a third flow cytometry entry
  (phospho-Akt / PLC-γ, 2 of 3 extractions) was delivered.

Cost: 90 calls, 1,140,102 prompt tokens (723,968 cached), 41,338 completion, $1.84.

## All 31 papers on gpt-5.4 (current prompt)

The remaining 21 papers (17 XML, 4 PDF) were then run, so `gpt_5_4_rerun_v1/` holds the whole
benchmark. The folder `data/31paper_assays/` was renamed `data/benchmark_agent_assays/` before
scoring.

| scorer | arm | benchmark rows | entries | matched | exact OBI | missed | extra | split | recall | precision | F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| strict | gpt-5.4 rerun | 158 | 176 | 154 | 138 | 4 | 4 | 15 | 97.5% | 87.5% | 0.922 |
| strict | gpt-5.4 v3 | 158 | 176 | 156 | 144 | 2 | 4 | 14 | 98.7% | 88.6% | 0.934 |
| default | gpt-5.4 rerun | 157 | 176 | 154 | 138 | 3 | 4 | 15 | 98.1% | 87.5% | 0.925 |
| default | gpt-5.4 v3 | 157 | 176 | 156 | 144 | 1 | 4 | 14 | 99.4% | 88.6% | 0.937 |

22 of 31 papers score the same as v3. The nine that differ (strict; matched / exact / missed /
extra [entries]):

| paper | bench | rerun | v3 | what changed |
|---|---|---|---|---|
| SDY1260 24336226 | 6 | 6 / 5 / 0 / 0 [8] | 6 / 4 / 0 / 0 [8] | Luminex now on the curators' `antibody detection by cytometric bead array assay` (better) |
| SDY1264 19029902 | 8 | 8 / 5 / 0 / 0 [9] | 8 / 6 / 0 / 0 [9] | RT-PCR mapped to `reverse transcription PCR assay`, curators have the real-time term |
| SDY1288 30150281 | 7 | 6 / 6 / 1 / 0 [7] | 7 / 7 / 0 / 0 [8] | virus isolation lost to the vote (1 of 3 extractions) |
| SDY1293 20078211 | 3 | 3 / 1 / 0 / 0 [3] | 3 / 3 / 0 / 0 [3] | thick blood smears on `blood microbiology assay`; real-time PCR on the non-RT term |
| SDY1294 28687661 | 5 | 5 / 4 / 0 / 0 [5] | 5 / 5 / 0 / 0 [6] | immunofluorescence on `binding assay using fluorescence detection`; one entry fewer |
| SDY1669 32788292 | 9 | 8 / 8 / 1 / 0 [9] | 8 / 8 / 1 / 0 [8] | one more entry, a split |
| SDY180 23601689 | 6 | 5 / 5 / 1 / 0 [5] | 6 / 6 / 0 / 0 [6] | pneumococcal immunoassay not extracted (0 of 3) |
| SDY212 25834109 | 8 | 8 / 7 / 0 / 0 [10] | 8 / 8 / 0 / 0 [9] | SNP array on the parent term; third flow entry |
| SDY2189 34252919 | 10 | 9 / 9 / 1 / 0 [10] | 9 / 9 / 1 / 0 [9] | second CITE-seq entry (new prompt rule) |

Seven exact rows were lost and one gained (144 to 138). Five of the seven are OBI term picks
on an assay both runs extracted, and two are assays the vote or the extraction dropped. Only the SDY2189 extra entry is traceable to
the new single-cell rule; none of the other changed rows involves single-cell or receptor
sequencing. The rest is the size of difference two runs of the same chain produce, and this
comparison cannot separate that from a prompt effect.

Cost of the 21 papers: 332 calls, $6.33. All 31: 503 calls, $9.75. Every flagged line of the
21 runs is in `logs/gpt_5_4_rerun_v1/flagged_lines_21papers.txt`.

## What the new prompt rules caused (debugged from `assays_raw.json`, no new calls)

Caused by the new multimodal rule:

1. **SDY2189, a second CITE-seq entry.** All three extractions split CITE-seq into a
   transcriptome entry and an antibody-derived-tag entry, as the rule's "surface protein read
   by antibody-derived tags ... is its own entry" asks. The paper has no assay name for the
   protein half, so the model named it after the library product, "TotalSeq-A libraries"; the
   verifier marks that identity NOT_SUPPORTED and nothing repairs an identity. Both halves map
   to the CITE-seq OBI term, and round 5 cannot fold them because the model gave the
   transcriptome half `standard_technique_name` "single-cell RNA sequencing" and the protein
   half "CITE-seq". The benchmark has one CITE-seq row.
2. **SDY2189 and SDY1669, the CITE-seq entry's `readouts` lost the protein half** ("single-cell
   transcriptomes" where v3 had "... and antibody-derived tag measurements"). In SDY1669 one
   extraction of three split, so the split-off "DNA-labeled antibody staining" went to
   MINORITY and is not delivered. The score is unchanged there.
3. **The rule is applied unevenly**: 3 of 3 extractions split in SDY2189, 1 of 3 in SDY1669,
   for the same technique.

Not caused by the rule, as far as the files show:

- **Five changed OBI terms** (SDY1264, SDY1293 x2, SDY1294, SDY212). The extracted name,
  technique and sample are the same in both runs (in SDY212 and the SDY1293 smear, readouts
  too); round 4 picked a neighbouring term from the same candidates. Round 4 does not read the
  extraction prompt.
- **SDY1294, one entry fewer.** All six extractions in both runs list "T cell function"; this
  time the verifier ruled its identity CONTRADICTED and it was dropped. The benchmark has no
  such row.
- **SDY180 and SDY1288, two missed rows.** Each assay is named once in its paper and was at
  the vote threshold in v3 (2 of 3). Now 0 of 3 and 1 of 3. A prompt edit changes every
  sampled reply even at a fixed seed, so this may be an indirect effect, but nothing on disk
  separates it from run-to-run variation. Running the old prompt on the current code for these
  two papers would.
- **SDY212, a third flow entry** (phospho-Akt / PLC-γ, 2 of 3 extractions; v3 had it in 0 of
  3 under that name). Same caveat.

## Old-prompt control and the CITE-seq fix

**Control.** The four papers with a missed row were run with the committed prompt
(`apps/api/app/prompts/extract_assays_old.txt`, identical to `HEAD`) on the current code;
registries in `gpt_5_4_old_prompt_v1/`. All four miss the same row as under the new prompt
(SDY180 0 of 3 extractions, SDY1288 1 of 3, SDY1669 0 of 3, SDY2189 SIMOA 1 of 3). The misses
are therefore not caused by the prompt edit; SDY180 and SDY1288 passed the vote in October on
this same prompt, so the cause is a code change since then or model-side variation. The
control also confirms the CITE-seq split: 3 of 3 old-prompt extractions keep CITE-seq as one
entry with both analytes in `readouts`, in both papers. Cost $1.54, 85 calls.

**Fix.** The multimodal paragraph in `extract_assays.txt` and `extract_assays_pdf.txt` now
splits only the transcriptome from receptor repertoires, and a second paragraph says a
technique named for transcriptome plus surface protein (CITE-seq, REAP-seq) is one entry with
both analytes in `readouts`. SDY1669 and SDY2189 were rerun in `gpt_5_4_rerun_v1/` (old logs
in `logs/gpt_5_4_rerun_v1/before_cite_fix/`): all six extractions give one CITE-seq entry,
technique "CITE-seq", both analytes in `readouts`. Both papers now score as in v3
(SDY1669 8 / 8 / 1 / 0 [8], SDY2189 9 / 9 / 1 / 0 [9]). Cost $0.76, 45 calls.

31 papers with the fixed prompt (29 from the first pass, these two rerun):

| scorer | entries | matched | exact OBI | missed | extra | split | recall | precision | F1 |
|---|---|---|---|---|---|---|---|---|---|
| strict | 174 | 154 | 138 | 4 | 4 | 13 | 97.5% | 88.5% | 0.928 |
| default | 174 | 154 | 138 | 3 | 4 | 13 | 98.1% | 88.5% | 0.930 |

## Limits of this comparison

- **One run each, five papers.** Claude cannot be given a temperature or seed, and gpt-5.4's
  own two runs differ by one matched row and one exact term. A gap of one row or one term
  between the models is not a stable ranking.
- **Effort was `medium`**, the adapter's setting. Higher effort was not tried.
- **The v3 column used an earlier prompt** (before the single-cell and receptor sequencing
  rules in `extract_assays.txt`), so only the rerun column is like for like with Claude.
- The four PDF-only benchmark papers cannot be run on Claude: the adapter does not translate
  PDF file parts.
