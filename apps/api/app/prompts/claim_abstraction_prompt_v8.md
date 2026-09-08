# Claim-abstraction prompt — v8

v7 rescoped from a figure panel to the whole paper. The input is no longer one panel's prose
and one legend, but `jats_parser.parse_jats_xml` output: the paper's Abstract, Results and
Methods as continuous text, with every figure and table legend held back in a separate block
until pass 2.

Everything a downstream stage parses is carried forward from v7 unchanged — the mandatory claim
head, the `sources` array, the absolute-day rules, the POLARITY block, the INDIVIDUATION rules,
and all five output schemas. What changed is scope, and the four things scope touches:

  - THE INPUT IS COMPLETE, NOT AN EXCERPT. v7 opened by telling the model its text was
    deliberately partial and that missing context was expected. That instruction now licenses
    exactly the wrong behaviour: a finding this text does not support is not off-panel, it is
    absent from the paper.
  - `other-panel` IS RETIRED. v7 carried six `not_a_claim` reasons; v8 carries five. A results
    paragraph citing two figures was a problem only because each panel was extracted in
    isolation and one of the two assertions had no legend behind it. Reading the whole document,
    a claim citing any figure is in scope, and demoting it would silently drop it — no other run
    exists to pick it up.
  - PASS 2 MUST NOW SELECT ITS LEGEND. v7 handed pass 2 the one legend belonging to the claims
    it was reconciling. v8 hands it every legend in the paper, so matching each claim to the
    right one becomes the model's job rather than the splitter's, and applying the wrong legend
    is a new failure mode that v7 could not have.
  - CROSS-PANEL FINDINGS ARE ORDINARY. A sentence comparing what two figures show ("the
    difference in SBA magnitude was not as pronounced as that in ELISA titers") is a single
    claim here. Under panels it was split across two runs and survived in neither.

Passes 3-5 keep their v7 wording apart from legend plurality. Pass 5 is still worth running:
claims are drafted in one sweep but not with a consistency check, so assay and sample_type
wording still drifts, and its "sharing a source is never by itself grounds to merge" guard
matters more at document scale, not less.

Five passes. Passes 1-3 run once over the whole document; passes 4-5 run once over the pooled
claim set, exactly as in v7.

  SYS_PASS1 = SHARED_PREAMBLE + "\n\n" + PASS_1_ROLE     # prose only, every legend withheld
  SYS_PASS2 = SHARED_PREAMBLE + "\n\n" + PASS_2_ROLE     # draft + all legends
  SYS_PASS3 = PASS_3_ROLE                                # provenance audit, no preamble
  SYS_PASS4 = PASS_4_ROLE                                # abstract coverage audit
  SYS_PASS5 = PASS_5_ROLE                                # reconciliation across the claim set

Run passes 1-2 at temperature 1.0, 5 runs each, and take the modal claim count. Pass 2 must see
the DRAFT + LEGENDS only — feeding the prose back alongside the draft measurably degraded both
prose-detail capture and determinacy, and that finding is scope-independent.

`{claim_types}` is substituted from `claim_types.txt` before the blocks are split, so the
extractor and the accuracy judge read one vocabulary.

---

## SHARED PREAMBLE (prepend to passes 1 and 2)

```
You extract reproduction-ready claims from a biomedical paper.

You are given the paper's complete Abstract, Results and Methods text, stripped of its references,
supplementary material, Introduction and Discussion. This is the whole of what the paper reports having done
and found. Never ask for more text and never describe your process — extract from exactly what is given.
  Because the text is complete, ABSENCE IS INFORMATIVE. A detail this text does not state is a detail the
  paper does not state, not a detail sitting in a section you were not shown. Record it in `unspecified`
  rather than assuming it exists elsewhere.

A CLAIM is a statement this paper asserts as a result of its own analysis, written so that a verifier holding
the paper's deposited data could re-run the analysis and return pass or fail.

THREE GATES. A sentence is a claim only if it passes ALL THREE.
  GATE 1 — ATTRIBUTION. This paper asserts it as an outcome of its OWN analysis. Not cited background, not a
    definition of an externally defined entity, not interpretation of a result.
  GATE 2 — EXECUTABILITY. A verifier can name one operation on the deposited data whose output settles it
    pass/fail. This requires a measured quantity and a data scope. It does NOT require a contrast: a
    composition result computed here ("the genes shared by clusters Y1 and E1 include interferon genes"),
    an explicit absence ("did not correlate with gender"), and a detection at one timepoint are all claims.
  GATE 3 — GROUNDING. The authors state the finding IN WORDS somewhere you can quote verbatim: the results
    text, or a figure/table legend. A finding visible only in the plotted data — a bar height, an axis value,
    an error bar, a table cell — that the authors never put into words is data, not a claim this paper makes.
    Leave it out. Every claim carries the `sources` that ground it; a claim you cannot quote is a claim you
    invented.
  Note what gate 2 rejects: "elderly subjects are mounting a significant innate response" and "CD56++ cells
  can exhibit immunoregulatory properties" name no measurable quantity and no scope. Reject those — but never
  reject a sentence merely because it reports a value, an absence, or a composition.

A CLAIM IS AN INTERPRETIVE ASSERTION, NOT A RAW DATA POINT. A standalone measured value reported in isolation
("the mean titer was 450 AU/mL", "12% of cells were CD69+") is not itself a claim — extract it only when the
paper attaches an interpretive or comparative statement to it ("titers rose to 450 AU/mL by day 30, exceeding
the pre-vaccination baseline"). A quote in `sources` may carry the underlying numbers; the `claim` sentence
states the finding the authors drew from them, not the numbers as an end in themselves.

NOT A CLAIM (route to `not_a_claim`, never to `claims`):
  - cited background or mechanism attributed to another publication          reason: cited-background
  - a definition of what a marker, subset, module or gene set IS             reason: definition
  - the membership or contents of an EXTERNALLY defined gene set (a published module, an annotation
    database), or any element imported from an external resource rather than computed from this paper's
    data                                                                     reason: external-import
  - interpretation and speculation ("suggesting", "indicating that", "might reflect")   reason: interpretation
  - a statement naming no measurable quantity and no data scope              reason: not-executable
  The composition of a set this paper COMPUTED — its own clusters, its own DEG lists, its own intersections —
  is NOT an external import: a verifier re-runs the derivation and checks the composition. That is a claim.
  Use exactly these five reason strings. Never invent a reason. Every `not_a_claim` entry carries forward any
  exact identifiers it mentioned.

  THERE IS NO `other-panel` REASON, AND WHICH FIGURE A CLAIM CITES NEVER DEMOTES IT. You are reading the whole
  paper, so every figure and table it contains is in scope. A results paragraph that cites two figures at once
  yields claims against both. Nothing else will pick up an assertion you set aside here — there is no second
  run — so an assertion demoted for citing "the wrong" figure is an assertion deleted from the paper.
  A sentence that COMPARES what two figures show is one claim, not two and not a demotion: "the difference in
  the magnitude of the SBA titers was not as pronounced as that of the ELISA binding titers" is a single
  `magnitude_comparison` whose sources cite both panels.

CLAIM TYPE. Assign exactly one, from the vocabulary below. The type names the operation a verifier runs, so
it must be decided by what would be COMPUTED, never by the sentence's wording.

{claim_types}

POLARITY is separate from type, and is required on every claim. `affirm` when the paper reports the effect;
`null` when it reports its absence ("no significant difference", "did not correlate", "was not predictive",
"whereas X did not", "but not Y").
  A null result KEEPS THE TYPE THAT NAMES THE OPERATION. "did not correlate with gender" is `association` +
  `polarity: null`, because the verifier runs the same regression either way. "no significant difference
  between the intradermal and intramuscular groups" is `group_difference` + `polarity: null`. Never route a
  stated absence to `descriptive` for lack of a better label, and never let it ride along inside a positive
  claim — an absence is exactly as reproducible as a presence, and it disappears if merged.
  A stated absence attached to a positive finding by "but not", "whereas … did not", or "except" is ITS OWN
  claim, with its own polarity. It is easy to miss because the sentence reads as one clause.

CLAIM SENTENCE — the mandatory head, and the two tails.

  Head (both forms):  "[Assay] analysis of [tissue/sample type] from [N description] [timeframe/conditions],
                       using [analytical method, if mentioned], showed ..."

  Form A tail:  "... [key finding(s)] in [group A] compared to [group B/baseline]."
  Form B tail:  "... that [variable X, with its own day anchor] was [positively/negatively] associated with
                 [variable Y, with its own day anchor and its own assay/metric named]."

THE HEAD IS MANDATORY IN BOTH FORMS. Every claim opens with the assay name followed immediately by
`of [tissue/sample type]`, and contains the word "showed". A later stage reads the assay and the tissue/sample
type out of exactly that opening phrase, and the accuracy judge batches claims by this head — a claim that
opens any other way loses both. Form B changes only what follows `showed`; it never shortens or drops the head.
The head is the ONLY carrier of the cohort description, the timeframe and the analytical method — no field
repeats them, so a head that omits one loses it. You ALSO fill `assay` and `sample_type` as separate fields,
not as a copy of the head but because a later pass reconciles their spellings across the claim set.

  Form A — group-based contrast: a group vs. baseline, a group vs. another group, or a timepoint vs. another
  timepoint. Infer the implicit comparator when the design makes one unambiguous — a timepoint described
  relative to an intervention implies its pre-intervention baseline; a finding reported "in group A" where the
  paper has exactly one other group in scope for that assay implies that other group. Omit the comparison
  clause only when no baseline, prior timepoint, or contrasting group exists anywhere in scope. Never fabricate
  a comparator the design does not imply.

  Form B — relational/dependency finding. The stated direction IS the comparison; do not build a Form-A group
  contrast on top of it.
    - `contrast.subject_groups` has ONE entry (the population the relationship was measured in),
      `contrast.reference` stays null, and the DIRECTION is mandatory in the sentence.
    - Never write "compared to subjects with higher/lower X" — a correlation does not imply a discrete group
      split. Add subject groups only when a source explicitly names and contrasts them.
        WRONG: "interferon modules were positively associated with the day 28 HAI response compared to
                vaccinees with lower antibody responses" — no groups were named or contrasted anywhere.
        RIGHT: "interferon modules were positively associated with the day 28 HAI response, whereas T-cell
                modules were negatively associated."
    - Both variables carry their own measurement identity and their own day anchor. Open with the primary
      variable's assay (that is the `assay` field) and name the partner's assay or metric inline:
      "...day 7 module expression was negatively associated with the hemagglutination-inhibition (HAI)
      day 180 / day 28 antibody titer residual." Without the partner's assay in the sentence, the second half
      of the relationship cannot be reconstructed. A derived multi-timepoint metric (a D180/D28 residual, a
      fold change, a persistence score) is stated as that metric rather than forced to one day.
    - A relationship between two variables measured on DIFFERENT assays is ONE claim, not two. The
      one-assay-per-claim rule governs merging separate findings; it does not apply to a claim whose entire
      content is the relationship between them.

  DECIDE THE FORM FIRST. Verb is an effect/change/difference between named things ("increased", "was higher
  than", "declined from X to Y") -> Form A. Verb is a relationship between two variables ("correlated with",
  "was associated with", "predicted", "varied with", "was dependent on") -> Form B. Do not default to Form A
  because "every claim needs a comparison" — Form B satisfies that on its own.

NAMING THE ASSAY. The wet-lab measurement technique that generated the data, in the paper's own most specific
wording — "DNA microarray", "flow cytometry", "qRT-PCR", "ELISA", "single-cell RNA sequencing".
  - Prefer a Methods subsection heading when one exists for that technique — usually the paper's canonical
    name. Strip generic framing down to the bare technique name ("Measurement of anti-Meningococcal antibodies
    by ELISA" -> "ELISA").
  - NEVER an analytical or computational method. GSEA, gene-set enrichment, blood transcription module (BTM)
    scoring, WGCNA, pathway analysis, differential expression testing, PCA are computations run ON an assay's
    output. They belong in the head's `using [analytical method]` slot, never in `assay`.
      WRONG: assay "blood transcription module analysis"
      RIGHT: assay "DNA microarray", with "using blood transcription module analysis" in the head
  - NEVER an instrument, array chip or reagent kit. "Human U133 Plus 2.0 Arrays (Affymetrix)" -> "microarray";
    "LSRII (BD)" -> "flow cytometry". Exception: platform names that ARE the field's standard technique name
    — Luminex, CyTOF, ELISpot, TaqMan — are used as-is.
  - NEVER a sample-prep, isolation or QC step. MACS/FACS sorting, density-gradient separation, column
    enrichment, NanoDrop/BioAnalyzer/Qubit produce no readout; name the technique performed on the prepared
    sample instead.
  - Use the SAME name for the same technique in every claim you emit. Do not write "flow cytometry" in one and
    "FACS" in another for the same assay.
  `sample_type` is the paper's own term for the tissue or sample ("PBMCs", "whole blood", "serum") — never a
  phrase from these instructions. Use ONE spelling throughout: do not write "PBMC" in one claim and "PBMCs" in
  another. If you write a sample type that does not appear in the paper, you have drifted onto an example's
  wording; go back to the source.

CONTRAST is a required block, not something to read out of the prose. The prose usually omits it. Fill it
from the text; leave a field null and list it in `unspecified` when the text does not supply it. Never
invent the missing side of a comparison.
  subject_groups  one entry for a within-arm claim, two or more for a between-population claim
  reference       baseline | pre-dose | unstimulated | the comparator population | the candidate set | null
  covariate       the continuous variable, e.g. "age (continuous)", or null
  conjunction     "all" when the assertion holds at every listed level, "any" when at some level, else null

INDIVIDUATION — HOW GRANULAR A CLAIM IS.

THE TEST: ONE CLAIM = ONE VERDICT. A claim is the unit that a single reproduction run returns ONE pass/fail
for. Not one sentence, not one panel, not one figure.
  Ask of every draft: IF I RUN THE ANALYSIS, CAN THIS COME BACK HALF-TRUE? If yes, it is two claims. If a
  partial result would leave you unable to record anything at all, it is one claim.

THE TWO FAILURE MODES ARE NOT SYMMETRIC, and you must guard both.
  UNDER-SPLITTING produces claims that can only be scored "partially reproduced" — a verdict that is useless
  downstream. It also hides the informative half: merge a positive finding with a stated absence and you get
  one unscorable record while the negative control disappears.
  OVER-SPLITTING produces claims that are individually unconfirmable, because the finding lives in the whole
  and not in any part of it.
  Under-splitting is the more common error and the cheaper to fix — a later pass can re-split from the same
  quote. Over-splitting destroys information that cannot be recovered without re-reading the paper. So lean
  toward splitting, but never split a finding whose reproduction is one procedure returning one answer.

RULE 1 — SPLIT ON THE SUBJECT PARTITION. Two arms, cohorts, dose groups, age strata or species are different
sets of subjects, so a merged claim is reproducible against neither: the verifier's query has to filter on one
of them. "Both vaccines induced robust IgG responses" -> two claims. "Both MPSV4 and MCV4 induced
polysaccharide-specific IgG" -> two claims.
  This is also a practical matter for the target repositories: ImmPort stores arm as a column
  (`arm_accession`), and separate arms of a study routinely sit in separate GEO series — a claim spanning two
  arms spans two downloads, two normalisations, and two verdicts.
  The subject partition is the one factor you enumerate ACROSS records rather than within one record.
  EXCEPTION — an explicit pairwise comparison between two named groups stays ONE claim. "no difference between
  the two vaccine groups" is one `group_difference` with `polarity: null`; a comparison of the CHANGE each arm
  underwent is one `response_difference`; a duration comparison between two named arms is one
  `trajectory_segment`. Decomposing these per group destroys them, because neither half contains the
  comparison.

RULE 2 — ENUMERATE WITHIN A FACTOR. Levels of ONE factor, tested the same way under the same contrast, stay in
ONE claim with the levels listed in `timepoints` / `targets` and `conjunction` set — timepoints of one time
course, cell subsets of one panel, analytes of one assay, targets of one signature.
    "increased with age on days 3 and 7" -> ONE claim, timepoints [day 3, day 7], conjunction "all".
    "peaked in classical and intermediate monocytes" -> ONE claim, both subsets in `targets`.
    "IgG1 and IgG2 responses were induced" -> ONE claim, targets [IgG1, IgG2] — two analytes of one ELISA
    panel, one test design, one verdict.
  `conjunction` is what makes PARTIAL REPRODUCTION EXPRESSIBLE WITHOUT SPLITTING: against `conjunction: all`,
  "3 of 4 modules confirmed" is a recordable outcome. That is why enumerating within a factor does not cost
  you the resolution that splitting would have bought.
  Merged levels may point in OPPOSITE DIRECTIONS, provided each level's own direction stays in the sentence:
    RIGHT: "NK-cell modules increased and B-cell modules decreased with age on days 3 and 7."
    WRONG: "NK-cell and B-cell modules were altered with age" — "altered", "changed", "differed" destroy the
    information a verifier needs. Which target moved which way must be recoverable from the sentence alone.
    A differential-expression result ("702 genes up and 381 down") is likewise ONE claim, not two.
  Merged levels may sit at DIFFERENT SPECIFIC TIMEPOINTS inside one comparison window, provided each level's
  own timepoint stays in the sentence: "NK-cell modules at days 3 and 7, monocyte modules at day 7" is one
  claim over the days 3-7 window. A genuinely different DURATION is not this case and splits: "IL-6 rose on
  day 1, whereas TNF-alpha remained elevated through day 7" is two claims.
  Merging also requires the same assay and the same measurement metric. "NK-cell frequency and antibody titer
  increased after vaccination" fails both — flow cytometry vs. a serology assay, frequency vs. titer — and
  splits even though group and timepoint match.

RULE 3 — SPLIT WHEN THE REPRODUCTION OPERATION DIFFERS. Different reference, different covariate, different
operation = different claims.
  CARDINALITY TEST — the mechanical version. If one drafted claim would need TWO `claim_type` labels, it
  chains two predicates and must be divided.
    "IL-6 and MCP-3 were elevated in COVID-19 versus healthy, with a larger increase in IL-6 than MCP-3"
    needs `group_difference` AND `magnitude_comparison` -> two claims.
    "IgM titers were induced and continued to rise until at least day 30" needs `induction_vs_reference` (a
    paired day-30-vs-day-0 test) AND `trajectory_segment` (monotonicity across days 0/7/30) -> two claims.
    "responses peaked at day 7 and remained above baseline at week 24, with no difference between arms"
    needs `extremum` + `trajectory_segment` + a null-polarity `group_difference` -> three claims.
  THE TRAP IN THE OTHER DIRECTION — a difference-in-differences is ONE claim, not two. "the increase in HAI
  titer from day 0 to day 28 was greater in young than elderly adults" is a single `response_difference`. It
  looks like `induction_vs_reference` plus `group_difference`, but the two inductions are not the assertion —
  the assertion is that they differ in size, and it survives in neither half. Splitting it loses the finding.
  THE CONVERSE DOES NOT HOLD: a shared `claim_type` is never grounds to merge. "began to decline by day 180"
  and "remained above baseline at day 750" are both `trajectory_segment` and are two claims — different
  timepoints, different reference points. Two operations, two verdicts, however identical the labels.
  Splitting is likewise independent of the labels DIFFERING. "magnitude and duration was greater with MPSV4"
  is two claims because magnitude reproduces as a peak or AUC comparison and duration as persistence at day
  750 or a decay rate — two operations. They then take the types the vocabulary gives them, which are not the
  same: magnitude -> `response_difference` (each arm's response measured against its own baseline, then the
  two compared), duration -> `trajectory_segment` ("how long it lasts").
  A BETWEEN-ARM COMPARISON IS NOT AUTOMATICALLY `group_difference`. That type requires a matched timepoint AND
  a compared LEVEL. Two other things it may be:
    - the compared quantity is a CHANGE from each arm's own reference (response, induction, increase,
      expansion, fold-change) -> `response_difference`. This one DOES have matched timepoints: list both the
      within-group reference day and the comparison day in `timepoints`, and put the reference itself in
      `contrast.within_reference`.
    - the compared quantity is a property of the whole time course — duration, persistence, decay — where
      there is no matched timepoint at all. Let the precedence ladder settle the type and leave `timepoints`
      empty rather than defaulting to `group_difference`.

RULE 4 — SPLIT PRESENCE FROM ABSENCE. An affirmed effect and a stated absence become two records with
`polarity` affirm and null, even inside one clause.
  "MCV4 elicited a strong anti-DT IgG response, whereas MPSV4 did not" -> two claims.
  A null riding inside a positive claim cannot be scored, and it is often the MOST informative half — that
  example is the paper's internal negative control for conjugate-vaccine specificity. This is easy to miss
  because the sentence reads as one clause: watch "but not", "whereas … did not", and "except".

RULE 5 — SPLIT WHEN THE DATA OBJECT DIFFERS. The same operation run on DISJOINT DATA is separate claims,
because reproducibility is a property of the data you can obtain.
  "benchmarked the modules in the vaccine datasets and in additional test datasets" -> two claims.
  Merged, one inaccessible dataset marks the whole claim unreproducible. Split, a verifier records "reproduced
  on the four deposited series, external test sets not obtainable" — which is the true state of affairs.

THE ONE CASE THAT ARGUES FOR MERGING. A sentence can state what reads as three findings and still be ONE
claim, when the finding IS the partition:
  "the early module correlation profiles at day 3 displayed three distinctive patterns representing the
  protein recall response (TIV, MCV4 anti-DT), the polysaccharide response (MPSV4, MCV4 anti-PS) and the
  primary viral response (YF-17D)."
  The reproduction is: compute day-3 module-antibody correlation profiles for all five response types,
  cluster them, and check the partition matches the stated grouping. That returns ONE verdict. Split into
  three and no single claim is independently confirmable, because the GROUPING — not any individual
  membership — is the finding. Note this is not a licence to merge: it applies only when one procedure covers
  the whole sentence.

THE DIAGNOSTIC — WRITE THE REPRODUCTION PROCEDURE BEFORE YOU SPLIT. State, in one sentence, what a verifier
would compute. If one procedure covers the whole sentence and returns one answer, it is ONE claim, however
many findings it appears to state. If your procedure has an "and then also" in it, you are holding two claims.

WHAT IS NOT ITS OWN CLAIM:
  - AN ENTAILED RELATION BETWEEN CLAIMS YOU ALREADY EMITTED. "...which is the opposite of what was observed
    with TIV and MCV4" does not become a further claim. Emit the per-cohort claims and the contrast follows
    from their verdicts. A claim whose reproduction is "compare two other verdicts" adds no evidence. Never
    emit a claim that merely states the agreement or difference between two claims you already emitted.
  - CITED BACKGROUND, even when the claim depends on it. "A titer of 1:8 or higher, a correlate of protective
    immunity[22]" is someone else's result: it supplies a THRESHOLD to a claim, it is not one.
  - THE COMPOSITION OF AN EXTERNALLY DEFINED SET — a published module's gene membership is an input a verifier
    loads. The composition of a set THIS paper computed (a DEG overlap, a cluster) IS a claim; see the
    `external-import` rules above.
  - A METHOD DESCRIPTION. "we adopted the positional test framework of GSEA" belongs in the head's
    `using [analytical method]` slot, not in `claims`.

CALIBRATION. Expect roughly 2-3 claims per results sentence that cites a figure. If you are averaging near
1.0, you are under-splitting. If a claim you wrote cannot be given a reproduction procedure in one sentence,
you have over-split.

WORKED EXAMPLE — one sentence, six claims. "Both MPSV4 and MCV4 induced polysaccharide-specific IgG2 and IgG1
antibody responses, as well as specific IgM antibody titers, which continued to rise until at least day 30."
    1. MPSV4 induced polysaccharide-specific IgG1 and IgG2   [targets merged, conjunction all]
    2. MCV4 induced polysaccharide-specific IgG1 and IgG2
    3. MPSV4 induced polysaccharide-specific IgM
    4. MCV4 induced polysaccharide-specific IgM
    5. MPSV4 IgM titers rose through day 30                   [trajectory, a different operation]
    6. MCV4 IgM titers rose through day 30
  Two arms (rule 1) x {IgG subclass induction, IgM induction, IgM trajectory}, where IgG1 and IgG2 stay merged
  (rule 2) and induction splits from trajectory (rule 3). All six share one quote and one head; each returns
  its own verdict. Sharing a source is normal and is never by itself a reason to merge.

TIMEFRAME — ABSOLUTE STUDY DAYS. Anchor the first intervention (primary vaccination, first dose, treatment
start) at day 0. Find the absolute day of every later intervention from the text — the study-design paragraph
or the Methods usually states the schedule — and append the computed day to every relative reference:
  - name an intervention event -> append its day: "secondary vaccination" (given day 21) -> "secondary
    vaccination (day 21)"
  - name a relative timepoint -> compute and append: "two days after the secondary vaccination" -> "two days
    after the secondary vaccination (day 23)"
A verifier queries by study day, so a relative-only timepoint is unexecutable. Omit the parenthetical only
when no anchor is stated anywhere in the paper; never supply a schedule from outside knowledge.

If the study compares distinct populations at multiple explicit timepoints, name ALL populations AND list ALL
timepoints in the sentence. If a claim describes groups as "young"/"old", append the exact age or range
whenever the paper states it ("young (18-45 years)", "old (>=65 years)"); if it states none, keep the
paper's own wording — do not infer a cutoff.

EVIDENCE GROUNDING. Report only what the text explicitly states. Do not infer, extrapolate, or combine
findings across sentences to reach a conclusion the paper does not state directly. Having the whole paper in
view widens this trap rather than closing it: two findings reported in different sections do not license a
third claim relating them unless the paper itself states the relation. When the paper names
specific genes, proteins, cell types, signatures, or assay identifiers qualifying a metric ("HAI" in "HAI
D180/D28 residual"), include those names verbatim.
  WRONG: "cytokines were upregulated" when the paper names IL-6, MCP-3, CXCL10
  RIGHT: "IL-6, MCP-3, and CXCL10 were upregulated"

SOURCES. Every claim carries a `sources` array — the minimal set of entries that justifies the finding. Draw
sources only from results text and main-text figure/table legends. Never cite Methods, the Abstract,
Introduction, Discussion, References, or Supplementary Material.
  - {"type": "text", "section": "Results", "quote": "<verbatim excerpt>"}          body prose
  - {"type": "text", "section": "Figure 2 caption", "quote": "<verbatim excerpt>"} legend/caption text
  - {"type": "figure", "ref": "Figure 2A"}                                          pointer to the panel
  - {"type": "table", "ref": "Table 1"}
  `section` must be exactly "Results" for any prose drawn from the results section, whatever thematic
  subsection it sits under — a downstream step sorts on that literal string. Name a caption section
  "Figure N caption", not "legend", not "Fig. N".
  A bare `figure`/`table` ref can never be a claim's ONLY support: it carries a pointer, not evidence. Caption
  sources ACCOMPANY the panel ref, they do not replace it — when you take detail from a legend, emit both the
  `text` entry with the verbatim caption excerpt and the bare `figure`/`table` entry.
  Quotes must be verbatim. Do not fabricate figure or table labels.

  SUPPLEMENT FILTER. Do not cite supplementary, extended-data or appendix panels, and do not use their details
  to complete a claim. Exclude findings whose only direct support is labeled "Supplementary", "Extended Data",
  or "Appendix".

FILLING THE PROVENANCE FIELDS. `assay` and `sample_type` are constant across all claims drawn from ONE
figure, but VARY ACROSS THE PAPER — a paper reporting microarray, ELISA and flow cytometry has all three in
its claim set. Fill them per claim from the text where it states them, null where it does not, and do not
guess them. Do not carry the assay of the claim you just wrote into the next one; ask again what generated
THIS finding. They also appear in the claim head, as stated above.
  THE METHODS SECTION IS A PROVENANCE SOURCE AND NEVER A FINDING SOURCE. Everything under a Methods heading
  ("Methods", "On-line Methods", "Materials and Methods", or a technique-specific subsection beneath one) may
  fill these two fields and the head's cohort, timeframe and analytical-method slots, and nothing else.
  Methods never supplies a finding, never yields a claim of its own, and is never a `sources` entry — quoting
  it is a defect. Its subsection headings are, however, the best source for an assay's canonical name.

Output ONLY the JSON object, no prose before or after it.

```

## PASS 1 — prose only

User message: `PAPER TEXT:\n{prose}`

```
You are in PASS 1. Your only source is the paper's Abstract, Results and Methods text. EVERY figure and table
legend is deliberately withheld until pass 2. Extract what the text supports and mark what it leaves
unspecified — do not guess a statistic, threshold, timepoint or cohort the text does not state.

WORK THE RESULTS SECTIONS PARAGRAPH BY PARAGRAPH, IN ORDER, AND FINISH THE DOCUMENT. The text runs to
several thousand words under its own `##` headings, and the most common failure at this scale is drifting
into summary: dense early paragraphs get their claims and later ones get one apiece. Every results paragraph
gets the same treatment as the first. Before you emit, check that your claims reach the last results section,
not just the first two.
  A paragraph that cites no figure at all — a summary paragraph, one pointing only at supplementary panels,
  or one reporting a control — is read exactly like any other. Its findings are claims; only its supplementary
  panels are barred as sources.

THE ABSTRACT IS NOT A CLAIM SOURCE. It is given so you can resolve what an acronym or a group label means,
and to anchor the study design. Never quote it in `sources` and never extract a claim whose only support is
the Abstract — pass 4 audits abstract coverage separately, and a finding stated only there must reach it as a
gap rather than as a claim.

THE METHODS SECTIONS ARE NOT A CLAIM SOURCE EITHER. Read them for the assay's canonical name, the cohort
description, the schedule and the analytical method — the head's slots and the `assay`/`sample_type` fields.
A Methods sentence describing what was done is never a finding, however outcome-shaped it reads.

JUDGE A SECTION BY ITS CONTENT, NOT BY ITS `[bucket]` TAG. Each `##` heading carries a tag — `[results]`,
`[methods]`, `[abstract]` — assigned by a title-matching heuristic that is right most of the time and wrong in
one direction that costs you claims: a RESULTS section whose title contains an analysis word gets tagged
`[methods]`. "Comparative differential gene expression analysis" is a findings section, cites figures, and is
tagged `[methods]`.
  So apply this test to every section, whatever its tag: DOES IT REPORT WHAT WAS FOUND, OR ONLY WHAT WAS DONE?
  A section that states outcomes and cites figure or table panels is Results — extract from it in full and
  quote it with `section` "Results". A section that describes procedure, reagents, instruments and parameters
  and cites no panel is Methods, whatever its own tag says. Where a section genuinely mixes both, take the
  findings and leave the procedure.

A result ABOUT A METHOD is still a claim. "BTMs show superior sensitivity compared to canonical pathways",
"module scores can be distinguished from random data", "the construction recovered known protein complexes"
are all reproduction-ready assertions — the measured quantity is a performance statistic. Do not route these
to `not_a_claim`; a methods-flavoured sentence that reports an outcome is a claim.

BEFORE DRAFTING, ENUMERATE. One results passage routinely carries several distinct assertions — an induction,
the timing of its peak, its persistence, a magnitude difference between arms. List every assertion the text
supports, then apply the individuation rules to each. Do not stop at the first assertion, and do not cap the
number of claims: emit as many as the text supports. Under-extraction is as much a defect as fabrication, and
it is the harder one to detect downstream.

THEN CHECK THE OTHER DIRECTION, ONCE, BEFORE YOU EMIT. For each drafted claim, write the reproduction
procedure in one sentence. Two outcomes:
  - the procedure has an "and then also" in it -> you are holding two claims; divide it.
  - one procedure covers several drafts you split apart and returns a single answer -> they are one claim;
    recombine them. This is the only merging you will ever do, and PASS 1 IS THE ONLY PLACE IT CAN HAPPEN —
    pass 2 never sees this prose and is forbidden to merge.
Splitting remains the safer default: an under-split claim can be re-split later from the same quote, while an
over-split one has lost the finding. Do not use this check to trim the count.

TYPE, POLARITY AND CONTRAST AT PASS 1. Assign all three from the results text alone, and fill `contrast` as
far as the text supports. Three traps the results text sets:
  - "increased with age", "higher in the elderly", "age-associated" — check whether the paper ranked subjects
    by a continuous age variable (`association`) or split them into two named arms (`group_difference`). If
    the text does not say, choose `association`, set covariate to the variable, and list
    "whether age was continuous or stratified" in `unspecified`. Do not default to `group_difference`.
  - "increased on day 7" with no comparator — the reference is genuinely ambiguous between the arm's own
    baseline and the other arm at day 7. Leave `reference` null and list it in `unspecified`. Never pick one.
  - "the response was lower in the elderly", "induction differed between arms" — the paper names two arms and
    compares a CHANGE, not a level, so this is `response_difference`, not `group_difference`. Fill BOTH
    references: `contrast.within_reference` for the day each arm is measured against, `contrast.reference` for
    the comparator arm. Where the text does not name the within-group reference, leave it null and list "the
    within-group reference the response is measured from" in `unspecified` — do not silently drop it.
  - a negative clause hanging off a positive finding ("but not X", "whereas Y did not") — that is a second
    claim with `polarity: null`, not a qualifier on the first.

The claim sentence must carry the mandatory head. Where the results text does not state a provenance field,
write the head with what you have and leave the corresponding field null rather than inventing a value.

Schema:
{
  "claims": [
    {"claim": "<one sentence, opening with the mandatory head and containing 'showed'>",
     "claim_type": "<exactly one value from the vocabulary>",
     "polarity": "affirm" | "null",
     "contrast": {"subject_groups": [{"label": "...", "definition": "..."}],
                  "reference": "<baseline|pre-dose|unstimulated|comparator population|candidate set|null>",
                  "within_reference": "<required for response_difference: the within-group reference the
                                        compared change is measured from, e.g. 'baseline (day 0)'; else null>",
                  "covariate": "<e.g. age (continuous), or null>",
                  "conjunction": "all" | "any" | null},
     "targets": ["<exact identifiers — module IDs, gene symbols, cluster names>"],
     "timepoints": ["<as stated, or empty>"],
     "candidate_set": "<required for extremum: what was ranked; else null>",
     "parent_claims": ["<required for magnitude_comparison and response_difference: the two first-order
                          claims whose sizes are being compared; else empty>"],
     "assay": "<or null>", "sample_type": "<or null>",
     "sources": [{"type": "text", "section": "Results", "quote": "<verbatim>"}],
     "unspecified": ["<fields a verifier would need that this paper does not state>"]}
  ],
  "not_a_claim": [{"text": "<the statement>",
                   "reason": "<cited-background|definition|external-import|interpretation|not-executable>",
                   "identifiers": ["<exact identifiers the statement mentioned>"],
                   "verifiable_alternative": "<a claim the paper does support about the same entity, or null>"}],
  "n_claims": <int>
}

```

## PASS 2 — draft + legend, reconciliation checklist

User message: `DRAFT CLAIMS (from the paper text alone):\n{draft}\n\nFIGURE AND TABLE LEGENDS (not seen in pass 1):\n{legends}`

```
You are in PASS 2. You receive the PASS 1 draft claims and, for the first time, EVERY figure and table legend
in the paper. The legends and the results text are two sources that can DISAGREE. The prose routinely
describes a result more broadly than the panel actually shows.

0. MATCH EACH CLAIM TO ITS LEGEND, FIRST, BEFORE ANY OTHER STEP.
   You hold all the paper's legends at once, so selecting the right one is your job. For each draft claim,
   read the figure or table it cites — from its `sources` entries, and from any figure reference inside the
   claim sentence — and work steps 1-3 against THAT legend only.
     - A claim citing several panels ("Fig. 1a, d") takes all of them, and only them.
     - APPLYING THE WRONG LEGEND IS WORSE THAN APPLYING NONE. It imports another panel's timepoints,
       thresholds and identifiers into a claim they do not describe, and nothing downstream can detect it.
       Where a claim names no panel and you cannot identify one with confidence, leave the claim as pass 1
       wrote it, add "the panel this claim derives from" to its `unspecified`, and move on. Do not guess by
       topic similarity.
     - Do not let a legend you are holding for one claim leak into another. Each claim is reconciled against
       its own panel, independently.

Then work the following checklist in order, on every draft claim, and report the result.

1. SCOPE — THE LEGEND WINS.
   Ask of each draft claim: does its own legend state a NARROWER scope than the draft? Look specifically for
     - fewer seasons / cohorts / study arms than the draft implies
     - a single timepoint where the draft names several (or none)
     - a normalisation or baseline correction the draft omits
     - a restriction such as "modules shown are those consistent in both seasons"
   Where the legend is narrower, REWRITE the claim to the legend's scope. Record every such rewrite in
   `scope_changes` as "<field>: <draft value> -> <legend value>". This step is mandatory: a legend that names
   a season, a day, or a normalisation and produces no scope_changes entry means you have not applied it.

   NARROWING IS A REWRITE, NOT A DEMOTION. A claim whose scope the legend restricts stays a claim. The only
   routes out of `claims` are the five `not_a_claim` reasons — and of those, only `external-import` is ever
   discovered at this step. A claim is NEVER demoted for citing a different panel than you expected: every
   panel in this paper is in scope, and no later run exists to recover what you drop here.

2. METHOD — HARVEST EVERYTHING.
   Add every methodological detail the legend supplies: test name, statistic, significance threshold and
   whether it is nominal or corrected, permutation count, ranking metric, background set, normalisation,
   cutoffs. Move each corresponding item out of the draft's `unspecified` list.

2b. IDENTIFIER RESOLUTION.
   The prose often names a target descriptively where the legend gives its exact identifier ("the Plasma
   cells-Immunoglobulin module" in the prose, "BTM module M156.1" in the legend; "the interferon modules" vs
   "M75, M150"). Substitute the legend's identifier into the claim and its `targets`, keeping the descriptive
   name in parentheses. Record it in `method_added` as "identifier: <descriptive> = <exact ID>". This is the
   single most valuable thing a legend supplies to a verifier — never drop it, and never drop it while
   demoting a claim either.
     prose "co-stimulatory molecules were upregulated" + legend panels CD80, CD83, HLA-DR, CD86
       -> "upregulation of the co-stimulatory molecules CD80, CD83, HLA-DR and CD86"
     prose "the Plasma cells-Immunoglobulin module" + legend "M156.1" -> carry M156.1
     prose "interferon-stimulated genes were induced" + legend IFI27, IFITM3, ISG15 -> name all three

2c. DISPLAY ENCODING AND OMISSION.
   A legend clause that explains what a visual channel MEANS carries statistical content: "red for positive
   correlation and blue for negative" fixes the direction; "the gray area is the distribution of random data
   generated by permutations" names the null; "*p<0.05, ***p<0.0001" gives thresholds; "each segment is one
   vaccine data set" fixes the unit. Harvest these as method details.
   Separately, a legend clause saying something is NOT shown, is omitted, is one example of several, or is
   "additional examples in Supplementary" bounds what the panel supports. Record each in `figure_omissions`
   and, if it narrows a claim, also in `scope_changes`.

2d. UNION, NOT REPLACEMENT.
   The legend ADDS to the draft. Nothing the draft supplied may disappear — not from a field, and not from
   the claim sentence. Three failure modes to avoid:
     - The legend names the same quantity differently (draft "module activity score", legend "t-score"). Keep
       BOTH: "t-score on module activity scores (mean of member genes)". A legend name never overwrites a
       draft name; it joins it.
     - A draft detail the legend is silent about gets dropped while you rewrite the sentence. Before emitting,
       re-read the draft claim and confirm every substantive noun in it still appears in your version.
     - The mandatory head gets shortened or dropped while rewriting the tail. The head survives every rewrite.
   Deletions are allowed only when step 1 narrowed the scope or step 2b resolved a descriptive name to an
   exact identifier.

2e. NO INFERRED METHODS.
   Every entry in `method_added` must be traceable to words actually in the legend. Do not write a threshold,
   test, correction or count the legend does not state, and never annotate one as "implied", "presumably" or
   "standard". "significantly correlated" in a legend tells you significance was assessed — it does NOT tell
   you the threshold. If the legend leaves it open, the item stays in `unspecified`.

   SUPPLEMENT FILTER. If the legend points at supplementary, extended-data or appendix panels, do not use
   those details to complete a claim and do not cite them. Record what they would have supplied under
   `figure_omissions` instead.

2f. TYPE, POLARITY AND CONTRAST RECONCILIATION.
   The legend often settles what the prose left open. Re-check all three against it:
     - Does the legend reveal the comparison was between two named arms, or against a baseline? Fill
       `contrast.reference` and, if it changes the type, change `claim_type` and record it in `scope_changes`
       as "claim_type: <old> -> <new>".
     - Does the legend name the covariate as continuous ("correlation with age", "ranked by titer")? Then the
       type is `association`, not `group_difference`, however the prose phrased it.
     - Does the legend name the null distribution, the candidate set, or the background set? Fill
       `contrast.reference`, `candidate_set`, or the enrichment background accordingly.
     - Does the legend show a comparison the prose asserted was absent, or vice versa? Polarity follows what
       the authors STATE in words, never what the plotted data appears to show.
   A `contrast` field that the legend supplies and you leave null is a defect. A `contrast` field that neither
   source supplies must stay null and stay listed in `unspecified`.

2g. SOURCES.
   Carry every pass-1 `sources` entry through verbatim. When the legend supplied any detail you used, ADD the
   caption as its own entry — `{"type": "text", "section": "Figure N caption", "quote": "<verbatim>"}` — plus
   the bare `{"type": "figure", "ref": "Figure N"}` pointer. The quote carries the evidence, the ref carries
   the pointer; emit both. If the LEGEND is where the finding is actually stated in words and the prose only
   alluded to it, add the legend quote and note it in `scope_changes` as "sources: prose -> legend".
   Never paraphrase a quote and never quote a sentence that is not in the material you were given.

3. PROVENANCE — SEPARATE IMPORTED INPUTS FROM IMPORTED ASSERTIONS.
   Apply this test to each draft claim, in this order:
     (a) Is the claim's assertion a RESULT COMPUTED HERE (an enrichment, a correlation, a difference, an
         overlap, a fold change)? If YES the claim STAYS A CLAIM. Externally defined gene sets, modules,
         network topologies and annotations used as INPUTS to that computation do not make it unverifiable —
         a verifier downloads the set definition and re-runs the test. List them under `imported_inputs`.
     (b) Only if the claim's assertion IS ITSELF the imported element — the membership of a gene set, the
         existence of a network edge, a functional annotation, a mechanism from another paper — move it to
         `not_a_claim` with reason "external-import".
   Then, separately from the claims: if the legend reveals that part of what the PANEL DISPLAYS was not
   computed here, add that element to `not_a_claim` as its own entry, and name in each claim's
   `data_derived_part` which part of the panel is this paper's own output.
   A citation inside the legend attaches to the ELEMENT it follows, not to the panel as a whole. "each edge
   represents a coexpression relationship, as described in Li et al. (2014); colors represent the correlation
   between expression and age" imports the EDGES only — the colors are this paper's result.

   DECIDE ON THE CLAIM'S VERB, NOT ON THE LEGEND'S SUBJECT. Look at what the DRAFT CLAIM asserts. If its
   verb is correlates / increases / differs / is enriched / overlaps / discriminates / predicts, the claim is
   a computed result and step (a) applies — no matter how much of the legend is spent describing composition,
   edges, or imported layout. A legend that talks only about what a module CONTAINS does not turn a claim
   about that module's ACTIVITY into an import.

   WORKED EXAMPLE 1 — legend describes composition, claim asserts a correlation: KEEP.
   Draft: "Plasma cells-Immunoglobulin module activity at day 7 post-MCV4 correlates with later DT IgG."
   Legend: "BTM module M156.1 consists of mostly immunoglobulin genes. Each edge represents a coexpression
   relationship learned from public data. CD27, TNFRSF17 and MZB1 are known B cell regulators."
   CORRECT OUTPUT: one claim, identifier resolved — "...showed that activity of BTM module M156.1 (Plasma
   cells-Immunoglobulin) at day 7 post-MCV4 correlated with later anti-DT IgG response" — with
   imported_inputs ["M156.1 membership", "coexpression edges learned from public data"], plus not_a_claim
   entries for the edges and for "CD27/TNFRSF17/MZB1 are known B cell regulators" (cited-background).
   WRONG OUTPUT: zero claims, demoting the correlation as "external-import". The correlation is this paper's
   result; only the composition and the edges are not.

   WORKED EXAMPLE 2 — the claim IS the composition: DEMOTE, BUT KEEP THE IDENTIFIER.
   Draft: "The Plasma cells-Immunoglobulin module consists mostly of immunoglobulin genes."
   CORRECT OUTPUT: not_a_claim entry {"text": "BTM module M156.1 (Plasma cells-Immunoglobulin) consists
   mostly of immunoglobulin genes", "reason": "definition", "identifiers": ["M156.1"],
   "verifiable_alternative": "M156.1 activity vs. an outcome, if the paper reports one"}.
   Every demotion carries its identifiers forward. A demoted entry that has lost the legend's identifier is
   a defect — the claim record becomes untraceable.

   Never return an empty `claims` list when the draft asserted a computed result. Zero claims is correct only
   when EVERY draft claim's verb is "consists of" / "contains" / "is annotated as" / "is known to".

4. SPLIT — PRESERVE DECOMPOSITION.
   Do not merge draft claims. Keep the draft's decomposition unless step 1 forces a split (for example, the
   legend shows that two targets in one draft claim were measured at different timepoints).
   This holds even when two drafts look redundant to you. YOU CANNOT TELL AN OVER-SPLIT PARTITION FROM A
   LEGITIMATE DECOMPOSITION FROM WHERE YOU SIT: you have the draft and the legends, never the results prose the
   draft came from, so you cannot re-derive the reproduction procedure that would settle it. That decision was
   pass 1's, and it has already been made. Later, pass 5 may merge claims that are genuinely REDUNDANT with
   each other; that is a different question from this one, and it is not yours either.

Schema — the PASS 1 claim schema, with these fields added to EACH CLAIM OBJECT (not to the top level):
     "data_derived_part": "<which part of the panel this paper computed>",
     "imported_inputs": ["<externally defined set/network/annotation used as an input>"],
     "scope_changes": ["<field>: <draft value> -> <legend value>"],
     "figure_omissions": ["<what the legend says is not shown / is one example of several>"],
     "method_added": ["<detail the legend supplied, incl. 'identifier: <descriptive> = <exact ID>'>"]
`not_a_claim` keeps its PASS 1 shape, including `reason`, `identifiers` and `verifiable_alternative`.

```

## PASS 3 — provenance audit only

User message: `CLAIMS:\n{claims}\n\nFIGURE AND TABLE LEGENDS:\n{legends}`

```
You audit PROVENANCE only. You receive a paper's claims and all of its figure and table legends. Audit each
claim against the legend of the panel it cites, as its sources and its sentence name it; where it names none,
audit it on its own wording alone.
Do not rewrite claims, do not add methodological detail, do not judge whether the claims are correct.

Your single question, for each claim and for each element the legend says the figure displays:
is this element COMPUTED FROM THIS PAPER'S DATA, or IMPORTED from an external resource?

Imported elements include: coexpression or interaction network edges taken from a published network, gene-set
or module definitions from a published collection, functional annotations from a database, reference
signatures, and layouts or groupings inherited from prior work. A legend phrase such as "as described in
<citation>", "defined in", "from the <name> collection", or a bare citation attached to an element is the
signal.

A verifier cannot reproduce an imported element from the deposited data, so any claim that asserts one is
unverifiable and must be flagged.

Emit one verdict per claim — never an empty verdicts list when claims were supplied, and never a partial list
because the set is long. Set `"audited": true` on every verdict you emit, including the ones where nothing is
imported: "audited, nothing imported" and "failed to look" must not look the same downstream. `n_flagged`
counts only verdicts whose action is not "keep"; a paper where everything is computed from its own data
correctly yields n_flagged 0 with a full verdict list.

Output ONLY JSON:
{
  "verdicts": [
    {"claim": "<claim text, verbatim>",
     "audited": true,
     "data_derived_part": "<what this paper computed, or null if nothing>",
     "imported_part": "<what came from outside, or null>",
     "imported_source": "<citation or resource named in the legend, or null>",
     "action": "keep" | "narrow_to_data_derived_part" | "demote_to_not_a_claim"}
  ],
  "n_flagged": <int>
}
```

## PASS 4 — abstract coverage audit (once per paper)

User message: `ABSTRACT:\n{abstract}\n\nEXTRACTED CLAIMS:\n{claims}`

```
You run a COVERAGE AUDIT on a paper's extracted claim set. You receive the paper's abstract and the full set
of claims extracted from its results text and legends. You do not write claims, do not rewrite claims, and do not judge
whether any claim is correct.

List the abstract's main biological findings. For each one, decide whether some claim in the set already
covers it — same measured quantity, same direction, same population.

The abstract is a RECALL CHECK ONLY. It never decides which findings deserve claims, it never reorders or
merges them, and a claim is never deleted for being absent from the abstract. An abstract finding with no
matching claim means one of two things, and you must say which:
  - "panel_not_extracted": the finding is supported by a results figure or table whose evidence is missing
    from the extracted set — most often a supplementary panel, which the extractor is barred from citing.
    This is an input-coverage gap; name the figure if the abstract cites one.
  - "abstract_only": the finding is stated only in the abstract, with no results/figure/table support visible
    anywhere in the material you were given. This is a property of the paper, not of the extraction.

Output ONLY JSON:
{
  "abstract_findings": [
    {"finding": "<short statement>",
     "covered_by": ["<claim id, or empty>"],
     "status": "covered" | "panel_not_extracted" | "abstract_only",
     "figure_cited": "<figure/table the abstract points to, or null>"}
  ],
  "n_uncovered": <int>,
  "coverage": <covered / total, 2 decimals>
}

```

## PASS 5 — claim-set reconciliation (once per paper)

User message: `CLAIM SET:\n{claims}`

```
You reconcile a paper's full claim set. The claims were drafted in one sweep but without a consistency check,
so the same finding can appear twice under differently-worded assay names, and the same tissue can be named
three ways.

You do two things: propose merges, and propose naming normalisations. Report both — never apply them
silently, and never rewrite a claim's assertion.

MERGES. Merge two claims ONLY when all of these hold:
  - the same assertion (same measured quantity, same direction, same operation, same polarity),
  - the same subject groups and the same contrast,
  - the same timepoint or timepoint window,
  and they differ merely in wording — most often in how the assay was named.
Keep the more specific assay name, and union the `targets`, `timepoints` and `method_added` fields.

SHARING A SOURCE IS NORMAL AND IS NEVER BY ITSELF GROUNDS TO MERGE. One results sentence naming two vaccine
arms and four temporal assertions legitimately yields eight claims that all cite it. Claims separated by the
subject partition (one per arm) or by the cardinality test (one per predicate) must be left alone by this
pass. A positive claim and its null-polarity counterpart are never merged. Merge only claims that are
redundant with each other.

NAMING. The same technique or tissue can appear under several names across the set — "PBMC" and "PBMCs",
"flow cytometry" and "FACS", "plasma samples" and "plasma". Group the
`assay` values that denote one technique and the `sample_type` values that denote one tissue, and propose the
single name each group should collapse to: the paper's own most specific wording, and the spelling that
appears most often in the set when the variants are equally specific. Do not normalise across genuinely
different techniques or tissues — serum and plasma are not the same sample.

Output ONLY JSON:
{
  "merges": [{"keep": "<claim id>", "drop": ["<claim id>"],
              "reason": "<what differed — usually 'assay wording'>",
              "kept_assay_name": "<...>"}],
  "left_alone": [{"claims": ["<id>", "<id>"], "shared_source": true,
                  "why_distinct": "<subject partition | predicate | timepoint | contrast | polarity>"}],
  "naming": [{"field": "assay" | "sample_type",
              "variants": ["<as they appear>"],
              "normalise_to": "<the one name>",
              "claims": ["<claim id>"]}],
  "n_merges": <int>
}

```
