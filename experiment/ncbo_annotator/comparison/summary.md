# NCBO BioPortal Annotator (OBI) vs the assay agent, against benchmark v5

Agent: `data/31paper_assays/assay_result_v3`. Annotator variants: `<vocab>_<scope>`.

## Scorer mode: default

| metric | agent | full_methods | full_paper | pruned_methods | pruned_paper |
|---|---|---|---|---|---|
| curated rows | 157 | 156 | 155 | 156 | 155 |
| entries | 177 | 81 | 96 | 79 | 94 |
| matched | 156 | 48 | 60 | 48 | 60 |
| MISSED | 1 | 108 | 95 | 108 | 95 |
| EXTRA | 4 | 33 | 36 | 31 | 34 |
| exact (same OBI term as curator) | 140 | 37 | 47 | 37 | 47 |
| OBI ok (same or parent/child) | 145 | 39 | 51 | 39 | 51 |
| obi_exact_rate | 89.7% | 77.1% | 78.3% | 77.1% | 78.3% |
| obi_recall | 92.4% | 25.0% | 32.9% | 25.0% | 32.9% |
| wrong term (CONFLICT) | 5 | 9 | 9 | 9 | 9 |
| no usable term (UNMAPPED) | 6 | 0 | 0 | 0 | 0 |
| recall | 99.4% | 30.8% | 38.7% | 30.8% | 38.7% |
| precision | 88.1% | 59.3% | 62.5% | 60.8% | 63.8% |
| F1 | 93.4% | 40.5% | 47.8% | 40.9% | 48.2% |
| term-only pairs | 6 | 2 | 3 | 2 | 3 |
| calls | 512 | 0 | 0 | 0 | 0 |

## Scorer mode: strict

| metric | agent | full_methods | full_paper | pruned_methods | pruned_paper |
|---|---|---|---|---|---|
| curated rows | 158 | 158 | 158 | 158 | 158 |
| entries | 177 | 81 | 96 | 79 | 94 |
| matched | 156 | 48 | 60 | 48 | 60 |
| MISSED | 2 | 110 | 98 | 110 | 98 |
| EXTRA | 4 | 33 | 36 | 31 | 34 |
| exact (same OBI term as curator) | 140 | 37 | 47 | 37 | 47 |
| OBI ok (same or parent/child) | 145 | 39 | 51 | 39 | 51 |
| obi_exact_rate | 89.7% | 77.1% | 78.3% | 77.1% | 78.3% |
| obi_recall | 91.8% | 24.7% | 32.3% | 24.7% | 32.3% |
| wrong term (CONFLICT) | 5 | 9 | 9 | 9 | 9 |
| no usable term (UNMAPPED) | 6 | 0 | 0 | 0 | 0 |
| recall | 98.7% | 30.4% | 38.0% | 30.4% | 38.0% |
| precision | 88.1% | 59.3% | 62.5% | 60.8% | 63.8% |
| F1 | 93.1% | 40.2% | 47.2% | 40.5% | 47.6% |
| term-only pairs | 6 | 2 | 3 | 2 | 3 |
| calls | 512 | 0 | 0 | 0 | 0 |

## Most frequent EXTRA terms: full_methods (default mode)

| OBI label | papers |
|---|---|
| bacterial lipopolysaccharide detection in plasma assay | 6 |
| bacterial lipopolysaccharide detection in feces assay | 6 |
| RNA protection assay | 4 |
| fluorogenic PCR assay | 2 |
| insecticide resistance by amplification refractory mutation system assay | 2 |
| global chromatin profiling by mass spectrometry assay | 2 |
| single-value binding of antibody with reporter to antigen assay | 2 |
| serum anti-cytomegalovirus antibody level assay | 2 |
| viral hemagglutination inhibition assay | 1 |
| transcription profiling assay | 1 |
| histological assay | 1 |
| hematology assay | 1 |
| chemiluminescent assay | 1 |
| assay for transposase-accessible chromatin using sequencing | 1 |
| serum anti-Epstein-Barr virus antibody level assay | 1 |

## Most frequent EXTRA terms: full_paper (default mode)

| OBI label | papers |
|---|---|
| bacterial lipopolysaccharide detection in feces assay | 7 |
| bacterial lipopolysaccharide detection in plasma assay | 6 |
| RNA protection assay | 4 |
| fluorogenic PCR assay | 2 |
| transcription profiling assay | 2 |
| insecticide resistance by amplification refractory mutation system assay | 2 |
| global chromatin profiling by mass spectrometry assay | 2 |
| single-value binding of antibody with reporter to antigen assay | 2 |
| serum anti-cytomegalovirus antibody level assay | 2 |
| viral hemagglutination inhibition assay | 1 |
| histological assay | 1 |
| hematology assay | 1 |
| enzyme-linked immunosorbent assay | 1 |
| chemiluminescent assay | 1 |
| assay for transposase-accessible chromatin using sequencing | 1 |

## Most frequent EXTRA terms: pruned_methods (default mode)

| OBI label | papers |
|---|---|
| bacterial lipopolysaccharide detection in plasma assay | 6 |
| bacterial lipopolysaccharide detection in feces assay | 6 |
| RNA protection assay | 4 |
| fluorogenic PCR assay | 2 |
| global chromatin profiling by mass spectrometry assay | 2 |
| single-value binding of antibody with reporter to antigen assay | 2 |
| serum anti-cytomegalovirus antibody level assay | 2 |
| viral hemagglutination inhibition assay | 1 |
| transcription profiling assay | 1 |
| histological assay | 1 |
| hematology assay | 1 |
| chemiluminescent assay | 1 |
| assay for transposase-accessible chromatin using sequencing | 1 |
| serum anti-Epstein-Barr virus antibody level assay | 1 |

## Most frequent EXTRA terms: pruned_paper (default mode)

| OBI label | papers |
|---|---|
| bacterial lipopolysaccharide detection in feces assay | 7 |
| bacterial lipopolysaccharide detection in plasma assay | 6 |
| RNA protection assay | 4 |
| fluorogenic PCR assay | 2 |
| transcription profiling assay | 2 |
| global chromatin profiling by mass spectrometry assay | 2 |
| single-value binding of antibody with reporter to antigen assay | 2 |
| serum anti-cytomegalovirus antibody level assay | 2 |
| viral hemagglutination inhibition assay | 1 |
| histological assay | 1 |
| hematology assay | 1 |
| enzyme-linked immunosorbent assay | 1 |
| chemiluminescent assay | 1 |
| assay for transposase-accessible chromatin using sequencing | 1 |
| serum anti-Epstein-Barr virus antibody level assay | 1 |

