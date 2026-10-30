"""Answer "what assays did this paper use?" end to end: extract, verify, correct, map to OBI.

This is the pipeline behind POST /agent/assays. It chains the two prompts a front-end
question needs — prompts/extract_assays.txt to build the registry, prompts/verify_assays.txt
to judge it — with the free deterministic quote check in between, and finishes by resolving
the corrected registry against the OBI vocabulary in data/OBI.

A paper with no JATS XML falls back to its PDF, and round 1 then reads prompts/
extract_assays_pdf.txt with the PDF attached instead. Only that round differs; the rest of the
chain is the same code on the same files. Entries from a PDF carry `sentence_ids: []` and a null
`source`, because there are no `[S<n>]` markers in a PDF to locate a quote against, so the quote
check searches the whole document and neither field can be derived.

**Every request runs all five rounds.** Results are written to disk under
data/31paper_assays, and the files are the same ones scripts/run_assay_pipeline.py writes
and scripts/run_assay_merge.py reads — but a stored one is never served back. A request costs EXTRACTIONS + N + F + O calls every time.

Reuse used to be the default, and it was removed rather than narrowed. Round 1's cache could
not be dropped on its own: a freshly extracted registry invalidates any stored verification
(the verdicts describe different entries), which in turn invalidates the corrections derived
from them, so the rounds are reusable together or not at all. What reuse cost in exchange was
that an edit to extract_assays.txt had no effect on a paper that had already been run, and
nothing in the output said so.

The quote check runs on every response. It costs nothing, it is the one signal that does not
depend on a model's opinion, and a registry that was fine when written can stop matching if
the paper's XML is re-fetched.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from openai import AsyncOpenAI

from app.agent import assay_trace
from app.agent.assay_consensus import consensus
from app.agent.assay_corrector import (
    build_report as build_correction_report,
    correct_registry,
    drop_rejected,
    flagged_groups,
    rejected_assays,
    uncorrectable_flags,
)
from app.agent.assay_extractor import (
    AssayExtractionError,
    contract_warnings,
    extract_assays,
    has_methods_section,
    paper_names,
    trim_registry,
)
from app.agent.assay_extractor_pdf import extract_assays_from_pdf
from app.agent.assay_merger import (
    blocked_folds,
    build_merge_report,
    canonical_groups,
    canonicalize_registry,
    key_map,
)
from app.agent.assay_obi_mapper import (
    _build_lookup,
    _index_children,
    enrich_assays_with_obi,
)
from app.agent.assay_registry import CORPUS_ROOT, RESULT_VERSION, normalize_assay_name
from app.agent.assay_verifier import (
    build_report,
    check_quote_verbatim,
    check_source_section,
    derive_evidence_fields,
    drop_absent_aliases,
    mark_identity_reviews,
    verify_registry,
)
from app.agent.jats_parser import (
    article_title,
    number_sentences,
    parse_jats_xml,
    sentence_sections,
)
from app.agent.paper_reader import extract_pdf_text
from app.config import settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
XML_ROOT = _REPO_ROOT / "data" / "JAT_XML"
#: Searched only when a paper has no JATS XML. Both roots are module-level and re-read at call
#: time so tests can monkeypatch either.
PDF_ROOT = _REPO_ROOT / "data" / "pdf"
#: `data/31paper_assays/<RESULT_VERSION>`: the benchmark papers' registries. The version lives in
#: assay_registry so claim resolution and this chain read the same folder; CORPUS_ROOT is the
#: unversioned parent, where the ImmPort cache sits.
REGISTRY_ROOT = CORPUS_ROOT / RESULT_VERSION
#: Where a paper outside the benchmark keeps its results: `<pmid>_<SDY>[_pdf]/`, holding its
#: assay registry and its data-repository files together. Benchmark papers stay in REGISTRY_ROOT,
#: so the corpus table (built from REGISTRY_ROOT alone) never picks up a new paper.
CACHE_ROOT = _REPO_ROOT / "data" / "cache" / "assays"
#: Marks a registry built from a PDF because the paper has no JATS XML: `<pmid>_<SDY>_pdf`.
#: Its entries carry no sentence ids, so the folder name says so up front.
PDF_DIR_SUFFIX = "_pdf"

#: How many extraction calls round 1 makes per paper, voted into one registry by
#: assay_consensus.consensus. Three, not one: measured over three papers run twice each with the
#: same prompt, two came back with an inventory one entry longer in one run than the other, and
#: rounds 2-4 then spent ~25 calls verifying whichever inventory happened to come out. Two more
#: extraction calls buy a majority on every entry and every field. Read at call time so a test or
#: a caller can set it.
EXTRACTIONS = 3

#: A PDF text layer is only ever the verification haystack, never the extraction input, so it
#: is capped far above any real paper rather than at paper_reader's 120k default. Truncation
#: here would be silent and would read as fabrication: every assay evidenced past the cut would
#: fail check_quote_verbatim with its quote "missing" from a document that really contains it.
_PDF_TEXT_CAP = 2_000_000


class PaperNotFoundError(LookupError):
    """No paper on disk for the request -- neither JATS XML nor a PDF."""


class NothingToDoError(RuntimeError):
    """The step before this one has not run: no verification to correct, or no correction
    to promote. A 409 rather than a 404 -- the paper is fine, the sequence is wrong."""


def _display_path(path: Path) -> str:
    """Repo-relative when it is under the repo, absolute otherwise.

    Not `relative_to` alone: REGISTRY_ROOT is patchable (tests, and any deployment that
    moves the data directory), and a path outside the repo would raise rather than degrade.
    """
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def split_stem(stem: str) -> tuple[str, str] | None:
    """`34252919_SDY2189` or `SDY2189_34252919` -> ("34252919", "SDY2189").

    The halves are identified by which one starts with "SDY", not by position: the registry
    scheme is `<pmid>_<SDY>` and the XML scheme is `<SDY>_<pmid>`, and the two were named
    independently. Returns None when there is no second half -- the caller decides whether that
    is fatal, because a CLI wants to exit and a directory walk wants to skip.
    """
    if stem.lower().endswith(PDF_DIR_SUFFIX):
        stem = stem[: -len(PDF_DIR_SUFFIX)]
    left, _, right = stem.partition("_")
    if not right:
        return None
    return (right, left) if left.upper().startswith("SDY") else (left, right)


def locate_paper_xml(pubmed_id: str, study_accession: str) -> Path | None:
    """Find a paper's XML, trying both directory spellings.

    The registry directories are `<pmid>_<SDY>` and the XML files `<SDY>_<pmid>` -- the two
    schemes were named independently and disagree, so both orders are tried rather than one
    being assumed.
    """
    pmid, sdy = (pubmed_id or "").strip(), (study_accession or "").strip()
    stems = [s for s in (f"{sdy}_{pmid}", f"{pmid}_{sdy}") if s.strip("_")]
    for stem in stems:
        path = XML_ROOT / f"{stem}.xml"
        if path.exists():
            return path
    # Only one identifier given: match whichever half the caller supplied.
    known = pmid or sdy
    if known:
        for path in sorted(XML_ROOT.glob("*.xml")):
            if known in path.stem.split("_"):
                return path
    return None


def locate_paper_pdf(pubmed_id: str, study_accession: str) -> Path | None:
    """Find a paper's PDF under data/pdf/, searched recursively.

    Filenames follow `{study_accession}_{pubmed_id}.pdf` and sit in one of several
    subdirectories, one of which has a space in its name, so this walks rather than joining a
    path. The same convention and the same walk as orchestrator._find_local_pdf, duplicated
    rather than imported: that module pulls in SQLAlchemy, app.database and query_builder, and
    nothing else in this one needs them.
    """
    pmid, sdy = (pubmed_id or "").strip(), (study_accession or "").strip()
    if not pmid or not sdy or not PDF_ROOT.exists():
        return None
    target = f"{sdy}_{pmid}.pdf".lower()
    for candidate in sorted(PDF_ROOT.rglob("*.pdf")):
        if candidate.name.lower() == target:
            return candidate
    return None


#: Where a PDF the user uploaded is filed. Under PDF_ROOT, so locate_paper_pdf finds it unchanged.
UPLOAD_SUBDIR = "uploads"
#: A paper PDF is a few MB; this only stops a mistaken upload from filling the disk.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class UploadRejectedError(ValueError):
    """An uploaded file that must not be stored. `status` is the HTTP status the route returns."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def store_uploaded_pdf(pubmed_id: str, study_accession: str, data: bytes,
                       force: bool = False) -> tuple[Path, bool]:
    """File a user-uploaded PDF where the pipeline looks for one. Returns (path, created).

    For a paper PMC will not serve: once the PDF is at `data/pdf/uploads/<SDY>_<PMID>.pdf`,
    locate_paper_pdf finds it, registry_dir files the paper as `<pmid>_<SDY>_pdf`, and both the
    assay chain and the data-availability step read it -- nothing downstream needs to know it was
    uploaded. The identifiers must already be validated (jats_fetcher.validate_identifiers).

    Refused: bytes that are not a PDF, an oversized file, and a paper whose JATS XML is on disk
    (the XML always wins, so the upload would silently do nothing). A PDF already on disk is kept
    unless `force` -- then *that* file is replaced, since any other copy would shadow a new one.
    Written to a temp name and renamed, so a failed write leaves nothing half-written.
    """
    if not data.startswith(b"%PDF-"):
        raise UploadRejectedError("that file is not a PDF", 415)
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejectedError(
            f"the PDF is {len(data) // (1024 * 1024)} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB", 413)
    xml = locate_paper_xml(pubmed_id, study_accession)
    if xml is not None:
        raise UploadRejectedError(
            f"this paper's full text is already on disk as {xml.name}, which the pipeline reads "
            "in preference to any PDF", 409)

    existing = locate_paper_pdf(pubmed_id, study_accession)
    if existing is not None and not force:
        return existing, False
    target = existing or (PDF_ROOT / UPLOAD_SUBDIR / f"{study_accession}_{pubmed_id}.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(data)
    partial.replace(target)
    return target, True


def locate_paper_source(pubmed_id: str, study_accession: str) -> tuple[str, Path] | None:
    """The best source on disk for a paper: `("xml", path)`, `("pdf", path)`, or None.

    XML wins whenever it exists. It carries the section tags and sentence markers the PDF route
    has to do without, so a paper that has both is never routed through the lossier one.
    """
    xml_path = locate_paper_xml(pubmed_id, study_accession)
    if xml_path is not None:
        return ("xml", xml_path)
    pdf_path = locate_paper_pdf(pubmed_id, study_accession)
    if pdf_path is not None:
        return ("pdf", pdf_path)
    return None


def paper_source(kind: str, path: Path) -> tuple[str, str]:
    """(title, source text) for either kind of paper.

    For XML this is paper_source_text unchanged -- the sentence-numbered parse that rounds 1, 2
    and 3 all read. For a PDF the text is the PyMuPDF layer, and it is *only* the verification
    haystack: round 1 sends the PDF itself, because the layout is exactly what the text layer
    loses. There is no article title to parse without XML, so the filename stem stands in.
    """
    if kind == "xml":
        return paper_source_text(path)

    text = extract_pdf_text(path.read_bytes(), max_chars=_PDF_TEXT_CAP)
    if not text.strip():
        raise PaperNotFoundError(f"{path.name} yielded no text")
    if len(text) >= _PDF_TEXT_CAP:
        logger.warning(
            "%s hit the %d-char cap: quote checks past the cut will read as missing",
            path.name, _PDF_TEXT_CAP)
    return path.stem, text


def _not_found(pubmed_id: str, study_accession: str) -> PaperNotFoundError:
    """The one message for "this paper is not on disk", naming both places looked."""
    return PaperNotFoundError(
        f"No paper for pubmed_id={pubmed_id!r} study_accession={study_accession!r}: "
        f"no JATS XML under {XML_ROOT} and no PDF under {PDF_ROOT}")


def registry_dir(pubmed_id: str, study_accession: str) -> Path:
    """Where this paper's registry lives. One canonical location, per the skill.

    `<pmid>_<SDY>`, or `<pmid>_<SDY>_pdf` for a paper whose registry comes from its PDF -- one
    already built that way, or one with no JATS XML but a PDF on disk.

    A benchmark paper -- one whose folder already exists under REGISTRY_ROOT -- stays there.
    Any other paper lives under CACHE_ROOT, which is also where its data repositories go.
    """
    name = f"{(pubmed_id or '').strip()}_{(study_accession or '').strip()}"
    for root in (REGISTRY_ROOT, CACHE_ROOT):
        for existing in (root / (name + PDF_DIR_SUFFIX), root / name):
            if existing.is_dir():
                return existing
    plain = CACHE_ROOT / name
    if (locate_paper_xml(pubmed_id, study_accession) is None
            and locate_paper_pdf(pubmed_id, study_accession) is not None):
        return plain.with_name(name + PDF_DIR_SUFFIX)
    return plain


def is_cached(pubmed_id: str, study_accession: str) -> bool:
    """True for a paper outside the benchmark, whose results live under CACHE_ROOT."""
    return registry_dir(pubmed_id, study_accession).parent == CACHE_ROOT


def paper_source_text(xml_path: Path) -> tuple[str, str]:
    """(title, sentence-numbered text) — the same parse every assay pass reads from.

    Identical to what the CLI scripts produce, so an `[S<n>]` id means the same sentence
    whether an entry was built here or by scripts/run_assay_pipeline.py. Any other source of text
    would make the cited ids uncheckable.
    """
    raw = xml_path.read_bytes()
    parsed = parse_jats_xml(raw.decode("utf-8"), include_extended_data=True)
    if not parsed or not parsed.strip():
        raise PaperNotFoundError(f"{xml_path.name} yielded no text")
    return (article_title(raw) or xml_path.stem), number_sentences(parsed)


def quote_report(assays: dict, source_text: str) -> dict:
    """The free deterministic checks over a whole registry, as a serialisable summary.

    Two of them now: the quote is copied verbatim from the sentences it cites, and `source`
    agrees with the section those sentences sit in. Both are pure string work, so they run on
    every response, and neither depends on a model's opinion.
    """
    sections = sentence_sections(source_text)
    per_assay = {key: check_quote_verbatim(entry, source_text) for key, entry in assays.items()}
    per_source = {key: check_source_section(entry, sections) for key, entry in assays.items()}
    statuses = [c["status"] for c in per_assay.values()]
    source_statuses = [c["status"] for c in per_source.values()]
    return {
        "verified": statuses.count("found"),
        "missing": statuses.count("missing"),
        # Verbatim but cited wrongly, or too short to pin down: NOT_SUPPORTED, not fabricated.
        "misattributed": statuses.count("misattributed") + statuses.count("too_short"),
        "no_quote": statuses.count("no_quote"),
        "total": len(per_assay),
        "per_assay": per_assay,
        "source_aligned": source_statuses.count("aligned"),
        "source_mismatch": source_statuses.count("mismatch"),
        "source_unknown": source_statuses.count("unknown"),
        "per_assay_source": per_source,
    }


#: The `resource` values assay_obi_mapper reaches without paying -- one, now that the lexical
#: exact-match round is gone: its step 1 is a dict lookup. Everything else went through the
#: embedding round, which costs one embedding call plus one chat call whatever it concludes --
#: an entry the LLM declined lands on "unresolved" having spent exactly what a hit spent.
#: "exact_normalized" is deliberately absent: it can no longer be produced, and counting a
#: value from an older mapping as free here would under-report a re-run's bill.
#:
#: "exact_normalized_llm" *is* free and must be listed. It was the exact lookup on
#: technique (removed 2026-10-02, so only stored rows carry it), and it reached the same
#: `return` as exact_original without touching the network. Omitting it billed a 4-assay paper 8 calls for
#: a round that made none.
_OBI_FREE_RESOURCES = ("exact_original", "exact_normalized_llm")
#: Resources whose entry also paid assay_obi_mapper._fulllist_pick, one call on top of step 2.
_OBI_FULLLIST_BILLED = ("fulllist_llm", "unresolved")


def _obi_query(key: str, entry: dict) -> tuple[str, str]:
    """(paper name, standard_technique_name) exactly as enrich_assays_with_obi queries them.

    The first wording only -- a canonicalized entry carries a list, and the mapper looks up one
    name -- falling back to the registry key when the entry has no name at all.
    """
    names = paper_names(entry)
    return (names[0] if names else key).strip(), str(entry.get("standard_technique_name") or "").strip()


def obi_query_calls(key: str, entry: dict) -> int:
    """What step 2 of the mapper spends on this entry: 2 calls, or 3 with a second query.

    One embedding for the paper's name, one chat call to pick, and one more embedding when a
    `standard_technique_name` differs from the name (_embedding_llm_match retrieves on both and merges
    the pools). Counting a flat 2 under-billed every entry the extractor normalized.
    """
    original, normalized = _obi_query(key, entry)
    return 3 if normalized and original and normalized.lower() != original.lower() else 2


def obi_calls(obi: dict) -> int:
    """What the OBI round spent, counted back from the resources it returned.

    An over-count in two cases: when obi_assay_pruned_embeddings.json is absent,
    _embedding_llm_match bails before calling anything and every miss still reads
    "unresolved"; and an entry whose lookup raised ("error") is billed as though every call it
    would have made went through. Over-reporting a bill is the safer direction to be wrong in.

    An entry the step-2 picker answered "none" for, with no exact hit, paid one more call over
    the whole vocabulary: it ends "fulllist_llm" if that pick landed and "unresolved" if not.
    """
    return sum(obi_query_calls(key, entry) + (entry.get("resource") in _OBI_FULLLIST_BILLED)
               for key, entry in (obi or {}).items()
               if entry.get("resource") not in _OBI_FREE_RESOURCES)


def obi_summary(obi: dict) -> dict:
    """How the mapping went, in the shape the other rounds report: counts plus the names.

    `unresolved` carries the assay names rather than just a total because that is the part a
    human has to act on -- a name OBI has no term for is either a vocabulary gap or an
    extraction that named something too vaguely to map, and the two are told apart by reading
    the name.
    """
    entries = (obi or {}).values()
    resources: dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("resource"))
        resources[key] = resources.get(key, 0) + 1
    return {
        "mapped": sum(1 for entry in entries if entry.get("obi_id")),
        "total": len(obi or {}),
        "resources": resources,
        "unresolved": sorted(k for k, e in (obi or {}).items() if not e.get("obi_id")),
        # A subset of `unresolved`: the lookup raised rather than finding no term, so the name
        # is not evidence of a vocabulary gap and a re-run may well map it.
        "errors": {k: e.get("obi_error") or "lookup failed"
                   for k, e in (obi or {}).items() if e.get("resource") == "error"},
    }



def obi_misses(assays: dict) -> list[str]:
    """Which assays would fall through to the OBI mapper's paid step. No API call.

    Mirrors assay_obi_mapper.map_assay_to_obi: step 1 looks up the *first* wording and nothing
    else -- not the `standard_technique_name`, which since 2026-10-02 is a retrieval query only. It used to also count any later
    wording and the registry key as a free hit -- and after round 5 the key of every mapped entry
    is an OBI label, which the vocabulary always knows, so a finished paper estimated almost no
    OBI calls at all.

    An exact hit is free only on a term with no children in the index; one that has children is
    pinned into the paid step for the picker to refine ("exact_original_llm"), so it is a miss.
    """
    lookup = _build_lookup()
    children = _index_children()
    missed = []
    for key, entry in assays.items():
        original, _ = _obi_query(key, entry)
        hit = lookup.get(original.lower()) if original else None
        if not hit or children.get(hit["obi_id"] if isinstance(hit, dict) else hit):
            missed.append(key)
    return missed


def _recover_key_map(extracted: dict, canonical: dict) -> dict[str, str]:
    """Which canonical key each extracted entry landed under, for a run that stored no key_map.

    Registries canonicalized before assays_merges.json carried a `key_map` can still be joined:
    round 5 keeps every member's wording in the survivor's `name_in_paper`, so an extracted
    entry is found by its own first wording. An entry that matches nothing maps to itself.
    """
    by_name: dict[str, str] = {}
    for canon_key, entry in canonical.items():
        for name in paper_names(entry) or [canon_key]:
            by_name.setdefault(normalize_assay_name(name), canon_key)
    recovered = {}
    for key, entry in extracted.items():
        names = paper_names(entry) or [key]
        recovered[key] = by_name.get(normalize_assay_name(names[0]), key)
    return recovered


def stored_key_map(out_dir: Path, extracted: dict | None = None,
                   canonical: dict | None = None) -> dict[str, str]:
    """The extracted-key -> canonical-key map for a finished run: stored, else recovered."""
    merges = _read_json(out_dir / "assays_merges.json") or {}
    if isinstance(merges.get("key_map"), dict):
        return merges["key_map"]
    if extracted and canonical:
        return _recover_key_map(extracted, canonical)
    return {}


#: Why rounds 2 and 3 carry a "~", in one paragraph. Returned as data rather than printed so the
#: caller decides how to wrap it; scripts/run_assay_pipeline.py prints its own hard-wrapped
#: rendering of these same three sentences, because its column layout is a printer's concern.
ESTIMATE_CAVEAT = (
    "Rounds 2-4 are sized from the previous run's output, which this run re-extracts rather "
    "than reuses. The shape rarely moves; it is not guaranteed -- round 4 in particular "
    "depends on whether this run re-extracts the same assay names."
)


def _read_json(path: Path) -> dict | None:
    """The stored file, or None when it is absent or unreadable.

    Unreadable counts as absent on purpose: the estimate is a free courtesy and a half-written
    registry from an interrupted run must degrade to "cannot size this round" rather than take
    down the page that was about to offer to re-run it.
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def estimate_run(pubmed_id: str, study_accession: str) -> dict:
    """What the five-round chain would cost, as data. No API call, no printing.

    Every round runs on every request, so the only question is how many calls each will make. A
    stored registry and verification are read for their *shape* -- how many assays, how many
    flagged fields -- which makes rounds 2 and 3 exact in practice even though neither file will
    be reused. Where they are absent the round cannot be sized at all, and says so with
    `calls: None` rather than guessing: an invented number on a cost gate is worse than no
    number.

    `exact` is False exactly where the CLI prints "~": rounds 2-4, which all scale with what the
    extraction finds. Round 4's count is exact for the names the last run found -- the
    vocabulary is a file -- but this run re-extracts those names. `total_calls` is None unless
    every round is known, so a caller cannot accidentally present a partial sum as the bill.

    Raises PaperNotFoundError when neither an XML nor a PDF is on disk. The round sizes do not
    depend on which one it is -- the PDF rides along as a file part on round 1's single call
    rather than adding one -- so a PDF paper is estimated exactly as an XML paper is.
    """
    source = locate_paper_source(pubmed_id, study_accession)
    if source is None:
        raise _not_found(pubmed_id, study_accession)
    kind, paper_path = source

    out_dir = registry_dir(pubmed_id, study_accession)
    title, source_text = paper_source(kind, paper_path)

    # Each round is sized from the file that round actually read last time, because round 5
    # re-keys assays.json by OBI label and the earlier files keep the extractor's wording. Sizing
    # the verifier from the folded registry under-counted it; joining the verification to OBI
    # keys matched nothing and billed round 3 at zero; checking OBI keys against the OBI
    # vocabulary found every one of them free. A registry from before the snapshot existed has
    # only assays.json, which is then the best there is.
    assays = _read_json(out_dir / "assays.json")
    extracted = _read_json(out_dir / "assays_precorrection.json") or assays
    verification = _read_json(out_dir / "assays_verification.json")
    corrected = _read_json(out_dir / "assays_corrected.json")
    obi = _read_json(out_dir / "assays_OBI.json")

    kept = extracted
    if extracted is not None and verification is not None:
        kept, _ = drop_rejected(extracted, verification)
    mapped_input = corrected if corrected is not None else kept

    rounds: list[dict] = [
        {"round": 1, "name": "extract", "calls": EXTRACTIONS, "exact": True, "basis": "always",
         "extractions": EXTRACTIONS},
    ]

    if extracted is not None:
        rounds.append({"round": 2, "name": "verify", "calls": len(extracted), "exact": False,
                       "basis": "last_run", "assays": len(extracted)})
    else:
        rounds.append({"round": 2, "name": "verify", "calls": None, "exact": False,
                       "basis": "unknown", "assays": None})

    if verification is not None and extracted is not None:
        pending = corrections_available(kept, verification)
        rounds.append({"round": 3, "name": "correct", "calls": pending["calls"], "exact": False,
                       "basis": "last_run",
                       "rejected": len(extracted) - len(kept)})
    else:
        rounds.append({"round": 3, "name": "correct", "calls": None, "exact": False,
                       "basis": "unknown", "rejected": None})

    if mapped_input is not None:
        missed = obi_misses(mapped_input)
        rounds.append({"round": 4, "name": "obi",
                       "calls": sum(obi_query_calls(k, mapped_input[k]) for k in missed),
                       "exact": False, "basis": "last_run", "assays": len(mapped_input),
                       "free_matches": len(mapped_input) - len(missed), "misses": missed})
    else:
        rounds.append({"round": 4, "name": "obi", "calls": None, "exact": False,
                       "basis": "unknown", "assays": None, "free_matches": None, "misses": []})

    if mapped_input is not None:
        # The stored mapping is keyed canonically; the fold is computed on the pre-canonical
        # registry, so each entry is given the mapping of the key it landed under.
        keys = stored_key_map(out_dir, mapped_input, assays)
        obi_by_entry = ({k: obi[keys.get(k, k)] for k in mapped_input if keys.get(k, k) in obi}
                        if obi else None)
        groups = canonical_groups(mapped_input, obi_by_entry)
        folds = [{"key": g["key"], "members": g["members"]}
                 for g in groups if len(g["members"]) > 1]
        # Free: re-keying and folding call nothing. A BROAD mapping stays on its category term;
        # the re-pick that used to be billed here was removed 2026-10-30 (assay_obi_mapper's
        # module docstring has the measurement).
        rounds.append({"round": 5, "name": "canonicalize", "calls": 0, "exact": True,
                       "basis": "deterministic", "entries": len(mapped_input),
                       "groups": len(groups), "folds": folds})
    else:
        # Free whether or not it can be sized, so the call count is 0 rather than None: "we
        # cannot tell you what this costs" would be a lie about a round that costs nothing.
        rounds.append({"round": 5, "name": "canonicalize", "calls": 0, "exact": True,
                       "basis": "deterministic", "entries": None, "groups": None, "folds": []})

    known = all(r["calls"] is not None for r in rounds)
    return {
        "pubmed_id": pubmed_id,
        "study_accession": study_accession,
        "paper_source": paper_path.name,
        "paper_source_kind": kind,
        "paper_title": title,
        "source_chars": len(source_text),
        # Absolute: the CLI prints this path. The display form is what a browser should show.
        "registry_dir": str(out_dir),
        "registry_dir_display": _display_path(out_dir),
        "has_registry": extracted is not None,
        "has_verification": verification is not None,
        "has_obi": obi is not None,
        "rounds": rounds,
        "total_calls": sum(r["calls"] for r in rounds) if known else None,
        "total_calls_known": known,
        # Only meaningful once a stored run has sized rounds 2 and 3; there is no "~" to explain
        # on a paper that has never been run.
        "caveat": ESTIMATE_CAVEAT if extracted is not None else None,
    }


@lru_cache(maxsize=256)
def _cached_title(path: str, mtime: float, size: int) -> str | None:
    """The paper's title, re-read only when the file itself changes.

    available_papers() is a page-load endpoint and article_title parses the whole document, so
    thirty papers would be thirty lxml parses on every request. Keyed by mtime and size as well
    as path so a re-fetched XML is not served under its old title.
    """
    del mtime, size  # cache keys, not arguments
    try:
        return article_title(Path(path).read_bytes())
    except OSError:
        return None


#: The files a finished run leaves behind, and what each is for. Read together rather than one
#: at a time because a caller that has the registry but not the verification cannot tell an
#: unverified entry from a verified one -- which is the failure this whole chain exists to stop.
_STORED_FILES = {
    "benchmark": "assays_benchmark.json",
    "assays": "assays.json",
    "obi": "assays_OBI.json",
    "verification": "assays_verification.json",
    "corrections": "assays_corrections.json",
    "merges": "assays_merges.json",
    "rejected": "assays_rejected.json",
    "precorrection": "assays_precorrection.json",
    # Every model reply the run paid for, by round (assay_trace). The file to read when a
    # registry looks wrong, instead of paying to re-run it.
    "raw": assay_trace.RAW_FILE,
    # Entries found by fewer than a majority of the extraction calls: not delivered, not lost.
    "minority": "assays_minority.json",
}


def stored_registry(pubmed_id: str, study_accession: str) -> dict:
    """What a previous run left on disk, with the free checks recomputed. No API call.

    The counterpart to assay_report, which never serves a stored run: this one *only* serves
    stored runs, and spends nothing doing it. That division is the point -- a page can show
    what is already known without a page load costing money, and the button beside it stays the
    one thing that spends.

    `contract_warnings` and `quote_report` are recomputed rather than read back, for the reason
    this module's docstring gives: a registry that was fine when written can stop matching if
    the paper's XML is re-fetched, and a stored verdict would not know. When the XML is gone the
    registry is still served -- with `quote_check` null and `paper_source` null, because a check
    that could not run must not read as a check that passed.

    Raises NothingToDoError when the paper has no registry directory to read.
    """
    out_dir = registry_dir(pubmed_id, study_accession)
    assays = _read_json(out_dir / "assays.json")
    if assays is None:
        raise NothingToDoError(
            f"no assays.json in {_display_path(out_dir)}; nothing has been extracted for this "
            "paper yet"
        )

    stored = {name: _read_json(out_dir / filename) for name, filename in _STORED_FILES.items()}
    files = {name: _display_path(out_dir / filename)
             for name, filename in _STORED_FILES.items()
             if (out_dir / filename).exists()}

    source = locate_paper_source(pubmed_id, study_accession)
    title, quote_check = None, None
    if source is not None:
        kind, paper_path = source
        try:
            title, source_text = paper_source(kind, paper_path)
        except PaperNotFoundError:
            title = None
        else:
            quote_check = quote_report(assays, source_text)

    benchmark = out_dir / "assays_benchmark.json"
    return {
        "pubmed_id": pubmed_id,
        "study_accession": study_accession,
        "paper_title": title,
        "paper_source": source[1].name if source is not None else None,
        "paper_source_kind": source[0] if source is not None else None,
        # The deliverable first. Falls back to projecting the registry for a directory written
        # before assays_benchmark.json existed, rather than handing back nothing to read.
        "benchmark": stored["benchmark"] if stored["benchmark"] is not None
                     else trim_registry(assays),
        "assays": assays,
        "minority": stored["minority"] or {},
        "obi": stored["obi"],
        "verification": stored["verification"],
        "corrections": stored["corrections"],
        "merges": stored["merges"],
        "dropped": stored["rejected"] or {},
        # The same two concessions assay_report and the CLI make: a PDF registry has no sentence
        # ids by contract, and after round 5 a key is the entry's OBI label, which only the
        # stored mapping can confirm. Without either, every entry of a finished paper warned.
        "contract_warnings": contract_warnings(
            assays, expect_sentence_ids=not out_dir.name.endswith(PDF_DIR_SUFFIX),
            obi=stored["obi"]),
        # Rebuilt from the stored mapping rather than read from a round record, which a stored
        # registry does not keep. Without it a reader of a finished paper would never be told
        # which assays OBI has no term for -- a finding CLAUDE.md requires be reported, and one
        # that is invisible in the registry itself because an unmapped entry looks like any
        # other. `source` distinguishes "round 4 produced this" from "round 4 never ran", which
        # is also what says whether the keys are OBI labels or the paper's own wordings.
        "rounds": {"obi": ({"source": "mapped", **obi_summary(stored["obi"])}
                           if stored["obi"] is not None else {"source": "skipped"})},
        "quote_check": quote_check,
        "updated_at": (datetime.fromtimestamp(benchmark.stat().st_mtime, tz=timezone.utc)
                       .isoformat() if benchmark.exists() else None),
        "registry_dir_display": _display_path(out_dir),
        "files": files,
    }


def available_papers() -> list[dict]:
    """Every paper the assay pipeline can run on: one entry per JATS XML, plus each PDF that
    has no XML.

    Having a source on disk is the gate -- assay_report reads nothing else to find a paper --
    so a study with neither is not offered rather than offered and then failed at, and a study
    with only a PDF *is* offered rather than hidden despite being runnable. `paper_source_kind`
    says which route it will take. Each is paired with its registry directory, so a caller can
    tell a paper that has already been run from one that has not without opening anything
    heavier than the benchmark.

    Free: a directory walk, one cached title parse per paper, and one small JSON read per
    finished paper.
    """
    papers = []
    seen: set[tuple[str, str]] = set()

    def _add(path: Path, kind: str) -> None:
        split = split_stem(path.stem)
        if split is None:
            return
        pubmed_id, study_accession = split
        if (pubmed_id, study_accession) in seen:
            return
        seen.add((pubmed_id, study_accession))
        out_dir = registry_dir(pubmed_id, study_accession)
        benchmark = out_dir / "assays_benchmark.json"
        stat = path.stat()
        entry = {
            "pubmed_id": pubmed_id,
            "study_accession": study_accession,
            "paper_source": path.name,
            "paper_source_kind": kind,
            # Only XML carries an article title to parse; a PDF is listed under its stem.
            "paper_title": (_cached_title(str(path), stat.st_mtime, stat.st_size)
                            if kind == "xml" else path.stem),
            "has_registry": (out_dir / "assays.json").exists(),
            "assays": None,
            "updated_at": None,
        }
        stored = _read_json(benchmark)
        if stored is not None:
            entry["assays"] = len(stored)
            entry["updated_at"] = datetime.fromtimestamp(
                benchmark.stat().st_mtime, tz=timezone.utc).isoformat()
        papers.append(entry)

    for path in sorted(XML_ROOT.glob("*.xml")):
        _add(path, "xml")
    # PDF-only papers are offered too, on the same invariant read the other way: assay_report
    # can run them, so leaving them off the list would hide a paper that works. XML is walked
    # first, so a paper with both is listed once, as the XML it will actually be run from.
    if PDF_ROOT.exists():
        for path in sorted(PDF_ROOT.rglob("*.pdf")):
            _add(path, "pdf")
    return papers



async def assay_report(
    pubmed_id: str,
    study_accession: str,
    client: AsyncOpenAI,
    verify: bool = True,
    correct: bool = True,
    model: str = settings.OPENAI_MODEL,
    on_progress: Callable[[dict], None] | None = None,
    extractions: int | None = None,
) -> dict:
    """Answer "what assays did this paper use?" in five rounds, and return the accurate set.

    Round 1 extracts (prompts/extract_assays.txt, or prompts/extract_assays_pdf.txt for a
    paper that has only a PDF) `extractions` times -- EXTRACTIONS by default -- concurrently,
    and votes the replies into one registry (assay_consensus): an entry a minority of the calls
    found is written to assays_minority.json and reported, not delivered. Round 2 verifies each entry
    against the paper with a model that has none of the extraction's reasoning in view
    (prompts/verify_assays.txt, 1 call per assay). Round 3 repairs what round 2 refused to
    support (prompts/correct_assay_field.txt, 1 call per flagged FIELD) and sets aside assays
    whose identity it rejected. Round 4 maps the surviving assays onto OBI terms (free on an
    exact match, 2-3 calls otherwise). Round 5 re-keys the registry by OBI label and folds
    entries that share a term (free).

    **assays.json is written last.** Round 1 clears every file the previous run left and writes
    its extraction to assays_precorrection.json; only when round 5 is done is the corrected,
    canonical registry written to assays.json, with assays_OBI.json and assays_benchmark.json
    beside it. A run that dies part-way therefore leaves no assays.json at all rather than one
    that cannot be told apart from a verified registry.

    Every paper costs EXTRACTIONS + N + F + O calls, every time. Nothing is served from disk:
    asking twice pays twice, and the second answer is the one that reflects the current prompts.

    `on_progress` is fired at each round boundary, and once per assay during round 2, for a
    caller watching a run it did not block on. It is a listener, not a participant: it cannot
    change what the chain does, and an exception it raises is logged and swallowed, because a
    broken listener must never cost a paid run its remaining rounds. Rounds 3 and 4 report a
    total and then a result with nothing in between -- correct_registry gathers its field calls
    and the OBI mapper runs in a worker thread, so neither can be watched from here, and a
    caller must show that as indeterminate rather than invent a position.

    Raises PaperNotFoundError when neither an XML nor a PDF is on disk. An extraction call
    that fails (empty or unparseable reply, API error) is recorded under
    `rounds.extract.failed` and the vote proceeds on the calls that answered; the paper is lost
    to AssayExtractionError only when fewer than a majority of the extraction calls succeed --
    the vote needs that many, and with one call there is nothing to fall back on. Verification,
    correction and OBI-mapping failures never propagate, because each turns a failed call into
    a per-item ERROR record, or a failed round, rather than losing the paper.
    """
    def _emit(**event) -> None:
        if on_progress is None:
            return
        try:
            on_progress(event)
        except Exception:
            logger.exception("assay progress listener raised; the run continues")
    source = locate_paper_source(pubmed_id, study_accession)
    if source is None:
        raise _not_found(pubmed_id, study_accession)
    kind, paper_path = source

    title, source_text = paper_source(kind, paper_path)
    out_dir = registry_dir(pubmed_id, study_accession)
    # Every reply this run gets is kept beside the registry, written after each round so a run
    # that dies part-way keeps the rounds it paid for. Stopped in the finally below.
    trace = assay_trace.start()
    try:
        return await _run_rounds(pubmed_id, study_accession, client, verify, correct, model,
                                 _emit, kind, paper_path, title, source_text, out_dir, trace,
                                 extractions if extractions is not None else EXTRACTIONS)
    finally:
        assay_trace.stop()


async def _extraction_attempt(label: str, call) -> tuple[str, dict | None, str | None]:
    """(label, registry, None) when the call answered; (label, None, "Type: msg") when it failed.

    One failed extraction used to abort the paper: the N calls ran under a bare gather, so an
    empty or unparseable reply from one threw away the other N-1 paid replies. The vote needs
    only a majority, so a failure is a run that found nothing -- recorded, and voted around.
    The reply itself is already in the trace (assay_extractor records it before parsing).
    """
    try:
        return label, await call, None
    except Exception as exc:  # noqa: BLE001 - one bad reply must not cost the others
        logger.warning("extraction %s failed: %s: %s", label, type(exc).__name__, exc)
        return label, None, f"{type(exc).__name__}: {exc}"


async def _run_rounds(pubmed_id, study_accession, client, verify, correct, model, _emit,
                      kind, paper_path, title, source_text, out_dir, trace,
                      extractions: int) -> dict:
    """assay_report's five rounds, split out so the trace's start/stop wraps them."""
    registry_path = out_dir / "assays.json"
    minority_path = out_dir / "assays_minority.json"
    precorrection_path = out_dir / "assays_precorrection.json"
    verification_path = out_dir / "assays_verification.json"
    corrections_path = out_dir / "assays_corrections.json"
    corrected_path = out_dir / "assays_corrected.json"
    rejected_path = out_dir / "assays_rejected.json"
    obi_path = out_dir / "assays_OBI.json"
    merges_path = out_dir / "assays_merges.json"
    benchmark_path = out_dir / "assays_benchmark.json"
    raw_path = out_dir / assay_trace.RAW_FILE

    calls = 0
    rounds: dict = {}

    # ── Round 1: extract ──────────────────────────────────────────────────────
    # The only round that cares which kind of source this is. A PDF goes to the model whole --
    # `source_text` for that kind is just the text layer, kept back for the quote checks below,
    # because the layout it loses is exactly what the extraction needs to read sections from.
    n_extract = max(1, int(extractions))
    _emit(round="extract", state="running", total=n_extract)
    labels = [f"run{i + 1}" for i in range(n_extract)]
    # Concurrent: the calls are independent, so N of them take about as long as one. Each reply
    # is kept in the trace under its own label; the registry is their majority.
    if kind == "pdf":
        pdf_bytes = paper_path.read_bytes()
        attempts = [_extraction_attempt(label, extract_assays_from_pdf(
            pdf_bytes, paper_path.name, title, client, model, run_label=label))
            for label in labels]
    else:
        attempts = [_extraction_attempt(label, extract_assays(
            source_text, title, client, model, run_label=label)) for label in labels]
    outcomes = await asyncio.gather(*attempts)
    failed = {label: error for label, registry, error in outcomes if registry is None}
    # The same majority consensus() demands of an entry: below it the vote has nothing to
    # stand on, and with one call there is no vote at all. A failed run otherwise stays in its
    # slot as an empty registry, so run labels line up with the trace and an entry the other
    # runs agree on still clears "2 of 3".
    needed = n_extract // 2 + 1
    if n_extract - len(failed) < needed:
        raise AssayExtractionError(
            f"{len(failed)} of {n_extract} extraction call(s) failed: "
            + "; ".join(f"{label}: {error}" for label, error in failed.items()))
    runs = [registry if registry is not None else {} for _, registry, _ in outcomes]
    # Each run's quotes are located before the vote, so two runs that quoted the same sentence
    # under different names align through the sentence ids (assay_consensus.same_entry). The
    # vote used to run on registries whose ids clean_entry had just emptied, which left that
    # link dead. XML only: a PDF text layer has no markers to locate against.
    if kind == "xml":
        for registry in runs:
            derive_evidence_fields(registry, source_text)
    assays, minority = consensus(runs)

    # `source` and `evidence.sentence_ids` are not asked of the model; they are worked out here
    # from the voted quote, once more, before the registry is written or judged. Free, and
    # exact where the quote is: locate_sentence_ids finds the sentences it came from and the
    # section map says whether they are Methods. On a PDF there are no markers, so both stay
    # empty -- the same contract that route already had.
    derive_evidence_fields(assays, source_text)
    # The vote unions aliases across runs, so a wording one run invented reaches here. One the
    # paper does not contain is removed now, for free, rather than reaching round 2 as a
    # NOT_SUPPORTED position that forces REVIEW and buys a round-3 call to delete it.
    aliases_dropped = drop_absent_aliases(assays, source_text)

    # Every file the previous run left now describes a different extraction. They go before
    # anything of this run's is written -- assays.json and the deliverable included -- so a run
    # that fails or is cancelled part-way leaves no file that reads as its findings, and never an
    # assays.json that looks verified. The registry is only written once the chain is done; until
    # then this run's extraction lives in assays_precorrection.json, which is what it is.
    for stale in (registry_path, benchmark_path, verification_path, corrections_path,
                  corrected_path, rejected_path, obi_path, merges_path, raw_path,
                  minority_path):
        if stale.exists():
            stale.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    precorrection_path.write_text(json.dumps(assays, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
    if minority:
        minority_path.write_text(json.dumps(minority, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    trace.write(raw_path)
    calls += n_extract
    rounds["extract"] = {"source": "extracted", "calls": n_extract, "extractions": n_extract,
                         "assays": len(assays), "minority": len(minority)}
    if failed:
        # Paid for and answered with nothing usable: the vote went on without them, and a
        # reader should know the majority was taken over fewer replies than were made.
        rounds["extract"]["failed"] = failed
    if aliases_dropped:
        # Wordings the vote carried that the paper does not contain, removed before verification.
        rounds["extract"]["aliases_dropped"] = aliases_dropped
    # Says why an empty or thin extraction may be: with no Methods section (a short report whose
    # methods sit in a supplement) round 1 had only the main text to read. XML only -- a PDF's
    # text layer carries no section tags to tell.
    if kind == "xml" and not has_methods_section(source_text):
        rounds["extract"]["no_methods"] = True
    _emit(round="extract", state="done", calls=n_extract, assays=len(assays),
          minority=len(minority), failed=sorted(failed))

    # ── Round 2: verify ───────────────────────────────────────────────────────
    verification = None
    if not verify or not assays:
        rounds["verify"] = {"source": "skipped", "calls": 0}
        _emit(round="verify", state="skipped", calls=0)
    else:
        _emit(round="verify", state="running", done=0, total=len(assays))
        results = await verify_registry(
            assays, source_text, title, client, model,
            on_item=lambda done, total, result: _emit(
                round="verify", state="running", done=done, total=total,
                item=result.get("assay_id"), verdict=result.get("record_verdict")),
        )
        verification = build_report(results)
        verification_path.write_text(
            json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        trace.write(raw_path)
        # The one verdict no later round acts on. Marked on the entry here so it rides through
        # correction, the fold and into the deliverable rather than surviving only as a line
        # printed once.
        mark_identity_reviews(assays, verification)
        calls += len(assays)
        rounds["verify"] = {"source": "verified", "calls": len(assays)}
    if verification:
        rounds["verify"]["summary"] = verification.get("summary", {})
        _emit(round="verify", state="done", calls=len(assays),
              summary=verification.get("summary", {}))

    # ── Round 3: correct ──────────────────────────────────────────────────────
    dropped: dict = {}
    corrections: dict | None = None
    if not correct or not verification:
        rounds["correct"] = {"source": "skipped", "calls": 0}
        _emit(round="correct", state="skipped", calls=0)
    else:
        kept, dropped = drop_rejected(assays, verification)
        # The total up front, from the free preview, because correct_registry gathers its field
        # calls and reports nothing until all of them return. A known total with no position is
        # the honest shape; a position would have to be invented.
        _emit(round="correct", state="running",
              total=corrections_available(kept, verification)["calls"])
        corrected, records = await correct_registry(kept, verification, source_text, title,
                                                    client, model)
        # A replaced quote may sit in a different section from the one it replaced, and `source`
        # and `sentence_ids` are derived from the quote -- so they are derived again from the
        # corrected one. Without this, SDY1264 carried `source: methods` on four quotes the
        # repair had moved into the abstract, and the run's own quote_report flagged every one.
        derive_evidence_fields(corrected, source_text)
        report = build_correction_report(records)
        corrections = report
        spent = report["summary"]["fields_re_extracted"]

        corrected_path.write_text(
            json.dumps(corrected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        corrections_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        trace.write(raw_path)
        if dropped:
            rejected_path.write_text(
                json.dumps(dropped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        assays = corrected
        calls += spent
        rounds["correct"] = {"source": "corrected", "calls": spent,
                             "actions": report["summary"]["actions"],
                             "dropped": len(dropped)}
        _emit(round="correct", state="done", calls=spent, dropped=len(dropped),
              actions=report["summary"]["actions"])

    # ── Round 4: map to OBI ───────────────────────────────────────────────────
    # After correction, deliberately. The mapper's paid step reads sample_type and readouts as
    # disambiguating context (prompts/resolver_obi_assay.txt), and those are two of the fields
    # round 3 re-extracts -- so mapping the extracted registry would resolve assays against
    # values the verifier had already refused to support, and would pay to map assays that
    # drop_rejected then removes.
    #
    # Written to its own file, never back into assays.json: enrichment adds technique and
    # four obi_* keys, none of them in ENTRY_FIELDS, so a merged registry would trip
    # contract_warnings on the way out and lose them to trim_registry anyway.
    obi = None
    if not assays:
        rounds["obi"] = {"source": "skipped", "calls": 0}
        _emit(round="obi", state="skipped", calls=0)
    else:
        # No `done`: the mapper runs in a worker thread and reports nothing until it returns.
        _emit(round="obi", state="running", total=len(assays))
        try:
            # to_thread because enrich_assays_with_obi is synchronous and drives a blocking
            # OpenAI client; calling it inline would stall the event loop for the whole round.
            obi = await asyncio.to_thread(enrich_assays_with_obi, assays, model=model)
        except Exception:
            # Soft on purpose. The mapper already turns a failed lookup into an "error" entry,
            # so reaching here means the round could not run at all (a missing vocabulary file,
            # say). Rounds 1-3 have cost 1+N+F calls; raising would throw that away over an
            # ontology lookup. `run_assay_merge.py --map` finishes the job without re-paying.
            logger.exception("OBI mapping failed; rounds 1-3 output is intact at %s",
                             _display_path(out_dir))
            rounds["obi"] = {"source": "failed", "calls": 0}
            _emit(round="obi", state="failed", calls=0)
        else:
            trace.write(raw_path)
            spent_obi = obi_calls(obi)
            calls += spent_obi
            rounds["obi"] = {"source": "mapped", "calls": spent_obi, **obi_summary(obi)}
            _emit(round="obi", state="done", calls=spent_obi, **obi_summary(obi))

    # ── Round 5: canonicalize ─────────────────────────────────────────────────
    # The OBI term is the assay's identity, so the registry is keyed by the term's label and two
    # entries that mapped to one term are one assay. Extraction keys by the paper's wording and
    # cannot see that its two Methods subheadings describe one ELISA; round 4 can, because both
    # resolved to OBI:0000661. Free and deterministic -- no model decides any of it. An entry
    # OBI left unmapped keeps its own key and is reported UNMAPPED rather than folded onto a
    # sibling that merely shares its technique.
    #
    # Runs whether or not anything folds: re-keying is the point, and `name_in_paper` becomes a
    # list of every wording on every entry so no reader has to branch on whether a fold happened.
    # assays_merges.json is written every time for its key_map, which is the only join from the
    # verification and corrections (keyed by the extractor's wording) to the canonical registry.
    merges: dict | None = None
    if not assays or obi is None:
        # Without a mapping there is nothing to key on. Leaving the registry in its extracted
        # shape is the honest degradation: run_assay_merge.py --map finishes the job.
        rounds["canonicalize"] = {"source": "skipped", "calls": 0}
        _emit(round="canonicalize", state="skipped", calls=0)
    else:
        _emit(round="canonicalize", state="running", total=len(assays))
        groups = canonical_groups(assays, obi)
        # Free and deterministic. A BROAD mapping stays on its category term: the vocabulary
        # has nothing finer for the assays that land there (ICS, degranulation, PRNT), so the
        # re-pick that used to be billed here found nothing in 52 asks and was removed
        # 2026-10-30 -- see assay_obi_mapper's module docstring.
        keys = key_map(assays, obi)
        assays, obi, folds = canonicalize_registry(assays, obi)
        # The folds the rules refused are findings too: two entries on one term kept apart
        # because their technique, sample type or readouts differ.
        merges = build_merge_report(folds, keys, blocked_folds(groups))
        rounds["canonicalize"] = {"source": "canonical", "calls": 0,
                                  "assays": len(assays), **merges["summary"]}
        _emit(round="canonicalize", state="done", calls=0, assays=len(assays),
              **merges["summary"])
        merges_path.write_text(
            json.dumps(merges, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ── Promote ───────────────────────────────────────────────────────────────
    # Only now, with every round done, is assays.json written -- the corrected, canonical
    # registry -- and the OBI mapping and the deliverable beside it, keyed the same way. Nothing
    # else writes it: the step-wise scripts that promoted a corrected registry on their own,
    # skipping rounds 4 and 5, were removed 2026-10-30.
    if obi is not None:
        obi_path.write_text(json.dumps(obi, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    registry_path.write_text(json.dumps(assays, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    benchmark_path.write_text(
        json.dumps(trim_registry(assays), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # On the registry as delivered -- corrected, re-keyed, with the mapping that says which key
    # is an OBI label -- the same call the CLI makes. Taken after round 1, as it used to be, the
    # list named pre-correction gaps under keys round 5 had since replaced, and the web UI
    # rendered it as the run's findings.
    warnings = contract_warnings(assays, expect_sentence_ids=(kind == "xml"), obi=obi)

    return {
        "study_accession": study_accession,
        "pubmed_id": pubmed_id,
        "paper_title": title,
        "paper_source": paper_path.name,
        "paper_source_kind": kind,
        "assays": assays,
        "obi": obi,
        "quote_check": quote_report(assays, source_text),
        "verification": verification,
        # Returned, not just written to disk: a repair that failed is a finding a caller has to
        # be able to report, and the count inside rounds["correct"]["actions"] does not say
        # which assay or which field.
        "corrections": corrections,
        "dropped": dropped,
        # Entries a minority of the extraction calls found: not delivered, and a finding to
        # report for the same reason a dropped one is.
        "minority": minority,
        # Same reason as corrections: which entries were folded onto one OBI term, and so are
        # no longer keys of their own, is a finding a caller has to be able to report.
        "merges": merges,
        "rounds": rounds,
        "contract_warnings": warnings,
        "meta": {
            "llm_calls": calls,
            "registry_path": _display_path(registry_path),
            "benchmark_path": _display_path(benchmark_path),
            "obi_path": _display_path(obi_path) if obi is not None else None,
            "raw_path": _display_path(raw_path),
            "note": "assays.json holds the corrected registry; the extracted one is kept as "
                    "assays_precorrection.json; assays_benchmark.json is the reading view; "
                    "assays_OBI.json is the same registry with OBI terms attached; "
                    "assays_raw.json holds every model reply the run paid for",
        },
    }


def corrections_available(assays: dict, verification: dict | None) -> dict:
    """What a correction run would do, and what it would cost. No API call.

    Computed from the stored verification so a caller can render "2 fields can be
    re-extracted -- 2 calls" and offer a button, without a page load spending anything.
    `calls` counts flagged FIELDS, not assays, because that is what correct_registry bills.
    """
    if not verification:
        return {"fields": 0, "calls": 0, "rejected": 0, "per_assay": {}}

    by_id = {r.get("assay_id"): r for r in (verification.get("results") or [])}
    reasons = rejected_assays(verification)

    per_assay, fields = {}, 0
    for key in assays:
        result = by_id.get(key, {})
        groups = flagged_groups(result)
        fields += len(groups)
        per_assay[key] = {
            "record_verdict": result.get("record_verdict"),
            "fields": groups,
            "rejected": key in reasons,
            "rejected_reason": reasons.get(key),
            "reported_only": uncorrectable_flags(result),
        }
    return {"fields": fields, "calls": fields,
            "rejected": sum(1 for k in assays if k in reasons), "per_assay": per_assay}
