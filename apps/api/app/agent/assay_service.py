"""Answer "what assays did this paper use?" end to end: extract, verify, correct, map to OBI.

This is the pipeline behind POST /agent/assays. It chains the two prompts a front-end
question needs — prompts/extract_assays.txt to build the registry, prompts/verify_assays.txt
to judge it — with the free deterministic quote check in between, and finishes by resolving
the corrected registry against the OBI vocabulary in data/OBI.

**Every request runs all four rounds.** Results are written to disk under
data/claims/assay_registries, and the files are the same ones the CLI scripts read and write,
so a registry built here is visible to run_assay_verify.py and vice versa — but a stored one
is never served back. A request costs 1 + N + F calls every time.

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

from app.agent.assay_corrector import (
    build_report as build_correction_report,
    correct_registry,
    drop_rejected,
    flagged_groups,
    promote_registry,
    rejected_assays,
    uncorrectable_flags,
)
from app.agent.assay_extractor import (
    contract_warnings,
    extract_assays,
    paper_names,
    trim_registry,
)
from app.agent.assay_merger import build_merge_report, canonical_groups, canonicalize_registry
from app.agent.assay_obi_mapper import _build_lookup, enrich_assays_with_obi
from app.agent.assay_verifier import (
    build_report,
    check_quote_verbatim,
    check_source_section,
    verify_registry,
)
from app.agent.jats_parser import (
    article_title,
    number_sentences,
    parse_jats_xml,
    sentence_sections,
)
from app.config import settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
XML_ROOT = _REPO_ROOT / "data" / "JAT_XML"
REGISTRY_ROOT = _REPO_ROOT / "data" / "claims" / "assay_registries"


class PaperNotFoundError(LookupError):
    """No JATS XML on disk for the requested paper."""


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
    left, _, right = stem.partition("_")
    if not right:
        return None
    return (right, left) if left.upper().startswith("SDY") else (left, right)


def locate_paper_xml(pubmed_id: str, study_accession: str) -> Path | None:
    """Find a paper's XML, trying both directory spellings.

    The registry directories are `<pmid>_<SDY>` and the XML files `<SDY>_<pmid>` -- the two
    schemes were named independently and disagree, so both orders are tried rather than one
    being assumed. Mirrors run_assay_verify.locate_xml.
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


def registry_dir(pubmed_id: str, study_accession: str) -> Path:
    """Where this paper's registry lives. One canonical location, per the skill."""
    return REGISTRY_ROOT / f"{(pubmed_id or '').strip()}_{(study_accession or '').strip()}"


def paper_source_text(xml_path: Path) -> tuple[str, str]:
    """(title, sentence-numbered text) — the same parse every assay pass reads from.

    Identical to what the CLI scripts produce, so an `[S<n>]` id means the same sentence
    whether an entry was built here or by run_assay_extract.py. Any other source of text
    would make the cited ids uncheckable.
    """
    raw = xml_path.read_bytes()
    parsed = parse_jats_xml(raw.decode("utf-8"))
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
#: "exact_normalized_llm" *is* free and must be listed. It is step 1b -- a dict lookup on the
#: normalized_name the extractor already wrote -- and it reaches the same `return` as
#: exact_original without touching the network. Omitting it billed a 4-assay paper 8 calls for
#: a round that made none.
_OBI_FREE_RESOURCES = ("exact_original", "exact_normalized_llm")


def obi_calls(obi: dict) -> int:
    """What the OBI round spent, counted back from the resources it returned.

    An over-count in one case: when obi_generic_embeddings.json is absent,
    _embedding_llm_match bails before calling anything and every miss still reads
    "unresolved". Over-reporting a bill is the safer direction to be wrong in, and the
    alternative -- having the mapper report its own calls -- is a change to a module this
    round is meant to leave alone.
    """
    return 2 * sum(1 for entry in (obi or {}).values()
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
    }



def obi_misses(assays: dict) -> list[str]:
    """Which assays would fall through to the OBI mapper's paid step. No API call.

    Mirrors assay_obi_mapper's step 1 -- both halves of it. `normalized_name` is an exact-match
    key in its own right (step 1b), and omitting it here would bill the 40-odd entries per 171
    that only it resolves, overstating the round by roughly the 23-point hit-rate gain it buys.
    Anything neither key carries verbatim is paid. The registry key is tried alongside
    name_in_paper because contract_warnings only reports a registry where the two disagree; it
    does not repair one.

    Unlike rounds 2 and 3 this is not sized from the previous run -- the vocabulary is a file on
    disk and the names are already known, so the count is exact for any registry whose assay
    names this run reproduces.
    """
    lookup = _build_lookup()
    missed = []
    for key, entry in assays.items():
        # Every wording, because a canonicalized entry carries a list and the vocabulary may
        # know any one of them verbatim -- and its key is an OBI label, which it always knows.
        candidates = {n.strip().lower() for n in paper_names(entry)} | {key.strip().lower()}
        # Not a paper name -- the extractor's technique judgement, which step 1b looks up too.
        candidates.add(str(entry.get("normalized_name") or "").strip().lower())
        if not any(lookup.get(c) for c in candidates if c):
            missed.append(key)
    return missed


#: Why rounds 2 and 3 carry a "~", in one paragraph. Returned as data rather than printed so the
#: caller decides how to wrap it; scripts/run_assay_pipeline.py prints its own hard-wrapped
#: rendering of these same three sentences, because its column layout is a printer's concern.
ESTIMATE_CAVEAT = (
    "Rounds 2 and 3 are sized from the previous run's output, which this run re-extracts rather "
    "than reuses. The shape rarely moves; it is not guaranteed. Round 4 carries no ~: its "
    "vocabulary is on disk, so the only uncertainty is whether this run re-extracts the same "
    "assay names."
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

    `exact` is False exactly where the CLI prints "~". Rounds 4 and 5 are exact whenever a
    registry exists, because the vocabulary and the collision check are a file and some code,
    not a model's answer. `total_calls` is None unless every round is known, so a caller cannot
    accidentally present a partial sum as the bill.

    Raises PaperNotFoundError when no XML is on disk.
    """
    xml_path = locate_paper_xml(pubmed_id, study_accession)
    if xml_path is None:
        raise PaperNotFoundError(
            f"No JATS XML for pubmed_id={pubmed_id!r} study_accession={study_accession!r}")

    out_dir = registry_dir(pubmed_id, study_accession)
    title, source_text = paper_source_text(xml_path)

    assays = _read_json(out_dir / "assays.json")
    verification = _read_json(out_dir / "assays_verification.json")
    obi = _read_json(out_dir / "assays_OBI.json")

    rounds: list[dict] = [
        {"round": 1, "name": "extract", "calls": 1, "exact": True, "basis": "always"},
    ]

    if assays is not None:
        rounds.append({"round": 2, "name": "verify", "calls": len(assays), "exact": False,
                       "basis": "last_run", "assays": len(assays)})
    else:
        rounds.append({"round": 2, "name": "verify", "calls": None, "exact": False,
                       "basis": "unknown", "assays": None})

    if verification is not None:
        pending = corrections_available(assays or {}, verification)
        rounds.append({"round": 3, "name": "correct", "calls": pending["calls"], "exact": False,
                       "basis": "last_run", "rejected": pending["rejected"]})
    else:
        rounds.append({"round": 3, "name": "correct", "calls": None, "exact": False,
                       "basis": "unknown", "rejected": None})

    if assays is not None:
        missed = obi_misses(assays)
        rounds.append({"round": 4, "name": "obi", "calls": 2 * len(missed), "exact": True,
                       "basis": "vocabulary", "assays": len(assays),
                       "free_matches": len(assays) - len(missed), "misses": missed})
    else:
        rounds.append({"round": 4, "name": "obi", "calls": None, "exact": False,
                       "basis": "unknown", "assays": None, "free_matches": None, "misses": []})

    if assays is not None:
        groups = canonical_groups(assays, obi)
        folds = [{"key": g["key"], "members": g["members"]}
                 for g in groups if len(g["members"]) > 1]
        rounds.append({"round": 5, "name": "canonicalize", "calls": 0, "exact": True,
                       "basis": "deterministic", "entries": len(assays),
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
        "paper_source": xml_path.name,
        "paper_title": title,
        "source_chars": len(source_text),
        # Absolute: the CLI prints this path. The display form is what a browser should show.
        "registry_dir": str(out_dir),
        "registry_dir_display": _display_path(out_dir),
        "has_registry": assays is not None,
        "has_verification": verification is not None,
        "has_obi": obi is not None,
        "rounds": rounds,
        "total_calls": sum(r["calls"] for r in rounds) if known else None,
        "total_calls_known": known,
        # Only meaningful once a stored run has sized rounds 2 and 3; there is no "~" to explain
        # on a paper that has never been run.
        "caveat": ESTIMATE_CAVEAT if assays is not None else None,
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

    xml_path = locate_paper_xml(pubmed_id, study_accession)
    title, quote_check = None, None
    if xml_path is not None:
        try:
            title, source_text = paper_source_text(xml_path)
        except PaperNotFoundError:
            title = None
        else:
            quote_check = quote_report(assays, source_text)

    benchmark = out_dir / "assays_benchmark.json"
    return {
        "pubmed_id": pubmed_id,
        "study_accession": study_accession,
        "paper_title": title,
        "paper_source": xml_path.name if xml_path is not None else None,
        # The deliverable first. Falls back to projecting the registry for a directory written
        # before assays_benchmark.json existed, rather than handing back nothing to read.
        "benchmark": stored["benchmark"] if stored["benchmark"] is not None
                     else trim_registry(assays),
        "assays": assays,
        "obi": stored["obi"],
        "verification": stored["verification"],
        "corrections": stored["corrections"],
        "merges": stored["merges"],
        "dropped": stored["rejected"] or {},
        "contract_warnings": contract_warnings(assays),
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
    """Every paper the assay pipeline can run on: one entry per JATS XML on disk.

    The XML is the gate -- assay_report reads nothing else to find a paper -- so a study without
    one is not offered rather than offered and then failed at. Each is paired with its registry
    directory, so a caller can tell a paper that has already been run from one that has not
    without opening anything heavier than the benchmark.

    Free: a directory walk, one cached title parse per paper, and one small JSON read per
    finished paper.
    """
    papers = []
    for path in sorted(XML_ROOT.glob("*.xml")):
        split = split_stem(path.stem)
        if split is None:
            continue
        pubmed_id, study_accession = split
        out_dir = registry_dir(pubmed_id, study_accession)
        benchmark = out_dir / "assays_benchmark.json"
        stat = path.stat()
        entry = {
            "pubmed_id": pubmed_id,
            "study_accession": study_accession,
            "paper_source": path.name,
            "paper_title": _cached_title(str(path), stat.st_mtime, stat.st_size),
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
    return papers



async def assay_report(
    pubmed_id: str,
    study_accession: str,
    client: AsyncOpenAI,
    verify: bool = True,
    correct: bool = True,
    model: str = settings.OPENAI_MODEL,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Answer "what assays did this paper use?" in four rounds, and return the accurate set.

    Round 1 extracts (prompts/extract_assays.txt, 1 call). Round 2 verifies each entry
    against the paper with a model that has none of the extraction's reasoning in view
    (prompts/verify_assays.txt, 1 call per assay). Round 3 repairs what round 2 refused to
    support (prompts/correct_assay_field.txt, 1 call per flagged FIELD) and sets aside assays
    whose identity it rejected. Round 4 maps the surviving assays onto OBI terms, into
    assays_OBI.json.

    **Round 4 runs last for a reason**, not merely for convenience: it reads the corrected
    registry. See the comment at the round itself.

    **Round 3 promotes.** The `assays` this returns are the corrected ones, and they are what
    assays.json now holds -- otherwise "the accurate assay" and the registry the resolver
    reads would disagree. The pre-correction registry is kept beside it as
    assays_precorrection.json, so an extracted value and a repaired one are still tellable
    apart; that distinction moves into the filename rather than being lost.

    Every paper costs 1 + N + F calls, every time. Nothing is served from disk: asking twice
    pays twice, and the second answer is the one that reflects the current prompts.

    `on_progress` is fired at each round boundary, and once per assay during round 2, for a
    caller watching a run it did not block on. It is a listener, not a participant: it cannot
    change what the chain does, and an exception it raises is logged and swallowed, because a
    broken listener must never cost a paid run its remaining rounds. Rounds 3 and 4 report a
    total and then a result with nothing in between -- correct_registry gathers its field calls
    and the OBI mapper runs in a worker thread, so neither can be watched from here, and a
    caller must show that as indeterminate rather than invent a position.

    Raises PaperNotFoundError when no XML is on disk. Extraction failures propagate as
    AssayExtractionError; verification, correction and OBI-mapping failures do not, because
    each turns a failed call into a per-item ERROR record, or a failed round, rather than
    losing the paper.
    """
    def _emit(**event) -> None:
        if on_progress is None:
            return
        try:
            on_progress(event)
        except Exception:
            logger.exception("assay progress listener raised; the run continues")
    xml_path = locate_paper_xml(pubmed_id, study_accession)
    if xml_path is None:
        raise PaperNotFoundError(
            f"No JATS XML for pubmed_id={pubmed_id!r} study_accession={study_accession!r} "
            f"under {XML_ROOT}"
        )

    title, source_text = paper_source_text(xml_path)
    out_dir = registry_dir(pubmed_id, study_accession)
    registry_path = out_dir / "assays.json"
    verification_path = out_dir / "assays_verification.json"
    corrections_path = out_dir / "assays_corrections.json"

    calls = 0
    rounds: dict = {}

    # ── Round 1: extract ──────────────────────────────────────────────────────
    _emit(round="extract", state="running")
    assays = await extract_assays(source_text, title, client, model)
    out_dir.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(assays, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    calls += 1
    rounds["extract"] = {"source": "extracted", "calls": 1, "assays": len(assays)}
    _emit(round="extract", state="done", calls=1, assays=len(assays))
    extracted = assays

    warnings = contract_warnings(assays)
    for warning in warnings:
        logger.warning("assay extraction: %s", warning)

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
        calls += len(assays)
        rounds["verify"] = {"source": "verified", "calls": len(assays)}
    if verification:
        rounds["verify"]["summary"] = verification.get("summary", {})
        _emit(round="verify", state="done", calls=len(assays),
              summary=verification.get("summary", {}))

    # ── Round 3: correct, then promote ────────────────────────────────────────
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
        report = build_correction_report(records)
        corrections = report
        spent = report["summary"]["fields_re_extracted"]

        (out_dir / "assays_corrected.json").write_text(
            json.dumps(corrected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        corrections_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Removed rather than left behind when this run rejected nothing: a stale file from an
        # earlier run would read as this run's findings. Same reason the snapshot below is
        # rewritten -- every one of these files now describes one specific run.
        rejected_path = out_dir / "assays_rejected.json"
        if dropped:
            rejected_path.write_text(
                json.dumps(dropped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        elif rejected_path.exists():
            rejected_path.unlink()

        # This run's extraction is what "pre-correction" means. promote_registry writes the
        # snapshot only when absent, which was right while a finished paper was served from
        # cache -- the first extraction really was the only unrepaired version there would
        # ever be. Now that every run re-extracts, that guard would pin the snapshot to
        # whichever run happened to be first, so it is written here instead.
        (out_dir / "assays_precorrection.json").write_text(
            json.dumps(extracted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        promote_registry(out_dir)
        assays = corrected
        calls += spent
        rounds["correct"] = {"source": "corrected", "calls": spent,
                             "actions": report["summary"]["actions"],
                             "dropped": len(dropped)}
        _emit(round="correct", state="done", calls=spent, dropped=len(dropped),
              actions=report["summary"]["actions"])

    # ── Round 4: map to OBI ───────────────────────────────────────────────────
    # After promotion, deliberately. The mapper's paid step reads sample_type and readouts as
    # disambiguating context (prompts/resolver_obi_assay.txt), and those are two of the fields
    # round 3 re-extracts -- so mapping the extracted registry would resolve assays against
    # values the verifier had already refused to support, and would pay to map assays that
    # drop_rejected then removes. The free exact-match steps are name-only, and name_in_paper is
    # never corrected, so those land the same either way: it is only the expensive path that
    # moves. Same argument this module's docstring makes for not reusing round 1 on its own.
    #
    # Written to its own file, never back into assays.json: enrichment adds normalized_name and
    # four obi_* keys, none of them in ENTRY_FIELDS, so a merged registry would trip
    # contract_warnings on the way out and lose them to trim_registry anyway.
    obi_path = out_dir / "assays_OBI.json"
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
            obi = await asyncio.to_thread(enrich_assays_with_obi, assays)
        except Exception:
            # Soft on purpose, and this round is the only one that can afford to be: rounds 1-3
            # have already cost 1+N+F calls and every one of their files is on disk by now, so
            # raising here would throw away a paid run over an ontology lookup. Nothing later
            # depends on the mapping, and its input is the promoted registry -- so
            # scripts/run_obi_map.py can finish the job without re-paying for the earlier rounds.
            logger.exception("OBI mapping failed; rounds 1-3 output is intact at %s",
                             _display_path(out_dir))
            rounds["obi"] = {"source": "failed", "calls": 0}
            _emit(round="obi", state="failed", calls=0)
        else:
            obi_path.write_text(json.dumps(obi, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
            spent_obi = obi_calls(obi)
            calls += spent_obi
            rounds["obi"] = {"source": "mapped", "calls": spent_obi, **obi_summary(obi)}
            _emit(round="obi", state="done", calls=spent_obi, **obi_summary(obi))

    # ── Round 5: canonicalize ─────────────────────────────────────────────────
    # The OBI term is the assay's identity, so the registry is keyed by the term's label and two
    # entries that mapped to one term are one assay. Extraction keys by the paper's wording and
    # cannot see that its two Methods subheadings describe one ELISA; round 4 can, because both
    # resolved to OBI:0000661. Free and deterministic -- no model decides any of it.
    #
    # Runs whether or not anything folds: re-keying is the point, and `name_in_paper` becomes a
    # list of every wording on every entry so no reader has to branch on whether a fold happened.
    merges: dict | None = None
    merges_path = out_dir / "assays_merges.json"
    if not assays or obi is None:
        # Without a mapping there is nothing to key on. Leaving the registry in its extracted
        # shape is the honest degradation: run_assay_merge.py finishes the job once OBI has.
        rounds["canonicalize"] = {"source": "skipped", "calls": 0}
        _emit(round="canonicalize", state="skipped", calls=0)
    else:
        _emit(round="canonicalize", state="running", total=len(assays))
        assays, obi, folds = canonicalize_registry(assays, obi)
        merges = build_merge_report(folds)
        rounds["canonicalize"] = {"source": "canonical", "calls": 0,
                                  "assays": len(assays), **merges["summary"]}
        _emit(round="canonicalize", state="done", calls=0, assays=len(assays),
              **merges["summary"])
        registry_path.write_text(
            json.dumps(assays, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Rewritten rather than left as round 4 wrote it: the two files are looked up across each
        # other by key, and a mapping still keyed by a wording no longer in the registry reads as
        # an assay this paper never reported.
        obi_path.write_text(
            json.dumps(obi, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if folds:
            merges_path.write_text(
                json.dumps(merges, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Removed when this run folded nothing: a stale file from an earlier run would read as this
    # run's findings, the same reason assays_rejected.json is unlinked above.
    if not (merges or {}).get("results") and merges_path.exists():
        merges_path.unlink()

    # The deliverable, written from the final registry on every request, so it can never
    # lag assays.json. Deliberately not inside promote_registry(): that would make
    # assay_corrector import assay_extractor, and it would skip the rounds that never promote.
    # The consequence is that `run_assay_correct.py --promote` alone does not refresh this file.
    benchmark_path = out_dir / "assays_benchmark.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(
        json.dumps(trim_registry(assays), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "study_accession": study_accession,
        "pubmed_id": pubmed_id,
        "paper_title": title,
        "paper_source": xml_path.name,
        "assays": assays,
        "obi": obi,
        "quote_check": quote_report(assays, source_text),
        "verification": verification,
        # Returned, not just written to disk: a repair that failed is a finding a caller has to
        # be able to report, and the count inside rounds["correct"]["actions"] does not say
        # which assay or which field.
        "corrections": corrections,
        "dropped": dropped,
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
            "note": "assays.json holds the corrected registry; the extracted one is kept as "
                    "assays_precorrection.json; assays_benchmark.json is the reading view; "
                    "assays_OBI.json is the same registry with OBI terms attached",
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


async def correct_report(
    pubmed_id: str,
    study_accession: str,
    client: AsyncOpenAI,
    drop_rejected_entries: bool = True,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Repair the fields a verification flagged, and set aside the assays it rejected.

    Costs one call per flagged field. Writes assays_corrected.json, assays_corrections.json
    and (when anything was rejected) assays_rejected.json. **Nothing downstream reads those**
    -- promote() is a separate deliberate step, so a corrected value reaches the resolver
    because someone reviewed it rather than because a request ran.
    """
    xml_path = locate_paper_xml(pubmed_id, study_accession)
    if xml_path is None:
        raise PaperNotFoundError(f"No JATS XML for {pubmed_id!r}/{study_accession!r}")

    out_dir = registry_dir(pubmed_id, study_accession)
    registry_path = out_dir / "assays.json"
    verification_path = out_dir / "assays_verification.json"
    if not registry_path.exists():
        raise NothingToDoError(f"no assays.json in {_display_path(out_dir)}; extract first")
    if not verification_path.exists():
        raise NothingToDoError(
            f"no assays_verification.json in {_display_path(out_dir)}; verify first -- "
            "correction acts on verdicts and has nothing to act on without them"
        )

    assays = json.loads(registry_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    title, source_text = paper_source_text(xml_path)

    kept, dropped = (drop_rejected(assays, verification) if drop_rejected_entries
                     else (assays, {}))

    corrected, records = await correct_registry(kept, verification, source_text, title,
                                                client, model)
    report = build_correction_report(records)

    (out_dir / "assays_corrected.json").write_text(
        json.dumps(corrected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "assays_corrections.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if dropped:
        (out_dir / "assays_rejected.json").write_text(
            json.dumps(dropped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "study_accession": study_accession,
        "pubmed_id": pubmed_id,
        "corrected": corrected,
        "corrections": report,
        "dropped": dropped,
        "meta": {
            "llm_calls": report["summary"]["fields_re_extracted"],
            "dropped_count": len(dropped),
            "promoted": False,
            "registry_path": _display_path(registry_path),
        },
    }


def promote(pubmed_id: str, study_accession: str) -> dict:
    """Install the corrected registry as the one the pipeline reads. Free, no API call."""
    out_dir = registry_dir(pubmed_id, study_accession)
    try:
        result = promote_registry(out_dir)
    except FileNotFoundError as exc:
        raise NothingToDoError(f"{exc}; run the correction first") from exc

    return {
        "study_accession": study_accession,
        "pubmed_id": pubmed_id,
        "assays": json.loads((out_dir / "assays.json").read_text(encoding="utf-8")),
        "meta": {**result, "registry_path": _display_path(out_dir / "assays.json"),
                 "note": "assays_verification.json still describes the pre-correction "
                         "registry; re-verify to judge the promoted values"},
    }
