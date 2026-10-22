"""Answer "what assays did this paper use?" in one command: extract, verify, correct, map, merge.

The rounds the separate scripts run one at a time, chained:

  1. prompts/extract_assays.txt      builds the registry              3 calls, voted
  2. prompts/verify_assays.txt       judges every entry               1 call per assay
  3. prompts/correct_assay_field.txt repairs what round 2 refused     1 call per flagged FIELD
  4. prompts/resolver_obi_assay.txt  resolves each name to an OBI term  2-3 calls per unmatched
     ("unmatched" = not in the OBI vocabulary verbatim; that exact match is the only free step)
  5. (no prompt — deterministic)     keys by OBI term, folds duplicates  free

Chaining is the whole point: an unverified registry cannot be told apart from a verified one by
reading it, because a `platform` inferred from what a technique usually runs on looks exactly
like one copied out of Methods.

Round 3 promotes, so `assays.json` ends up holding the corrected registry with the extracted
one kept beside it as `assays_precorrection.json`. The run then projects that onto
`assays_benchmark.json` -- name_in_paper, aliases, source, evidence -- **which is the file to
read**. Every field stays in `assays.json` because each pass in the chain works from them. assays.json is written only once every round is done, so a run that dies part-way
leaves none rather than one that looks verified.

Round 5 runs last because the OBI term from round 4 is the assay's identity: the registry is
re-keyed by the term's label, and two entries that mapped to one term are one assay, folded with
every wording kept in `name_in_paper` and every write-up kept in `additional_evidence`. Free, and
the same registry always canonicalizes the same way.

Round 4 runs on the *corrected* registry, and writes `assays_OBI.json` rather than merging back:
the OBI resolver reads sample_type and readouts as disambiguating context, and those are fields
round 3 re-extracts, so mapping earlier would resolve some assays against values the verifier
had already refused. Its exact-match steps are free; only names the vocabulary misses cost.

The chain itself is app.agent.assay_service.assay_report, which is also what POST /agent/assays
runs. This script is the CLI in front of it, so a registry built here and one built through the
endpoint are the same files, and run_assay_verify.py / run_assay_correct.py still read them.

**Nothing is reused between runs.** Every invocation pays for all five rounds, so re-running
a finished paper costs what the first run cost. Reuse was removed because it could not be kept
for round 1 alone -- a fresh registry invalidates the stored verdicts, which invalidates the
corrections derived from them -- and because an edit to extract_assays.txt had no effect on a
paper that had already been run.

**A paper with no JATS XML falls back to its PDF.** Round 1 then reads
prompts/extract_assays_pdf.txt with the PDF attached, in place of extract_assays.txt over the
parsed XML; every later round is the same code on the same files, and the call count does not
change. What changes is traceability: a PDF carries no `[S<n>]` sentence markers, so those
entries have `sentence_ids: []`, round 2 checks each quote against the whole document instead
of against the sentences it names, and the methods-vs-results cross-check reports "unknown".
--dry-run names the source it would use, so which route a paper takes is visible before paying.

**--dry-run makes no API call** and reports the projected bill. Run it first: a 10-assay paper
is upwards of 30 calls. Round 1 is EXTRACTIONS calls (3), voted; rounds 2-4 are sized from what the last run's
extraction found, once one exists on disk -- each from the file that round actually read, since
round 5 re-keys assays.json. Round 5 is free except for one call per mapping the picker
marked BROAD, which asks it once more for a term naming the function (REPICKED).

Usage:
    python3 scripts/run_assay_pipeline.py <registry_dir> [--dry-run]
    python3 scripts/run_assay_pipeline.py --pmid 34252919 --sdy SDY2189 [--dry-run]

Example:
    python3 scripts/run_assay_pipeline.py data/31paper_assays/assay_result_v1/34252919_SDY2189 --dry-run
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent import assay_service
from app.agent.assay_extractor import contract_warnings, paper_names
from app.agent.assay_service import (
    PaperNotFoundError,
    assay_report,
    estimate_run,
    split_stem,
)
from app.agent.claim_parser import _get_client


def split_registry_dir(path: Path) -> tuple[str, str]:
    """`31paper_assays/34252919_SDY2189` -> ("34252919", "SDY2189").

    The halves are identified by which one starts with "SDY" rather than by position, so a
    directory named the other way round still resolves instead of silently producing a paper we
    cannot find. The splitting itself is assay_service.split_stem; what stays here is the
    exit -- a directory that is not a registry is a CLI usage error, not a library one.
    """
    stem = path.resolve().name
    split = split_stem(stem)
    if split is None:
        raise SystemExit(
            f"{stem!r} is not a <pmid>_<SDY> registry directory; pass --pmid/--sdy instead"
        )
    return split


def _print_fields(assays: dict, obi: dict | None = None) -> None:
    """The fields the registry is asked to carry, per entry.

    Name, evidence source, aliases, and the OBI term when round 4 produced one. Printed rather
    than summarised because "10 entries" tells you nothing about whether any of them can be
    traced back to a sentence.
    """
    print("\nname / source / aliases / OBI:" if obi else "\nname / source / aliases:")
    for key, entry in assays.items():
        evidence = entry.get("evidence") or {}
        ids = evidence.get("sentence_ids") or []
        where = entry.get("source") or "?"
        names = paper_names(entry)
        cite = f"{where} {evidence.get('section') or '?'} [{', '.join(ids) or 'no ids'}]"
        aliases = entry.get("aliases")
        shown = ", ".join(aliases) if isinstance(aliases, list) and aliases else (
            "(none)" if isinstance(aliases, list) else f"NOT A LIST: {aliases!r}")
        print(f"  {key}\n      in paper: {', '.join(names) or '(none)'}"
              f"\n      source: {cite}\n      aliases: {shown}")
        # The judge's doubt about the identity, as the deliverable carries it (identity_review):
        # printed here so the terminal and the file say the same thing about the same key.
        review = entry.get("identity_review")
        if isinstance(review, dict) and review.get("verdict"):
            print(f"      identity: {review['verdict']} \u2014 {review.get('reason') or ''}")
        if obi is None:
            continue
        # The resource is printed beside the term because the two say different things: which
        # OBI term this is, and how much a model had to do with choosing it.
        mapped = obi.get(key) or {}
        term = (f"{mapped['obi_id']} {mapped['obi_label']}" if mapped.get("obi_id")
                else "unmapped")
        print(f"      OBI: {term}  ({mapped.get('resource') or 'not mapped'})")


def _dry_run(pmid: str, sdy: str) -> None:
    """Print what the chain would cost, without calling anything.

    A printer over assay_service.estimate_run, which does the counting. The column layout and
    the hard-wrapped caveat live here because they are this script's concern; the numbers, and
    the rule for which of them can be known, are the service's -- POST /agent/assays/estimate
    has to reach the same answer or the cost gate means two different things in two places.
    """
    try:
        estimate = estimate_run(pmid, sdy)
    except PaperNotFoundError as exc:
        raise SystemExit(str(exc))

    # The source kind is printed before the cost, not after: it is what tells a reader which
    # route this paper takes, and a PDF run yields no sentence ids to cite.
    print(f"{estimate['paper_source']} [{estimate['paper_source_kind']}]: "
          f"{estimate['source_chars']:,} chars, title {estimate['paper_title']!r}")
    if estimate["paper_source_kind"] == "pdf":
        print("  no JATS XML for this paper -- round 1 reads the PDF "
              "(prompts/extract_assays_pdf.txt).")
        print("  entries will carry sentence_ids: [];  quotes are checked against the whole "
              "document and")
        print("  the methods-vs-results cross-check reports 'unknown'.")
    print(f"registry: {estimate['registry_dir']}")

    by_name = {round_["name"]: round_ for round_ in estimate["rounds"]}
    verify, correct = by_name["verify"], by_name["correct"]
    obi, canon = by_name["obi"], by_name["canonicalize"]

    n_extract = by_name["extract"]["calls"]
    if n_extract == 1:
        print("  round 1 extract: will run                            1 call")
    else:
        print(f"  round 1 extract: will run                            {n_extract} calls"
              f"   ({n_extract} extractions, majority vote)")

    if verify["calls"] is not None:
        print(f"  round 2 verify:  will run                            ~{verify['calls']} calls"
              "   (the last run found that many)")
    else:
        print("  round 2 verify:  will run, 1 call per assay found    ? calls")

    if correct["calls"] is not None:
        print(f"  round 3 correct: will run                            ~{correct['calls']} calls"
              f"   ({correct['rejected']} assay(s) set aside last run)")
    else:
        print("  round 3 correct: will run, 1 call per flagged field  ? calls")

    if obi["calls"] is not None:
        print(f"  round 4 OBI:     will run                            ~{obi['calls']} calls"
              f"   ({obi['free_matches']} of {obi['assays']} match the vocabulary for free)")
        for key in obi["misses"]:
            print(f"      needs embedding + LLM: {key}")
    else:
        print("  round 4 OBI:     will run, 2-3 calls per unmatched   ? calls")

    if canon["entries"] is not None:
        repicks = canon.get("repicks") or []
        cost = f"~{len(repicks)} calls" if repicks else "0 calls"
        print(f"  round 5 canon:   will run                            {cost}"
              f"   ({canon['entries']} entries \u2192 {canon['groups']}, keyed by OBI term)")
        for group in canon["folds"]:
            print(f"      folds onto {group['key']}: {', '.join(group['members'])}")
        for key in repicks:
            print(f"      re-picks a BROAD term: {key}")
    else:
        print("  round 5 canon:   will run, free                       0 calls")

    if estimate["caveat"]:
        print("\n  ~ because rounds 2-4 are sized from the previous run's output, which this "
              "run\n    re-extracts rather than reuses. The shape rarely moves; it is not "
              "guaranteed.")
    print("\n--dry-run: nothing called.")


def report_result(result: dict) -> None:
    """Print one paper's run in full: rounds, checks, every reason not to trust an entry.

    Factored out of main() so scripts/run_assay_batch.py reports each of its 30 papers the same
    way. One definition on purpose -- CLAUDE.md requires the WARNING / REVIEW / REJECT /
    DROPPED / UNMAPPED lines be reported rather than summarised, and a second copy of this
    logic is how one of them quietly stops being printed.
    """
    print(f"{result['paper_source']} [{result.get('paper_source_kind', 'xml')}]: "
          f"{result['paper_title']!r}")
    for name in ("extract", "verify", "correct", "obi", "canonicalize"):
        row = result["rounds"].get(name, {})
        extra = {k: v for k, v in row.items() if k not in ("source", "calls")}
        print(f"  {name:8} {row.get('source', '?'):10} {row.get('calls', 0)} call(s)"
              + (f"  {json.dumps(extra)}" if extra else ""))
    # An extraction call that answered with nothing usable. The vote went on without it, so the
    # majority was taken over fewer replies than were paid for -- printed, not folded into the
    # count above, because it is a reason to read the MINORITY lines more carefully.
    for label, error in (result["rounds"].get("extract", {}).get("failed") or {}).items():
        print(f"  WARNING  extraction {label} failed: {error}")

    assays = result["assays"]
    check = result["quote_check"]
    kind = result.get("paper_source_kind", "xml")
    print(f"\n{len(assays)} assay(s); {check['verified']}/{check['total']} quotes verbatim, "
          f"{check.get('misattributed', 0)} miscited, {check['missing']} missing, "
          f"{check['source_aligned']}/{check['total']} source-aligned")

    # Both of these are the reasons not to trust an entry, so neither is summarised away.
    # Checked on the delivered registry, against the source it came from: a PDF has no sentence
    # markers, so demanding sentence_ids there printed a false WARNING on every entry.
    # The mapping says which key is an OBI label; without it every re-keyed entry warned.
    for warning in contract_warnings(assays, expect_sentence_ids=(kind == "xml"),
                                     obi=result.get("obi")):
        print(f"  WARNING  {warning}")
    for key, quote in (check.get("per_assay") or {}).items():
        if quote.get("status") in ("misattributed", "too_short", "missing"):
            print(f"  QUOTE {quote['status'].upper()}  {key}: {quote.get('detail')}")

    # Verdicts describe the extraction, before round 3 repaired anything and before round 5
    # re-keyed it -- so each names the key its assay is delivered under now.
    keys = (result.get("merges") or {}).get("key_map") or {}
    for record in (result.get("verification") or {}).get("results", []):
        verdict = record.get("record_verdict")
        if verdict not in ("REVIEW", "REJECT", "ERROR"):
            continue
        assay_id = record.get("assay_id")
        now = keys.get(assay_id)
        where = f" → {now}" if now and now != assay_id else ""
        if verdict == "ERROR":
            # A verification that never happened: every field of this entry is unjudged, and
            # round 3 re-asked all of them.
            print(f"  ERROR  {assay_id}{where}: {record.get('error') or 'verification failed'}")
            continue
        print(f"  {verdict}  {assay_id}{where} "
              f"(identity {record.get('assay_identity_verdict')}; pre-correction verdicts)")
        # The record itself carries no reason -- it is derived from the field verdicts, so the
        # unsupported fields are where the "why" actually lives.
        for field in record.get("field_verifications") or []:
            if field.get("verdict") not in (None, "SUPPORTED"):
                print(f"           {field.get('field_name')}: {field.get('verdict')}"
                      f" — {field.get('reason') or 'no reason given'}")
    for key, record in (result.get("dropped") or {}).items():
        print(f"  DROPPED  {key}: {record.get('reason') or 'rejected'}")
    # An entry fewer than a majority of the extraction calls found. Not delivered, but printed:
    # a rare miss and a Results-only admission both look like this, and a reader decides which.
    for key, record in (result.get("minority") or {}).items():
        quote = ((record.get("entry") or {}).get("evidence") or {}).get("quote") or ""
        print(f"  MINORITY  {key}: found by {len(record.get('runs') or [])} of "
              f"{record.get('of')} extractions; not delivered — {quote[:120]}")
    # Every fold round 5 made: an entry that is no longer a key of its own because another
    # write-up of the same OBI term absorbed it. Printed rather than counted, because the OBI term
    # is coarser than the paper's wording and a fold is exactly where that coarseness shows.
    for record in (result.get("merges") or {}).get("results", []):
        print(f"  MERGED  {', '.join(record['folded'])} → {record['key']} "
              f"({record.get('obi_id') or 'no term'})")
    # A BROAD mapping that blocked a fold and was asked once more: the term it had, and the
    # term it has now. Printed because the entry's identity changed after round 4 reported it.
    for key, change in (result["rounds"].get("canonicalize", {}).get("repicked") or {}).items():
        print(f"  REPICKED  {key}: {change['from']} (BROAD) → {change['to']}")
    # Two entries on one OBI term that round 5 kept apart -- a BROAD mapping, or two techniques
    # reaching one term. Printed as REVIEW: a reader decides whether they are one assay.
    for record in (result.get("merges") or {}).get("blocked", []):
        print(f"  REVIEW  not folded  {record['member']} kept apart from "
              f"{record['kept_apart_from']} ({record.get('obi_id') or 'no term'}): "
              f"{record['reason']}")
    # A repair that was asked for, paid for, and then failed. It used to surface only as a count
    # inside the round's actions JSON, which is how 12 discarded alias corrections crossed a
    # 30-paper run unnoticed: the entry keeps exactly the field the verifier objected to.
    for record in (result.get("corrections") or {}).get("results", []):
        for change in record.get("corrections") or []:
            if change.get("action") == "ERROR" or change.get("error"):
                print(f"  CORRECT FAILED  {record.get('assay_id')} / {change.get('field')}: "
                      f"{change.get('error') or 'no reason given'}")
            elif change.get("action") == "UNCHANGED" and change.get("note"):
                # Refused rather than failed -- a replacement quote that was not verbatim, or no
                # quotable evidence at all -- so the entry kept the value the verifier flagged.
                print(f"  CORRECT REFUSED  {record.get('assay_id')} / {change.get('field')}: "
                      f"{change['note']}")
    # An assay OBI has no term for is the same kind of finding as an unsupported field: it
    # means either a gap in the vocabulary or a name too vague to map, and only reading the
    # name tells you which. Reported per entry rather than as a coverage percentage.
    obi_round = result["rounds"].get("obi", {})
    if obi_round.get("source") == "failed":
        print("  OBI FAILED  mapping did not run; rounds 1-3 are intact. "
              "Re-run: scripts/run_assay_merge.py --map <registry_dir>")
    errors = obi_round.get("errors") or {}
    for key, reason in errors.items():
        print(f"  OBI ERROR  {key}: {reason} (a re-run may map it)")
    for key in obi_round.get("unresolved", []):
        if key not in errors:
            print(f"  UNMAPPED  {key}: no OBI term")

    _print_fields(assays, result.get("obi"))
    meta = result["meta"]
    print(f"\n{meta['llm_calls']} call(s) spent."
          f"\n  {meta['benchmark_path']}  <- the deliverable: name_in_paper, aliases, "
          "source, evidence"
          f"\n  {meta['registry_path']}  the full registry the pipeline works from")
    if meta.get("obi_path"):
        print(f"  {meta['obi_path']}  the same registry with OBI terms attached")
    if meta.get("raw_path"):
        print(f"  {meta['raw_path']}  every model reply this run paid for, by round")


def use_result_version(version: str, pmid: str, sdy: str) -> Path:
    """Route this paper's run into `data/31paper_assays/<version>/` instead of the configured
    result folder, and return the registry directory it will write.

    assay_service.registry_dir only keeps a benchmark paper under REGISTRY_ROOT when its folder
    already exists there -- otherwise the paper is treated as new and lands in the cache -- so
    the folder is created here. Named `<pmid>_<SDY>`, or `_pdf` when the paper has no JATS XML
    and a PDF, the way registry_dir names it. The folder is not emptied: the run deletes every
    stale output of its own before writing, so a re-run over an existing version is the same
    overwrite-in-place as a re-run over the configured one.
    """
    assay_service.REGISTRY_ROOT = assay_service.CORPUS_ROOT / version
    name = f"{pmid.strip()}_{sdy.strip()}"
    if (assay_service.locate_paper_xml(pmid, sdy) is None
            and assay_service.locate_paper_pdf(pmid, sdy) is not None):
        name += assay_service.PDF_DIR_SUFFIX
    target = assay_service.REGISTRY_ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    return target


async def main(pmid: str, sdy: str) -> None:
    try:
        result = await assay_report(pmid, sdy, _get_client(), verify=True, correct=True)
    except PaperNotFoundError as exc:
        raise SystemExit(str(exc))

    report_result(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry_dir", type=Path, nargs="?", default=None,
                        help="registry directory named <pmid>_<SDY>")
    parser.add_argument("--pmid", default="", help="PubMed id (instead of registry_dir)")
    parser.add_argument("--sdy", default="", help="study accession (instead of registry_dir)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the projected call count; makes no API call")
    parser.add_argument("--result-version", metavar="NAME", default="",
                        help="write under data/31paper_assays/NAME/ instead of the configured "
                             "result folder (e.g. assay_result_v3); the folder is created")
    args = parser.parse_args()

    if args.registry_dir is not None:
        pubmed_id, study = split_registry_dir(args.registry_dir)
    elif args.pmid.strip() or args.sdy.strip():
        pubmed_id, study = args.pmid.strip(), args.sdy.strip()
    else:
        parser.error("give a registry directory, or --pmid/--sdy")

    if args.result_version.strip():
        use_result_version(args.result_version.strip(), pubmed_id, study)

    if args.dry_run:
        _dry_run(pubmed_id, study)
    else:
        asyncio.run(main(pubmed_id, study))
