"""Data availability: which accessions a paper names, whose data each is, and how the paper uses it."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.accession_validator import NOT_FOUND, UNCHECKED, VERIFIED
from app.agent.accession_validator import result as vresult
from app.agent.data_availability import (
    DEPOSITED,
    OTHER_PAPER,
    REFERENCED,
    REGISTRATION,
    REUSED,
    THIS_PAPER,
    UNCLEAR,
    UNLINKED,
    DataAvailabilityError,
    add_linked_datasets,
    apply_llm_answer,
    apply_validation,
    benchmark_papers,
    build_record,
    clean_pdf_text,
    build_prompt,
    classify_candidates,
    combine,
    data_availability_statement,
    extract_mentions,
    extract_mentions_from_text,
    find_accessions,
    full_text,
    group_mentions,
    llm_candidates,
    load_paper,
    owner_of,
    repository_record,
    settle_drops,
    statement_from_text,
)

JATS_DIR = Path(__file__).resolve().parents[3] / "data" / "JAT_XML"
PMID = "11111111"


def _article(body: str = "", back: str = "") -> str:
    return (f'<article><front><article-meta><title-group><article-title>T</article-title>'
            f'</title-group></article-meta></front><body>{body}</body><back>{back}</back></article>')


def _sec(title: str, *paras: str) -> str:
    return f"<sec><title>{title}</title>" + "".join(f"<p>{p}</p>" for p in paras) + "</sec>"


def _entries(xml: str) -> dict:
    return group_mentions(extract_mentions(xml))


# ------------------------------------------------------------------ regexes


@pytest.mark.parametrize("text, expected", [
    ("GEO GSE13486", ("GSE13486", "GEO")),
    ("SRA SRP123456", ("SRP123456", "SRA")),
    ("ENA ERR1234567", ("ERR1234567", "SRA")),
    ("DDBJ DRX123456", ("DRX123456", "SRA")),
    ("BioProject PRJNA12345", ("PRJNA12345", "BioProject")),
    ("ImmPort SDY1264", ("SDY1264", "ImmPort")),
    ("dbGaP phs000635.v1.p1", ("phs000635.v1.p1", "dbGaP")),
    ("ArrayExpress E-TABM-305", ("E-TABM-305", "ArrayExpress")),
    ("PRIDE PXD012345", ("PXD012345", "PRIDE")),
    ("EGA EGAS00001002345", ("EGAS00001002345", "EGA")),
    ("FlowRepository FR-FCM-ZZ8C", ("FR-FCM-ZZ8C", "FlowRepository")),
    ("doi 10.5281/zenodo.6960", ("10.5281/zenodo.6960", "Zenodo")),
    ("https://zenodo.org/record/6960", ("10.5281/zenodo.6960", "Zenodo")),
    ("10.6084/m9.figshare.1234567", ("10.6084/m9.figshare.1234567", "figshare")),
    ("code at https://github.com/simslab/scHPF .", ("github.com/simslab/scHPF", "GitHub")),
    ("trial NCT01234567", ("NCT01234567", "ClinicalTrials.gov")),
    ("BioSample SAMN02604091", ("SAMN02604091", "BioSample")),
    ("BioSample SAMEA1234567", ("SAMEA1234567", "BioSample")),
    ("GSA-Human HRA000123", ("HRA000123", "GSA")),
    ("GSA CRA001234", ("CRA001234", "GSA")),
    ("NGDC BioProject PRJCA002326", ("PRJCA002326", "GSA")),
    ("CNGB CNP0001234", ("CNP0001234", "CNGB")),
    ("JGA JGAS000123", ("JGAS000123", "JGA")),
    ("MassIVE MSV000079843", ("MSV000079843", "MassIVE")),
    ("jPOST JPST000123", ("JPST000123", "jPOST")),
    ("MetaboLights MTBLS1234", ("MTBLS1234", "MetaboLights")),
    ("map EMD-21374", ("EMD-21374", "EMDB")),
    ("BioImage Archive S-BIAD123", ("S-BIAD123", "BioStudies")),
    ("GISAID EPI_ISL_402124", ("EPI_ISL_402124", "GISAID")),
    ("immuneACCESS 10.21417/B7001Z", ("10.21417/B7001Z", "immuneACCESS")),
    ("Dryad 10.5061/dryad.j1fd7.", ("10.5061/dryad.j1fd7", "Dryad")),
    ("Mendeley 10.17632/abc123xyz.2", ("10.17632/abc123xyz.2", "Mendeley Data")),
    ("Dataverse 10.7910/DVN/TJCLKP", ("10.7910/DVN/TJCLKP", "Dataverse")),
    ("https://osf.io/EZCUJ/", ("osf.io/ezcuj", "OSF")),
    ("Synapse syn2580853", ("syn2580853", "Synapse")),
    ("https://cellxgene.cziscience.com/collections/abc-123", (
        "cellxgene.cziscience.com/collections/abc-123", "CELLxGENE")),
    ("https://data.humancellatlas.org/explore/projects/abc-123", (
        "data.humancellatlas.org/explore/projects/abc-123", "HCA Data Portal")),
    ("https://community.cytobank.org/cytobank/experiments/123 .", (
        "community.cytobank.org/cytobank/experiments/123", "Cytobank")),
    ("http://tools.iedb.org/mhci/", ("iedb.org", "IEDB")),
    ("https://vdjdb.cdr3.net/search", ("vdjdb.cdr3.net", "VDJdb")),
    ("ISRCTN12345678", ("ISRCTN12345678", "ISRCTN")),
    ("ChiCTR2000029308", ("ChiCTR2000029308", "ChiCTR")),
    # loose formats: only with their context word
    ("Broad Single Cell Portal SCP1064", ("SCP1064", "Single Cell Portal")),
    ("Metabolomics Workbench ST000123", ("ST000123", "Metabolomics Workbench")),
    ("PDB 6VXX", ("6VXX", "PDB")),
    ("GenBank: MN908947", ("MN908947", "GenBank")),
    ("EudraCT 2009-015973-11", ("2009-015973-11", "EudraCT")),
])
def test_each_repository_is_recognised(text, expected):
    assert [(a, r) for a, r, _, _ in find_accessions(text)] == [expected]


@pytest.mark.parametrize("text", [
    "the SCP2 gene", "on ST000123 we", "structure 6VXX was", "grant AI057229", "on 2009-015973-11",
])
def test_loose_formats_need_their_context_word(text):
    assert find_accessions(text) == []


def test_resource_links_collapse_to_one_id():
    text = "IEDB https://www.iedb.org and tools http://tools.iedb.org/mhci/ were used."
    assert {a for a, _, _, _ in find_accessions(text)} == {"iedb.org"}


def test_look_alikes_are_not_accessions():
    """GSEA is a method, GPL a chip platform, and a glued prefix is not a word boundary."""
    assert find_accessions("GSEA was run on GPL570 arrays; XGSE12345 and NCT123 are not IDs") == []


# ------------------------------------------------------------------ candidates and text


def test_mention_carries_the_sentences_either_side():
    xml = _article(_sec("Methods", "First sentence here. Data are in GSE11111. Last sentence here."))
    [mention] = extract_mentions(xml)
    assert mention["quote"] == "Data are in GSE11111."
    assert mention["context"] == "First sentence here. Data are in GSE11111. Last sentence here."


def test_a_closing_quote_ends_the_sentence_before_it():
    """SDY1669: a patent title in quotes ran into the DA label's sentence."""
    xml = _article(back='<ack><p>We thank X for \u201cA Title.\u201d Data availability: data are in '
                        'GSE12345.</p></ack>')
    [mention] = extract_mentions(xml)
    assert mention["quote"] == "Data availability: data are in GSE12345."
    assert mention["context"].startswith("We thank X for \u201cA Title.\u201d")


def test_abbreviations_still_do_not_split():
    xml = _article(_sec("Methods", "As in Fig. 2 and Smith et al. we used GSE12345. Next."))
    [mention] = extract_mentions(xml)
    assert mention["quote"] == "As in Fig. 2 and Smith et al. we used GSE12345."


def test_accession_only_in_reference_list_is_ignored():
    xml = _article(_sec("Methods", "Nothing here."),
                   back='<ref-list><ref><mixed-citation>Dataset GSE77777.</mixed-citation></ref></ref-list>')
    assert extract_mentions(xml) == []


def test_table_row_is_read_as_one_unit():
    """Cells only mean something together: "This paper" sits in a different cell from the ID."""
    table = ('<table-wrap><label>Table 1</label><caption><title>Key resources</title></caption>'
             '<table><tbody><tr><td>Raw data</td><td>This paper</td><td>GEO: GSE88888</td></tr>'
             '</tbody></table></table-wrap>')
    entry = _entries(_article(f"<sec><title>Methods</title>{table}</sec>"))["GSE88888"]
    assert entry["evidence"][0]["section"] == "Table: Table 1 Key resources"
    assert entry["evidence"][0]["quote"] == "Raw data | This paper | GEO: GSE88888"


def test_full_text_keeps_da_section_and_drops_references():
    xml = _article(_sec("Introduction", "Background.") + _sec("Methods", "We did things."),
                   back=_sec("Data availability", "Deposited as GSE12121.")
                   + '<ref-list><ref><mixed-citation>Smith J. A cited paper.</mixed-citation></ref></ref-list>')
    text = full_text(xml)
    assert text.startswith("# T")
    assert "## Introduction" in text and "Background." in text
    assert "## Data availability" in text and "GSE12121" in text
    assert "A cited paper" not in text


def test_statement_is_read_from_the_da_section():
    xml = _article(_sec("Methods", "Other text.") + _sec("Data Availability", "All data are in GEO."))
    assert data_availability_statement(xml) == ("All data are in GEO.", "section")
    assert data_availability_statement(_article(_sec("Methods", "x"))) == (None, None)


def test_statement_falls_back_to_an_inline_label():
    xml = _article(back='<ack><p>We thank the donors. Data and materials availability: '
                        'RNA-seq is in GEO (GSE12345).</p></ack>')
    assert data_availability_statement(xml) == (
        "Data and materials availability: RNA-seq is in GEO (GSE12345).", "inline_label")


# ------------------------------------------------------------------ grouping


def test_citation_marks_are_stripped_from_quotes():
    xml = _article(_sec("Methods", 'We compared the cohort ( GSE44444 ) <xref ref-type="bibr">16</xref>.'))
    assert "⁣" not in _entries(xml)["GSE44444"]["evidence"][0]["quote"]


def test_each_mention_says_whether_it_sits_in_the_da_statement():
    xml = _article(_sec("Methods", "Counts are in GSE40000.")
                   + _sec("Data availability", "Our data: GSE40000."))
    entry = _entries(xml)["GSE40000"]
    assert (entry["in_da"], entry["da_source"]) == (True, "section")
    assert [ev["in_da"] for ev in entry["evidence"]] == [False, True]


def test_kinds_separate_code_and_registrations_from_data():
    xml = _article(_sec("Methods", "Code at https://github.com/a/b . Trial NCT01234567. Data GSE10101."))
    entries = _entries(xml)
    assert {a: e["kind"] for a, e in entries.items()} == {
        "github.com/a/b": "code", "NCT01234567": "registration", "GSE10101": "data"}
    # Every text-named ID is sent to the model, registrations included.
    assert {e["accession"] for e in llm_candidates(entries)} == {
        "github.com/a/b", "NCT01234567", "GSE10101"}


# ------------------------------------------------------------------ validation


def test_owner_of():
    assert owner_of(vresult(VERIFIED, [PMID, "2"]), PMID) == THIS_PAPER
    assert owner_of(vresult(VERIFIED, ["2"]), PMID) == OTHER_PAPER
    assert owner_of(vresult(VERIFIED, []), PMID) == UNLINKED
    assert owner_of(vresult(UNCHECKED), PMID) is None
    assert owner_of(None, PMID) is None


def test_validation_attaches_evidence_and_drops_nothing():
    entries = _entries(_article(_sec("Methods", "GSE1001 . GSE1002 . GSE1003 .")))
    apply_validation(entries, {
        "GSE1001": vresult(VERIFIED, [PMID]),
        "GSE1002": vresult(NOT_FOUND, detail="no such record"),
        "GSE1003": vresult(UNCHECKED, detail="timeout"),
    }, PMID)
    assert set(entries) == {"GSE1001", "GSE1002", "GSE1003"}
    assert entries["GSE1001"]["owner"] == THIS_PAPER
    assert entries["GSE1003"]["owner"] is None


def test_without_llm_the_repository_decides_what_is_dropped():
    entries = _entries(_article(_sec("Methods", "GSE1001 . GSE1002 .")))
    apply_validation(entries, {"GSE1001": vresult(VERIFIED, []),
                               "GSE1002": vresult(NOT_FOUND, detail="no such record")}, PMID)
    assert settle_drops(entries) == ["GSE1002 (GEO): no such record"]
    assert set(entries) == {"GSE1001"}


def test_with_llm_the_model_decides_what_is_dropped():
    entries = _entries(_article(_sec("Methods", "GSE1001 . GSE1002 .")))
    apply_validation(entries, {"GSE1001": vresult(VERIFIED, []),
                               "GSE1002": vresult(NOT_FOUND, detail="no such record")}, PMID)
    apply_llm_answer(entries, {
        "GSE1001": {"is_accession": False, "reason": "a figure label"},
        "GSE1002": {"is_accession": True, "repository": "GEO", "role": "this_study", "reason": "r"},
    }, {"GSE1001", "GSE1002"})
    [line] = settle_drops(entries)
    assert line.startswith("GSE1001 (GEO): model says not a repository ID (a figure label)")
    assert "does have a record" in line
    assert set(entries) == {"GSE1002"}  # kept on the model's word, with a REVIEW (below)


def test_repository_linked_dataset_is_added_once():
    entries = _entries(_article(_sec("Methods", "Data in GSE1001 .")))
    assert add_linked_datasets(entries, [("GSE1001", "GEO"), ("GSE1004", "GEO")]) == ["GSE1004"]
    assert entries["GSE1004"]["found_by"] == "repository_link"
    assert "GSE1004" not in {e["accession"] for e in llm_candidates(entries)}


# ------------------------------------------------------------------ combine


def _entry(llm_role=None, owner=None, kind="data", found_by="text", pmids=(), in_da=False,
           model_da=None, status=VERIFIED, llm_repo="GEO", da_reuse_reason=None):
    llm = None if llm_role is None else {
        "is_accession": True, "repository": llm_repo, "role": llm_role,
        "in_da_statement": model_da, "reason": "model reason"}
    return {"accession": "GSE1", "repository": "GEO", "kind": kind, "found_by": found_by,
            "llm": llm, "owner": owner, "owner_pmids": list(pmids), "in_da": in_da,
            "da_reuse_reason": da_reuse_reason, "validation": vresult(status, list(pmids))}


@pytest.mark.parametrize("llm_role, role", [
    ("this_study", DEPOSITED), ("public_data", REUSED), ("reference", REFERENCED),
    ("registration", REGISTRATION),
])
def test_llm_role_is_final(llm_role, role):
    got_role, by, reason, review = combine(_entry(llm_role))
    assert (got_role, by, reason, review) == (role, "llm", "model reason", None)


@pytest.mark.parametrize("kwargs, fragment", [
    # the DA statement names it, but the model calls it someone else's
    (dict(llm_role="public_data", in_da=True, model_da=True), "the DA statement names it"),
    # the pattern search and the model disagree on DA membership
    (dict(llm_role="this_study", model_da=True, owner=THIS_PAPER, pmids=[PMID]),
     "the model reads it as in the DA statement"),
    # the model says this study, outside any DA statement, and the repository links no paper
    (dict(llm_role="this_study", model_da=False, owner=UNLINKED), "no DA statement names it"),
    # the repository links another paper
    (dict(llm_role="this_study", owner=OTHER_PAPER, pmids=["9"]), "links it to PMID 9"),
    # the repository links this paper
    (dict(llm_role="reference", owner=THIS_PAPER, pmids=[PMID]), "links it to this paper"),
    # the repository has no record
    (dict(llm_role="this_study", owner=None, status=NOT_FOUND), "has no record"),
    # the model names another repository
    (dict(llm_role="public_data", owner=UNLINKED, llm_repo="SRA"), "repository is SRA"),
])
def test_disagreements_are_reviewed_not_overridden(kwargs, fragment):
    role, by, _, review = combine(_entry(**kwargs))
    assert role == {"this_study": DEPOSITED, "public_data": REUSED, "reference": REFERENCED}[kwargs["llm_role"]]
    assert by == "llm"
    assert fragment in review


def test_da_listed_reuse_is_not_reviewed_when_the_statement_says_so():
    """eLife's "previously published datasets were used" list: public_data is what it says."""
    entry = _entry("public_data", in_da=True, model_da=True, da_reuse_reason="lead-in")
    assert combine(entry)[3] is None


def test_without_llm_answer_the_id_is_unclear():
    role, by, _, review = combine(_entry(owner=THIS_PAPER, pmids=[PMID]))
    assert (role, by) == (UNCLEAR, "none") and "no model answer" in review


def test_registration_and_repository_link_are_fixed():
    # A registration stays one whatever the model calls it; the model only confirms it is real.
    assert combine(_entry("this_study", kind="registration"))[0] == REGISTRATION
    assert combine(_entry(found_by="repository_link", owner=THIS_PAPER))[:2] == (DEPOSITED, "repository")


# ------------------------------------------------------------------ LLM


def _two_candidates() -> dict:
    return _entries(_article(_sec("Methods", "GSE10001 .", "GSE10002 .", "Trial NCT01234567.")))


def test_prompt_carries_id_repository_guess_sentence_and_da_flag_but_no_repository_check():
    xml = _article(_sec("Methods", "Before. Counts were downloaded from GSE29619. After.")
                   + _sec("Data availability", "Our data: GSE74817."))
    prompt = build_prompt("T", PMID, "FULL PAPER BODY", llm_candidates(_entries(xml)))
    assert f"This paper's PubMed ID: {PMID}" in prompt
    assert "- ID: GSE29619 | pattern match: GEO\n  in the Data Availability statement: no" in prompt
    assert 'sentence: "Counts were downloaded from GSE29619."' in prompt
    assert "context: \"Before. Counts were downloaded from GSE29619. After.\"" in prompt
    assert "- ID: GSE74817 | pattern match: GEO\n  in the Data Availability statement: yes" in prompt
    assert "repository check" not in prompt  # the repositories are asked after the model
    assert '"in_da_statement"' in prompt
    assert prompt.rstrip().endswith("FULL PAPER BODY")


def test_valid_answer_is_attached():
    entries = _two_candidates()
    warnings = apply_llm_answer(entries, {
        "GSE10001": {"is_accession": True, "repository": "GEO", "in_da_statement": True,
                     "role": "this_study", "reason": "own"},
        "GSE10002": {"is_accession": False, "repository": "GEO", "role": None, "reason": "a label"},
        "NCT01234567": {"is_accession": True, "repository": "ClinicalTrials.gov",
                        "in_da_statement": False, "role": "registration", "reason": "trial"},
    }, {"GSE10001", "GSE10002", "NCT01234567"})
    assert warnings == []
    assert entries["GSE10001"]["llm"] == {"is_accession": True, "repository": "GEO", "role": "this_study",
                                          "in_da_statement": True, "reason": "own"}
    assert entries["GSE10002"]["llm"]["role"] is None
    assert entries["GSE10002"]["llm"]["in_da_statement"] is None


def test_missing_da_reading_is_warned_but_the_role_stands():
    entries = _two_candidates()
    [warning] = apply_llm_answer(entries, {
        "GSE10001": {"is_accession": True, "repository": "GEO", "role": "this_study", "reason": "r"},
    }, {"GSE10001"})
    assert "in_da_statement" in warning
    assert entries["GSE10001"]["llm"]["role"] == "this_study"
    assert entries["GSE10001"]["llm"]["in_da_statement"] is None


def test_bad_answers_are_refused():
    entries = _two_candidates()
    warnings = apply_llm_answer(entries, {
        "GSE99999": {"is_accession": True, "role": "this_study"},          # never asked about
        "GSE10001": {"is_accession": "yes", "role": "this_study"},         # not a boolean
        "GSE10002": {"is_accession": True, "role": "maybe"},               # not a role
        "NCT01234567": {"is_accession": True, "role": "registration", "in_da_statement": False,
                        "repository": "Made-up Archive"},                  # unknown repository
    }, {"GSE10001", "GSE10002", "NCT01234567"})
    assert "llm" not in entries["GSE10001"] and "llm" not in entries["GSE10002"]
    # An unknown repository name is ignored, but the rest of that answer stands.
    assert entries["NCT01234567"]["llm"]["repository"] == "ClinicalTrials.gov"
    assert len(warnings) == 4


def test_non_object_answer_raises():
    with pytest.raises(DataAvailabilityError):
        apply_llm_answer(_two_candidates(), ["GSE10001"], {"GSE10001"})


class _StubClient:
    def __init__(self, content: str):
        self.calls = 0
        self.content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls += 1
        self.prompt = kwargs["messages"][0]["content"]
        msg = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.mark.asyncio
async def test_classify_candidates_sends_every_text_named_id():
    entries = _two_candidates()
    add_linked_datasets(entries, [("GSE77777", "GEO")])
    answer = {a: {"is_accession": True, "repository": "GEO", "in_da_statement": False,
                  "role": "public_data", "reason": "r"} for a in ("GSE10001", "GSE10002")}
    answer["NCT01234567"] = {"is_accession": True, "repository": "ClinicalTrials.gov",
                             "in_da_statement": False, "role": "registration", "reason": "r"}
    client = _StubClient(json.dumps(answer))
    assert await classify_candidates("T", PMID, "FULL PAPER BODY", entries, client) == []
    assert client.calls == 1
    for acc in ("GSE10001", "GSE10002", "NCT01234567"):
        assert f"- ID: {acc} |" in client.prompt
    assert "GSE77777" not in client.prompt  # repository-link only: no sentence to read


@pytest.mark.asyncio
async def test_classify_candidates_makes_no_call_without_ids():
    client = _StubClient("{}")
    assert await classify_candidates("T", PMID, "text", {}, client) == []
    assert client.calls == 0


@pytest.mark.asyncio
async def test_unparseable_answer_raises():
    with pytest.raises(DataAvailabilityError):
        await classify_candidates("T", PMID, "text", _two_candidates(), _StubClient("not json"))


# ------------------------------------------------------------------ record


def test_record_uses_the_llm_answer_and_reports_disagreements():
    entries = _two_candidates()
    apply_validation(entries, {"GSE10001": vresult(VERIFIED, [PMID]),
                               "GSE10002": vresult(VERIFIED, ["22222222"]),
                               "NCT01234567": vresult(VERIFIED, [])}, PMID)
    apply_llm_answer(entries, {
        "GSE10001": {"is_accession": True, "repository": "GEO", "in_da_statement": False,
                     "role": "this_study", "reason": "own"},
        "GSE10002": {"is_accession": True, "repository": "GEO", "in_da_statement": False,
                     "role": "this_study", "reason": "ours"},
        "NCT01234567": {"is_accession": True, "repository": "ClinicalTrials.gov",
                        "in_da_statement": False, "role": "registration", "reason": "trial"},
    }, {"GSE10001", "GSE10002", "NCT01234567"})
    record = build_record(PMID, "SDY1", "T", None, entries, warnings=["w"], dropped=["d"],
                          llm_model="gpt-test")
    assert record[DEPOSITED][0]["llm_in_da"] is False
    assert (record["llm_called"], record["llm_model"]) == (True, "gpt-test")
    assert _roles_of(record) == {"GSE10001": DEPOSITED, "GSE10002": DEPOSITED,
                                 "NCT01234567": REGISTRATION}
    assert all(e["decided_by"] == "llm" for e in record[DEPOSITED])
    [review] = record["reviews"]
    assert review.startswith("GSE10002") and "22222222" in review
    assert (record["warnings"], record["dropped"]) == (["w"], ["d"])


def test_record_before_validation_has_no_repository_fields():
    entries = _two_candidates()
    apply_llm_answer(entries, {
        "GSE10001": {"is_accession": True, "repository": "GEO", "in_da_statement": False,
                     "role": "this_study", "reason": "own"},
    }, {"GSE10001"})
    record = build_record(PMID, "SDY1", "T", None, entries, warnings=[], dropped=[],
                          llm_model="gpt-test", validated=False)
    [dep] = record[DEPOSITED]
    assert not {"status", "status_detail", "owner", "owner_pmids"} & set(dep)
    assert dep["llm"]["role"] == "this_study"
    assert _roles_of(record)["GSE10002"] == UNCLEAR  # no answer from the model


def _deposited(acc, status, kind="data", found_by="text", location=None, detail=""):
    item = {"accession": acc, "repository": "GEO", "url": f"u/{acc}", "kind": kind,
            "status": status, "status_detail": detail, "owner_pmids": [PMID], "found_by": found_by}
    if location:
        item["location"] = location
    return item


def test_repository_record_keeps_only_this_studys_data_with_links():
    loc = {"landing_page": "https://geo/GSE1", "download": {"https": "https://ftp/GSE1/"},
           "access": "open", "file_count": 3, "total_size_bytes": 99}
    record = {
        "pmid": PMID, "study": "SDY1", "title": "T",
        DEPOSITED: [_deposited("GSE1", VERIFIED, location=loc),
                    _deposited("GSE2", "private"),
                    _deposited("GSE3", VERIFIED, found_by="repository_link"),
                    _deposited("GSE4", NOT_FOUND, detail="no such record"),
                    _deposited("EGAS1", UNCHECKED, detail="no public lookup"),
                    _deposited("github.com/a/b", VERIFIED, kind="code")],
        REUSED: [_deposited("GSE9", VERIFIED)],
        "reviews": ["GSE1: GEO links it to PMID 9, but the model says this_study"],
    }
    final = repository_record(record)
    repos = {r["accession"]: r for r in final["data_repositories"]}
    assert list(repos) == ["GSE1", "GSE2", "GSE3"]
    assert repos["GSE1"]["landing_page"] == "https://geo/GSE1"
    assert repos["GSE1"]["download"] == {"https": "https://ftp/GSE1/"}
    assert (repos["GSE1"]["file_count"], repos["GSE1"]["total_size_bytes"]) == (3, 99)
    assert repos["GSE1"]["review"] == "GEO links it to PMID 9, but the model says this_study"
    # No location found: the ID's own page stands in, and nothing else is guessed.
    assert (repos["GSE2"]["landing_page"], repos["GSE2"]["download"]) == ("u/GSE2", None)
    assert repos["GSE3"]["found_by"] == "repository_link" and repos["GSE3"]["review"] is None
    assert [(u["accession"], u["status"], u["detail"]) for u in final["unconfirmed"]] == [
        ("GSE4", NOT_FOUND, "no such record"), ("EGAS1", UNCHECKED, "no public lookup")]
    assert set(final) == {"pmid", "study", "title", "data_repositories", "unconfirmed"}


# ------------------------------------------------------------------ a real paper


@pytest.mark.skipif(not (JATS_DIR / "SDY2189_34252919.xml").exists(), reason="JATS corpus not present")
def test_sdy2189_meta_analysis_candidates():
    """Deposits two new GEO series in its DA section; its meta-analysis table lists reused ones."""
    xml = (JATS_DIR / "SDY2189_34252919.xml").read_text(encoding="utf-8")
    entries = group_mentions(extract_mentions(xml))
    assert entries["GSE169159"]["da_source"] == "section"
    assert entries["GSE171964"]["da_source"] == "section"
    for acc in ("GSE13486", "SDY1264", "GSE52245", "SDY1260"):
        assert not entries[acc]["in_da"]
    assert "## Data availability" in full_text(xml)


# ------------------------------------------------------------------ DA statement detection


def _roles_of(record: dict) -> dict[str, str]:
    return {e["accession"]: role for role in (DEPOSITED, REUSED, REFERENCED, REGISTRATION, UNCLEAR)
            for e in record[role]}


def test_inline_label_at_paragraph_start_counts_as_da():
    xml = _article(back=_sec("Additional information",
                             "Accession codes: The microarray data are in GEO under GSE65834."))
    entries = _entries(xml)
    assert entries["GSE65834"]["in_da"] and entries["GSE65834"]["da_source"] == "inline_label"


def test_inline_label_mid_paragraph_covers_only_what_follows_it():
    """SDY1669 style: the label sits in the middle of an Acknowledgments paragraph."""
    xml = _article(back='<ack><p>We thank the GSE11111 consortium. Data and materials availability: '
                        'The CITE-seq data are in GEO (GSE22222).</p></ack>')
    entries = _entries(xml)
    assert not entries["GSE11111"]["in_da"]
    assert entries["GSE22222"]["in_da"]


def test_record_carries_da_membership_and_leaves_unanswered_ids_unclear():
    xml = _article(_sec("Methods", "We downloaded GSE50000 (ref).")
                   + _sec("Data availability", "Our data are in GEO: GSE40000."))
    entries = _entries(xml)
    record = build_record(PMID, "SDY1", "T", "Our data are in GEO: GSE40000.", entries,
                          warnings=[], dropped=[], statement_source="section")
    assert record["da_accessions"] == ["GSE40000"]
    assert record["data_availability_source"] == "section"
    assert _roles_of(record) == {"GSE40000": UNCLEAR, "GSE50000": UNCLEAR}
    by_acc = {e["accession"]: e for e in record[UNCLEAR]}
    assert (by_acc["GSE40000"]["in_da_section"], by_acc["GSE40000"]["da_source"]) == (True, "section")
    assert (by_acc["GSE50000"]["in_da_section"], by_acc["GSE50000"]["da_source"]) == (False, None)
    assert len(record["reviews"]) == 2


def test_reuse_wording_in_the_da_statement_reaches_the_model():
    xml = _article(back=_sec("Data availability", "Public data were downloaded from GSE40000."))
    entries = _entries(xml)
    assert "downloaded" in entries["GSE40000"]["da_reuse_reason"]
    assert "  note: reuse wording 'downloaded'" in build_prompt("T", PMID, "x", llm_candidates(entries))


def test_previously_published_leadin_marks_what_follows():
    xml = _article(back="<sec><title>Major datasets</title>"
                        "<p>The following dataset was generated:</p><p>New data, GSE40001.</p>"
                        "<p>The following previously published datasets were used:</p>"
                        "<p>Old data, GSE40002.</p></sec>")
    entries = _entries(xml)
    assert entries["GSE40001"]["da_reuse_reason"] is None
    assert entries["GSE40002"]["da_reuse_reason"]


@pytest.mark.skipif(not (JATS_DIR / "SDY1669_32788292.xml").exists(), reason="JATS corpus not present")
def test_sdy1669_inline_label_puts_its_geo_series_in_the_da_statement():
    entries = _entries((JATS_DIR / "SDY1669_32788292.xml").read_text(encoding="utf-8"))
    assert entries["GSE152418"]["da_source"] == "inline_label"
    assert entries["GSE155673"]["in_da"]
    assert entries["GSE155673"]["evidence"][0]["quote"].startswith("Data and materials availability")


# ------------------------------------------------------------------ PDF text


PDF_LIKE = (
    "Title of the paper\n\nMethods\nRNA was sequenced and ana-\nlysed as before. Counts were "
    "downloaded from GSE11111.\n\nData availability\nOur data are deposited in GEO under "
    "GSE22222.\n\n" + "Filler sentence. " * 60 + "\nReferences\n1. Smith J, et al. (2010) "
    "A dataset GSE99999.\n2. Doe J (2011) Another.\n"
)


def test_clean_pdf_text_rejoins_hyphens_and_cuts_references():
    text = clean_pdf_text(PDF_LIKE)
    assert "analysed" in text
    assert "GSE99999" not in text
    assert "Data availability:" in text  # a heading on its own line becomes a label


def test_an_early_references_word_does_not_cut():
    text = clean_pdf_text("References\nIntro text GSE1234 here.\n\n" + "More text. " * 50)
    assert "GSE1234" in text


def test_numbered_reference_list_without_heading_is_cut():
    """PNAS prints its reference list with no heading."""
    text = clean_pdf_text("Body GSE22822 text.\n" + "Filler. " * 80
                          + "\n1. Rerks-Ngarm S, et al. (2009) GSE77777 trial.\n2. Zak DE (2012) x.\n")
    assert "GSE22822" in text and "GSE77777" not in text


def test_pdf_mentions_and_statement():
    text = clean_pdf_text(PDF_LIKE)
    mentions = {m["accession"]: m for m in extract_mentions_from_text(text)}
    assert set(mentions) == {"GSE11111", "GSE22222"}
    assert mentions["GSE22222"]["da_source"] == "inline_label"
    assert mentions["GSE11111"]["da_source"] is None
    assert mentions["GSE11111"]["section"] == "PDF text"
    assert "analysed as before" in mentions["GSE11111"]["context"]
    statement, source = statement_from_text(text)
    assert source == "inline_label" and "GSE22222" in statement


def test_load_paper_dispatches_by_suffix(tmp_path):
    xml = tmp_path / "SDY9_12345678.xml"
    xml.write_text(_article(back=_sec("Data availability", "GEO: GSE40000.")), encoding="utf-8")
    paper = load_paper(xml)
    assert (paper["format"], paper["study"], paper["pmid"]) == ("xml", "SDY9", "12345678")
    assert paper["statement_source"] == "section"
    assert [m["accession"] for m in paper["mentions"]] == ["GSE40000"]


PDF_DIR = JATS_DIR.parent / "pdf" / "26papers"


@pytest.mark.skipif(not (PDF_DIR / "SDY1291_23151505.pdf").exists(), reason="PDF not present")
def test_sdy1291_pdf():
    paper = load_paper(PDF_DIR / "SDY1291_23151505.pdf")
    entries = group_mentions(paper["mentions"])
    assert paper["format"] == "pdf"
    assert entries["GSE22822"]["in_da"]  # PNAS "Data deposition:" label
    assert entries["NCT00486408"]["kind"] == "registration"


# ------------------------------------------------------------------ benchmark paper list


def test_benchmark_papers_prefers_xml_then_pdf_then_skips(tmp_path):
    assays, jats, pdfs = tmp_path / "assays", tmp_path / "jats", tmp_path / "pdf" / "sub"
    for d in (assays, jats, pdfs):
        d.mkdir(parents=True)
    for name in ("111_SDY1", "222_SDY2_pdf", "333_SDY3", "444_SDY4"):
        (assays / name).mkdir()
    (assays / "all_assays_OBI.json").write_text("{}")
    (jats / "SDY1_111.xml").write_text("x")
    (pdfs / "SDY1_111.pdf").write_text("x")
    (pdfs / "SDY2_222.pdf").write_text("x")
    (jats / "SDY3_333.xml").write_text("x")
    papers = dict(benchmark_papers(assays, jats, tmp_path / "pdf"))
    assert papers == {"SDY1_111": jats / "SDY1_111.xml", "SDY2_222": pdfs / "SDY2_222.pdf",
                      "SDY3_333": jats / "SDY3_333.xml", "SDY4_444": None}
