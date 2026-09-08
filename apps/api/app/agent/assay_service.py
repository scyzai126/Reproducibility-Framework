"""Answer "what assays did this paper use?" end to end: extract, verify, correct.

This is the pipeline behind POST /agent/assays. It chains the two prompts a front-end
question needs — prompts/extract_assays.txt to build the registry, prompts/verify_assays.txt
to judge it — with the free deterministic quote check in between.

**Results are cached on disk and reused by default.** A single request costs 1 + N calls (one
extraction, one verification per assay), which is real money to spend on a page load, and the
answer for a given paper does not change between requests. So an existing
`assays.json` / `assays_verification.json` under data/claims/assay_registries is served as-is
unless the caller passes `refresh`. Both files are the same ones the CLI scripts read and
write, so a registry built here is visible to run_assay_verify.py and vice versa.

The quote check runs on every response, cached or fresh. It costs nothing, it is the one
signal that does not depend on a model's opinion, and a registry that was fine when written
can stop matching if the paper's XML is re-fetched.
"""

import json
import logging
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
from app.agent.assay_extractor import contract_warnings, extract_assays, trim_registry
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
    every response, cached or fresh, and neither depends on a model's opinion.
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


async def assay_report(
    pubmed_id: str,
    study_accession: str,
    client: AsyncOpenAI,
    verify: bool = True,
    correct: bool = True,
    refresh: bool = False,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Answer "what assays did this paper use?" in three rounds, and return the accurate set.

    Round 1 extracts (prompts/extract_assays.txt, 1 call). Round 2 verifies each entry
    against the paper with a model that has none of the extraction's reasoning in view
    (prompts/verify_assays.txt, 1 call per assay). Round 3 repairs what round 2 refused to
    support (prompts/correct_assay_field.txt, 1 call per flagged FIELD) and sets aside assays
    whose identity it rejected.

    **Round 3 promotes.** The `assays` this returns are the corrected ones, and they are what
    assays.json now holds -- otherwise "the accurate assay" and the registry the resolver
    reads would disagree. The pre-correction registry is kept beside it as
    assays_precorrection.json, so an extracted value and a repaired one are still tellable
    apart; that distinction moves into the filename rather than being lost.

    A cold paper costs 1 + N + F calls. Every round caches to disk and is skipped on a repeat
    request, so asking twice costs nothing -- `assays_corrections.json` is the marker that
    round 3 already ran, written even when it repaired nothing.

    Raises PaperNotFoundError when no XML is on disk. Extraction failures propagate as
    AssayExtractionError; verification and correction failures do not, because both turn a
    failed call into a per-item ERROR record rather than losing the paper.
    """
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
    if registry_path.exists() and not refresh:
        assays = json.loads(registry_path.read_text(encoding="utf-8"))
        rounds["extract"] = {"source": "cache", "calls": 0}
    else:
        assays = await extract_assays(source_text, title, client, model)
        out_dir.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(assays, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        calls += 1
        rounds["extract"] = {"source": "extracted", "calls": 1}
    rounds["extract"]["assays"] = len(assays)

    warnings = contract_warnings(assays)
    for warning in warnings:
        logger.warning("assay extraction: %s", warning)

    fresh_registry = rounds["extract"]["source"] != "cache"

    # ── Round 2: verify ───────────────────────────────────────────────────────
    verification = None
    if not verify or not assays:
        rounds["verify"] = {"source": "skipped", "calls": 0}
    elif verification_path.exists() and not refresh and not fresh_registry:
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        rounds["verify"] = {"source": "cache", "calls": 0}
    else:
        # A fresh registry invalidates any stored report: it judged different entries.
        results = await verify_registry(assays, source_text, title, client, model)
        verification = build_report(results)
        verification_path.write_text(
            json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        calls += len(assays)
        rounds["verify"] = {"source": "verified", "calls": len(assays)}
    if verification:
        rounds["verify"]["summary"] = verification.get("summary", {})

    fresh_verification = rounds["verify"]["source"] == "verified"

    # ── Round 3: correct, then promote ────────────────────────────────────────
    dropped: dict = {}
    if not correct or not verification:
        rounds["correct"] = {"source": "skipped", "calls": 0}
    elif corrections_path.exists() and not refresh and not fresh_verification:
        report = json.loads(corrections_path.read_text(encoding="utf-8"))
        rejected_path = out_dir / "assays_rejected.json"
        if rejected_path.exists():
            dropped = json.loads(rejected_path.read_text(encoding="utf-8"))
        # Promotion is idempotent, and running it here holds the invariant this endpoint
        # promises: what we return IS assays.json. A registry corrected through the CLI and
        # never promoted would otherwise come back uncorrected -- measured on SDY1119, whose
        # assays.json still carried an alias its own correction had dropped.
        corrected_path = out_dir / "assays_corrected.json"
        if corrected_path.exists():
            promote_registry(out_dir)
            assays = json.loads(corrected_path.read_text(encoding="utf-8"))
        rounds["correct"] = {"source": "cache", "calls": 0,
                             "actions": report.get("summary", {}).get("actions", {})}
    else:
        kept, dropped = drop_rejected(assays, verification)
        corrected, records = await correct_registry(kept, verification, source_text, title,
                                                    client, model)
        report = build_correction_report(records)
        spent = report["summary"]["fields_re_extracted"]

        (out_dir / "assays_corrected.json").write_text(
            json.dumps(corrected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Written even when nothing was repaired: this file is the marker that round 3 ran,
        # and without it every later request would pay for round 3 again.
        corrections_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if dropped:
            (out_dir / "assays_rejected.json").write_text(
                json.dumps(dropped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        promote_registry(out_dir)
        assays = corrected
        calls += spent
        rounds["correct"] = {"source": "corrected", "calls": spent,
                             "actions": report["summary"]["actions"],
                             "dropped": len(dropped)}

    # The deliverable, written from the final registry on every request -- cache hits too, so
    # it can never lag assays.json. Deliberately not inside promote_registry(): that would make
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
        "quote_check": quote_report(assays, source_text),
        "verification": verification,
        "dropped": dropped,
        "rounds": rounds,
        "contract_warnings": warnings,
        "meta": {
            "llm_calls": calls,
            "registry_path": _display_path(registry_path),
            "benchmark_path": _display_path(benchmark_path),
            "note": "assays.json holds the corrected registry; the extracted one is kept as "
                    "assays_precorrection.json; assays_benchmark.json is the reading view",
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
