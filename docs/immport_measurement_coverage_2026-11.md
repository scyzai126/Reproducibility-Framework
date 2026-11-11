# Does every assay ImmPort recorded appear in what we extracted?

29 studies, 83 (study, technique) pairs after dropping 2 uninformative row(s). One-directional: assays we found that ImmPort never recorded are expected and not reported.

| group | pairs | EXACT | DESCENDANT | ANCESTOR | SIBLING | NAME | EXPNAME | MISS |
|---|---|---|---|---|---|---|---|---|
| we hold every ImmPort paper | 70 | 52 | 9 | 0 | 3 | 0 | 3 | 3 |
| we hold only some of them | 13 | 10 | 0 | 0 | 0 | 0 | 0 | 3 |

## MISS where we hold every paper of the study — these test the claim

A miss here cannot be blamed on a paper we do not have.

### SDY1289 — ImmPort: `Neutralizing Antibody Titer Assay` (OBI:0000872)

ImmPort papers: ['19047440']; ours: ['19047440']

What we extracted for this study:

- `transcription profiling by array assay` — OBI:0001463 transcription profiling by array assay (pmid 19047440)
- `real time reverse-transcription polymerase chain reaction assay` — OBI:0000911 real time reverse-transcription polymerase chain reaction assay (pmid 19047440)
- `enzyme-linked immunosorbent assay` — OBI:0000661 enzyme-linked immunosorbent assay (pmid 19047440)
- `cell proliferation assay using carboxyfluorescein succinimidyl ester staining` — OBI:0003582 cell proliferation assay using carboxyfluorescein succinimidyl ester staining (pmid 19047440)
- `analyte detection by flow based bead assay` — OBI:0003799 analyte detection by flow based bead assay (pmid 19047440)
- `flow cytometry assay` — OBI:0000916 flow cytometry assay (pmid 19047440)
- `flow cytometry assay (2)` — OBI:0000916 flow cytometry assay (pmid 19047440)
- `cytometric bead array assay` — OBI:0000920 cytometric bead array assay (pmid 19047440)
- `flow cytometry assay (3)` — OBI:0000916 flow cytometry assay (pmid 19047440)

### SDY1655 — ImmPort: `ELISA` (OBI:0000661)

ImmPort papers: ['32717743']; ours: ['32717743']

What we extracted for this study:

- `real time reverse-transcription polymerase chain reaction assay` — OBI:0000911 real time reverse-transcription polymerase chain reaction assay (pmid 32717743)
- `cytometric bead array assay` — OBI:0000920 cytometric bead array assay (pmid 32717743)
- `flow cytometry assay` — OBI:0000916 flow cytometry assay (pmid 32717743)
- `flow cytometry assay (2)` — OBI:0000916 flow cytometry assay (pmid 32717743)

### SDY180 — ImmPort: `Nanostring` (no ontology id)

ImmPort papers: ['23601689']; ours: ['23601689']

What we extracted for this study:

- `transcription profiling by array assay` — OBI:0001463 transcription profiling by array assay (pmid 23601689)
- `flow cytometry assay` — OBI:0000916 flow cytometry assay (pmid 23601689)
- `viral hemagglutination inhibition assay` — OBI:0000875 viral hemagglutination inhibition assay (pmid 23601689)
- `serum neutralization of viral infectivity assay` — OBI:0000872 serum neutralization of viral infectivity assay (pmid 23601689)
- `cytometric bead array assay` — OBI:0000920 cytometric bead array assay (pmid 23601689)
- `single-value binding of antibody with reporter to antigen assay` — OBI:0002773 single-value binding of antibody with reporter to antigen assay (pmid 23601689)


## MISS where ImmPort links papers we did not process

The technique may well be described in one of those papers.

### SDY212 — ImmPort: `Protein microarray` (OBI:0400149)

ImmPort papers: ['23591775', '24337376', '25834109', '27746093', '30842675', '31636302']; ours: ['25834109']

What we extracted for this study:

- `enzyme-linked immunosorbent assay` — OBI:0000661 enzyme-linked immunosorbent assay (pmid 25834109)
- `transcription profiling by array assay` — OBI:0001463 transcription profiling by array assay (pmid 25834109)
- `flow cytometry assay` — OBI:0000916 flow cytometry assay (pmid 25834109)
- `flow cytometry assay (2)` — OBI:0000916 flow cytometry assay (pmid 25834109)
- `cytometric bead array assay` — OBI:0000920 cytometric bead array assay (pmid 25834109)
- `viral hemagglutination inhibition assay` — OBI:0000875 viral hemagglutination inhibition assay (pmid 25834109)
- `viral plaque assay` — OBI:0003798 viral plaque assay (pmid 25834109)
- `genotyping by SNP array assay` — OBI:0002031 genotyping by SNP array assay (pmid 25834109)
- `MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex` — OBI:1110179 MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex (pmid 25834109)

### SDY404 — ImmPort: `Mass Spectrometry` (OBI:0000470)

ImmPort papers: ['25367297', '28881994', '30939133']; ours: ['25367297']

What we extracted for this study:

- `flow cytometry assay` — OBI:0000916 flow cytometry assay (pmid 25367297)
- `viral hemagglutination inhibition assay` — OBI:0000875 viral hemagglutination inhibition assay (pmid 25367297)
- `western blot assay` — OBI:0000854 western blot assay (pmid 25367297)

### SDY404 — ImmPort: `Transcription profiling by array` (OBI:0001463)

ImmPort papers: ['25367297', '28881994', '30939133']; ours: ['25367297']

What we extracted for this study:

- `flow cytometry assay` — OBI:0000916 flow cytometry assay (pmid 25367297)
- `viral hemagglutination inhibition assay` — OBI:0000875 viral hemagglutination inhibition assay (pmid 25367297)
- `western blot assay` — OBI:0000854 western blot assay (pmid 25367297)


## Dropped as uninformative

- SDY1669: `Other`
- SDY984: `Other`
