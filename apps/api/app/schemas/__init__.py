from pydantic import BaseModel


class TextRequest(BaseModel):
    message: str


class FailedFieldCount(BaseModel):
    field: str
    count: int


class CompletnessSummary(BaseModel):
    total_claims: int = 0
    claims_with_failures: int = 0
    failed_groups: int = 0
    failed_fields: list[FailedFieldCount] = []


class SubjectResult(BaseModel):
    group_id: int = 0
    resolvers: dict = {}
    comparison: list = []
    subjects: list[dict] = []
    error: str | None = None


class ClaimResult(BaseModel):
    claim_id: int
    claim_text: str = ""
    source: dict = {}
    study_design: str | None = None
    comparison: list = []
    subject_results: list[SubjectResult] = []


class ParsePaperRequest(BaseModel):
    study_accession: str


class ParsePaperResponse(BaseModel):
    study_accession: str
    claims_sentence: dict = {}
    claims_group: dict = {}


class AgentResponse(BaseModel):
    study_accession: str = ""
    # Populated for claims-based JSON (new format)
    claims: list[ClaimResult] = []
    # Populated for PDF + question mode: step-1 claim sentences from the paper
    paper_claims: list[dict] = []
    # Populated for legacy signature / plain-text / question input
    subject_results: list[dict] = []
    # Populated when the backend needs more information from the user
    type: str | None = None
    question: str | None = None
    # type == "paper_choice": the study's papers, one of which the user picks to analyze
    paper_options: list[dict] = []
    # ImmPort field resolution completeness summary
    completeness: CompletnessSummary | None = None


class AssayRequest(BaseModel):
    """Ask what assays a paper used. At least one identifier is required.

    `verify` and `correct` default on: the point of the endpoint is to return the accurate
    registry, and an unverified one cannot be told apart from a verified one by the reader --
    a `platform` inferred from what a technique usually runs on looks exactly like one copied
    from Methods. Turn them off only to inspect an intermediate round.

    Every request runs all five rounds and costs 1 + N + F + O model calls; nothing is served
    from a previous run.
    """

    study_accession: str = ""
    pubmed_id: str = ""
    verify: bool = True
    correct: bool = True


class AssayResponse(BaseModel):
    study_accession: str = ""
    pubmed_id: str = ""
    paper_title: str = ""
    paper_source: str = ""
    #: canonical key -> the ten-field entry: the CORRECTED registry, as assays.json holds it.
    assays: dict = {}
    #: The same registry with OBI terms attached: assay key -> entry plus obi_id, obi_label,
    #: resource and obi_confidence. Null when round 4 was skipped or failed -- null and {} say
    #: different things, and "the round did not run" must not read as "it found nothing".
    obi: dict | None = None
    #: The free verbatim-quote check. Always present.
    quote_check: dict = {}
    #: build_report() output, or null when verify was false or the paper has no assays.
    verification: dict | None = None
    #: build_correction_report() output. Carries the CORRECT FAILED records -- a repair that was
    #: asked for, paid for and then failed. The count in rounds["correct"]["actions"] does not
    #: say which assay or which field, so dropping this loses the finding entirely.
    corrections: dict | None = None
    #: build_merge_report() output: which entries round 5 folded onto one OBI term, and so are no
    #: longer keys of their own. Null when round 5 was skipped.
    merges: dict | None = None
    #: assay id -> {entry, reason} for assays round 3 set aside as never performed.
    dropped: dict = {}
    #: What each of the five rounds did, and what it cost.
    rounds: dict = {}
    #: Entries that broke the extraction contract; report these, do not skim them.
    contract_warnings: list[str] = []
    #: Where the registry and report came from, and what the request actually cost.
    meta: dict = {}



# ── the assay extraction workspace ────────────────────────────────────────────
# One paper at a time: what can be run, what a run would cost, and what a previous run left.
# Every model here is free to produce -- none of these endpoints calls a model.


class AssayPaperRequest(BaseModel):
    """A paper, by either identifier. At least one is required."""

    study_accession: str = ""
    pubmed_id: str = ""


class AssayPaperSummary(BaseModel):
    """One paper the pipeline can run on, plus whether it already has been."""

    pubmed_id: str = ""
    study_accession: str = ""
    paper_source: str = ""
    paper_title: str | None = None
    has_registry: bool = False
    #: How many assays the stored deliverable holds; null when the paper has never been run.
    assays: int | None = None
    updated_at: str | None = None


class AssayPaperListResponse(BaseModel):
    papers: list[AssayPaperSummary] = []


class AssayPaperAddRequest(BaseModel):
    """Add a paper to the corpus the assay pipeline reads. Costs two NCBI requests, no model calls.

    Both identifiers are required and neither is optional-by-convenience. The XML is filed as
    `<SDY>_<pmid>.xml` and the registry as `<pmid>_<SDY>`, and the two halves are told apart by
    the SDY prefix -- so a PubMed ID alone cannot name the file, and an accession without the
    prefix produces one that reads back inverted.
    """

    pubmed_id: str = ""
    study_accession: str = ""
    #: Re-download a paper already on disk. Off by default: the sentence numbering is derived
    #: from the file, so re-fetching can renumber every [S<n>] a stored registry cites.
    force: bool = False


class AssayPaperAddResponse(BaseModel):
    #: False when the paper was already on disk, which is a success rather than a conflict --
    #: adding the same paper twice is idempotent and the second ask makes no request at all.
    created: bool = False
    paper: AssayPaperSummary
    message: str = ""



class AssayResolveRequest(BaseModel):
    """One identifier, as typed. A PubMed ID, a study accession, or a PMC id."""

    query: str = ""


class AssayResolveCandidate(AssayPaperSummary):
    """One paper the query could mean.

    Extends the corpus summary rather than restating it, so a candidate is usable anywhere an
    AssayPaperSummary is. `title` comes from study_pubmed and `paper_title` (inherited) from the
    XML: they differ, the database one is what a disambiguation list should show, and it is the
    only one that exists for a paper not yet fetched.
    """

    title: str | None = None
    journal: str | None = None
    year: int | None = None
    authors: str | None = None
    doi: str | None = None
    #: False when the pair came from a filename rather than from ImmPort.
    in_db: bool = False
    #: False when ImmPort's pubmed_id for this study is not a PubMed ID -- "TBD", "Not
    #: Applicable" or a PMC id, which 28 of its 1,562 rows are. Such a study is shown but
    #: cannot be run, because the value cannot name a file.
    usable: bool = True
    unusable_reason: str | None = None
    has_xml: bool = False
    #: Set when a run is already under way for this paper. Adopt it; do not start a second.
    active_job_id: str | None = None


class AssayResolveResponse(BaseModel):
    """Every pair the identifier could mean. Never one, chosen on the caller's behalf.

    The mapping is many-to-many in both directions -- SDY212 has six papers, PubMed ID 26682988
    belongs to five studies -- so an empty list and a six-item list are both ordinary answers.
    `reason` is set only when the list is empty; `warning` when the answer is incomplete.
    """

    query: str = ""
    shape: str = ""
    normalized: str = ""
    pmc_id: str | None = None
    pubmed_id: str = ""
    study_accession: str = ""
    candidates: list[AssayResolveCandidate] = []
    total: int = 0
    source: str = "none"
    #: True when the ImmPort database could not be reached and only local files were consulted.
    degraded: bool = False
    warning: str | None = None
    resolved_via: str = ""
    reason: str | None = None



class AssayEstimateRound(BaseModel):
    """What one round would cost.

    `calls` is null when the round cannot be sized yet -- rounds 2, 3 and 4 all depend on how
    many assays the extraction finds, and a paper that has never been run says nothing about
    that. Null rather than a guess: an invented number on a cost gate is worse than no number.

    `exact` is false where the CLI prints "~": the round is sized from the previous run's
    output, which this run re-extracts rather than reuses.
    """

    round: int
    name: str
    calls: int | None = None
    exact: bool = False
    basis: str = ""
    assays: int | None = None
    rejected: int | None = None
    free_matches: int | None = None
    #: Round 4 only: the names the vocabulary misses, which are the ones that cost.
    misses: list[str] = []
    entries: int | None = None
    groups: int | None = None
    #: Round 5 only: the entries that would fold onto one OBI term.
    folds: list[dict] = []


class AssayEstimateResponse(BaseModel):
    pubmed_id: str = ""
    study_accession: str = ""
    paper_source: str = ""
    paper_title: str = ""
    source_chars: int = 0
    registry_dir: str = ""
    registry_dir_display: str = ""
    has_registry: bool = False
    has_verification: bool = False
    has_obi: bool = False
    rounds: list[AssayEstimateRound] = []
    #: Null unless every round is known, so a partial sum can never be presented as the bill.
    total_calls: int | None = None
    total_calls_known: bool = False
    caveat: str | None = None


class AssayRegistryResponse(BaseModel):
    """What a previous run left on disk. Free to read, and never a substitute for a run.

    `benchmark` is the deliverable -- keyed by OBI label, four fields per entry. `assays` is the
    full ten-field record every pass in the chain works from. Both are returned because the
    reading view and the working record answer different questions.
    """

    pubmed_id: str = ""
    study_accession: str = ""
    paper_title: str | None = None
    paper_source: str | None = None
    benchmark: dict = {}
    assays: dict = {}
    obi: dict | None = None
    verification: dict | None = None
    corrections: dict | None = None
    merges: dict | None = None
    dropped: dict = {}
    contract_warnings: list[str] = []
    #: Rebuilt from the stored mapping, so a reader of a finished paper still learns which
    #: assays OBI has no term for. Only the `obi` round is reconstructible from disk.
    rounds: dict = {}
    #: Null when the paper's XML is gone: a check that could not run must not read as one that
    #: passed.
    quote_check: dict | None = None
    updated_at: str | None = None
    registry_dir_display: str = ""
    files: dict = {}


class AssayRunRequest(BaseModel):
    """Start a paid run. The only request in this group that spends anything.

    `acknowledged_calls` is the headline number the caller was shown by
    POST /agent/assays/estimate, echoed back. It is required, and the endpoint refuses without
    it, because the cost gate is a protocol rule rather than a convention of one front end: a
    client must have asked what a run costs before it can start one. Send null only where the
    estimate itself reported the total as unknown.
    """

    study_accession: str = ""
    pubmed_id: str = ""
    acknowledged_calls: int | None = None
    #: Set when the estimate reported `total_calls_known: false`, which is the one case where a
    #: caller legitimately has no number to acknowledge.
    acknowledged_unknown: bool = False
    verify: bool = True
    correct: bool = True


class AssayJobResponse(BaseModel):
    """A run in progress, or the one it became.

    `result` is the whole assay_report payload once the run is done -- typed as a plain dict
    rather than as AssayResponse so that AssayResponse stays the single place enumerating which
    of the report's keys reach a caller.
    """

    id: str = ""
    pubmed_id: str = ""
    study_accession: str = ""
    state: str = "queued"
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    estimate: dict | None = None
    acknowledged_calls: int | None = None
    #: Recorded, never blocking: rounds 2 and 3 were always approximate, so an estimate that
    #: moved between the gate and the run is information, not a reason to refuse.
    estimate_drift: dict | None = None
    progress: dict = {}
    result: dict | None = None
    error: str | None = None
    cancel_requested: bool = False


# ── is this assay registered in ImmPort? ──────────────────────────────────────


class AssayImmportRow(BaseModel):
    """One corpus assay, and whether ImmPort records an experiment for it.

    `status` distinguishes three different "no"s, because they call for different responses:
    `no_experiments` means ImmPort registered nothing at all for the study and no model call
    could change that; `absent` means it registered experiments and this assay is not
    recognisably one of them, which a resolver might yet settle; `unknown_study` means the row's
    study id could not be parsed.
    """

    study: str = ""
    study_accession: str = ""
    assay: str = ""
    experiment_accession: str | None = None
    #: ImmPort's own name for the technique ("Luminex xMAP", "Flow Cytometry"). Null unless matched.
    measurement_technique: str | None = None
    #: "SQL" for a free match, "LLM" when the resolver was asked. Null when unresolved.
    method: str | None = None
    status: str = ""
    study_experiments: int = 0


class AssayImmportStats(BaseModel):
    total: int = 0
    matched: int = 0
    absent: int = 0
    no_experiments: int = 0
    unknown_study: int = 0
    #: What a paid resolve pass would cost: one call per still-unresolved row.
    resolvable: int = 0
    studies_without_experiments: list[str] = []


class AssayImmportResponse(BaseModel):
    rows: list[AssayImmportRow] = []
    stats: AssayImmportStats = AssayImmportStats()
    #: True when the ImmPort database could not be reached; rows are then empty rather than wrong.
    degraded: bool = False
    warning: str | None = None


class AssayImmportCheckRequest(BaseModel):
    """Check a specific set of rows against ImmPort: SQL, then the cached LLM fallback.

    The corpus sweep reads every row on disk; this takes the rows for one paper. A row SQL
    cannot place costs one model call the first time and is answered from the cache after that.
    """

    rows: list[dict] = []


class AssayImmportResolveRequest(BaseModel):
    """Ask the resolver about rows the free pass could not place. **This spends.**

    One model call per row. `acknowledged_calls` is the number the caller was shown, echoed
    back, for the same reason POST /agent/assays/runs requires it: the cost gate is a protocol
    rule rather than a convention of one front end.
    """

    rows: list[dict] = []
    acknowledged_calls: int | None = None
