"""Find where each paper's data lives, and separate its own data from data it reused or only cited.

--all runs the benchmark papers: one per folder under assay_service.REGISTRY_ROOT (named <PMID>_<SDY>,
optionally with a _pdf suffix). Each is read from data/JAT_XML/<SDY>_<PMID>.xml when that
exists, otherwise from the first data/pdf/**/<SDY>_<PMID>.pdf. Per paper:

1. regex candidates, with the sentence and the sentences either side, and  (free)
   whether the paper's Data Availability statement names each one
2. one LLM call per paper over EVERY text-named ID, with its repository     (paid)
   guess, sentences and DA membership, plus the full paper text: is it
   really an ID, is it in the DA statement, and is it this study's data /
   public data / reference / registration?
3. validation against each repository, after the LLM: exists? which paper  (free, network + local DB)
   owns it? plus datasets the repository links to this PMID
4. combine: the LLM's answer is final; disagreements with the DA statement
   or the repository record become REVIEW lines
5. locate each deposited, verified dataset: landing page, download folder,  (free, network)
   files with sizes, related records (data_locator; --no-locate skips it)

An ID the LLM gave no answer for (the call failed, or the answer was refused) is `unclear`.

**--dry-run makes no network and no API call**: it reports how many LLM calls the real run would
make and roughly how many input tokens they would send. Run it first.

Writes two files per paper to data/benchmark_assay/data_availability/ (overwritten in place):
  <SDY>_<PMID>_llm.json  before validation: every ID, its sentences, DA membership and the LLM's
                         judgement (roles straight from the LLM)
  <SDY>_<PMID>.json      after validation, the final answer: `data_repositories` -- the
                         repositories holding this study's own data, with landing page, download
                         folder and size -- and `unconfirmed`, deposited IDs the repository could
                         not confirm, with the reason. Code, reused and referenced IDs stay in
                         the _llm file.
and, for more than one paper, a roll-up table at data/benchmark_assay/data_availability/summary.md. Every
REVIEW, DROPPED, WARNING and SKIPPED line is printed.

Usage:
    python3 scripts/run_data_availability.py --all --dry-run
    python3 scripts/run_data_availability.py --all                  # the paid run
    python3 scripts/run_data_availability.py data/JAT_XML/SDY2189_34252919.xml
    python3 scripts/run_data_availability.py data/pdf/26papers/SDY1291_23151505.pdf
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.data_availability import (  # noqa: E402
    DEPOSITED,
    REFERENCED,
    REGISTRATION,
    REUSED,
    ROLES,
    UNCLEAR,
    DataAvailabilityError,
    add_linked_datasets,
    apply_validation,
    benchmark_papers,
    build_prompt,
    build_record,
    classify_candidates,
    group_mentions,
    llm_candidates,
    repository_record,
    load_paper,
    settle_drops,
)

from app.agent.data_availability_service import immport_lookup_factory, run_paper  # noqa: E402
from app.config import settings  # noqa: E402

from app.agent.assay_service import REGISTRY_ROOT  # noqa: E402

ASSAY_DIR = REGISTRY_ROOT
JATS_DIR = _REPO_ROOT / "data" / "JAT_XML"
PDF_ROOT = _REPO_ROOT / "data" / "pdf"
OUT_DIR = _REPO_ROOT / "data" / "benchmark_assay" / "data_availability"

def _load(path: Path) -> dict:
    paper = load_paper(path)
    paper["entries"] = group_mentions(paper["mentions"])
    return paper


def _papers(args) -> list[tuple[str, Optional[Path]]]:
    if args.all:
        return benchmark_papers(ASSAY_DIR, JATS_DIR, PDF_ROOT)
    return [(Path(p).stem, Path(p)) for p in args.paper]


def dry_run(papers: list[tuple[str, Optional[Path]]]) -> None:
    from app.agent.data_locator import LOCATABLE

    calls = chars = locatable = 0
    print(f"{'paper':<24} {'src':>4} {'DA statement':>12} {'cands':>5} {'in DA':>5} {'~tokens':>8}")
    for stem, path in papers:
        if path is None:
            print(f"{stem:<24} SKIPPED: no XML or PDF")
            continue
        paper = _load(path)
        cands = llm_candidates(paper["entries"])
        tokens = 0
        if cands:
            calls += 1
            prompt_chars = len(build_prompt(paper["title"] or "", paper["pmid"], paper["text"], cands))
            chars += prompt_chars
            tokens = prompt_chars // 4
        locatable += sum(1 for e in paper["entries"].values()
                         if e["repository"] in LOCATABLE and e["kind"] == "data")
        in_da = sum(1 for e in paper["entries"].values() if e["in_da"])
        print(f"{stem:<24} {paper['format']:>4} {paper['statement_source'] or 'none':>12} "
              f"{len(paper['entries']):>5} {in_da:>5} {tokens:>8,}")
        if not paper["entries"]:
            print(f"  NOTHING IN TEXT: {stem} names no accession outside its references "
                  "(the real run still asks the repositories for datasets linked to its PMID)")
    print(f"\n{len(papers)} papers; the real run would make {calls} LLM call(s), "
          f"~{chars // 4:,} input tokens (chars/4). Every text-named ID is sent, so this is the "
          "real count, not an upper bound. No network or API call was made.")
    print(f"Locating: at most {locatable} text-named IDs sit in a repository the locator covers; "
          "only those that end up deposited and verified are looked up (free, public APIs).")


async def _immport_lookup_factory():
    """An ImmPort lookup over the local database, plus a closer. (None, None) if unavailable."""
    return await immport_lookup_factory(lambda line: print(f"  WARNING: {line}"))


def _format_size(n: Optional[int]) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


async def run(papers: list[tuple[str, Optional[Path]]], validate: bool,
              locate_data: bool = True) -> None:
    import httpx

    from app.agent.accession_validator import _Ncbi
    from app.agent.claim_parser import _get_client

    client = _get_client()

    immport_lookup, close_db = (await _immport_lookup_factory()) if validate else (None, None)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, Optional[dict]]] = []
    cache: dict[str, dict] = {}
    locate_cache: dict = {}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        ncbi = _Ncbi(http)
        for stem, path in papers:
            if path is None:
                print(f"{stem}: SKIPPED: no XML or PDF")
                records.append((stem, None))
                continue
            # One paper, end to end, by the same code the web app's Extract tab runs.
            result = await run_paper(stem, path, client=client, http=http, ncbi=ncbi,
                                     immport_lookup=immport_lookup, validate=validate,
                                     locate_data=locate_data, cache=cache,
                                     locate_cache=locate_cache, out_dir=OUT_DIR)
            paper, record, final = result["paper"], result["record"], result["final"]
            llm_model, notes = result["llm_model"], result["notes"]
            located, located_of = result["located"], result["located_of"]
            llm_out, out = result["llm_path"], result["final_path"]
            records.append((stem, record))

            counts = ", ".join(f"{role} {len(record[role])}" for role in ROLES if record[role])
            da_note = f"DA {paper['statement_source']}" if paper["statement_source"] else "no DA statement"
            llm_note = f", LLM {llm_model}" if llm_model else ", no LLM answer"
            print(f"{stem} [{paper['format']}, {da_note}{llm_note}]: "
                  f"{counts or 'nothing found'} -> {llm_out.relative_to(_REPO_ROOT)}")
            repos = ", ".join(f"{r['repository']} {r['accession']}" for r in final["data_repositories"])
            print(f"  data repositories: {repos or 'none'} -> {out.relative_to(_REPO_ROOT)}")
            for item in final["unconfirmed"]:
                print(f"  UNCONFIRMED: {item['repository']} {item['accession']} "
                      f"({item['status']}: {item['detail']})")
            if located_of:
                print(f"  located {located}/{located_of} deposited datasets")
            for line in record["reviews"]:
                print(f"  REVIEW: {line}")
            for line in record["dropped"]:
                print(f"  DROPPED: {line}")
            for line in record["warnings"]:
                print(f"  WARNING: {line}")
            for line in notes:
                print(f"  NOTE: {line}")

    if close_db is not None:
        await close_db()
    if len(papers) > 1:
        _write_summary(records)


def _fmt(items: list[dict], kind: str | None = "data") -> str:
    """Accessions of one kind ("data" / "code"), or every accession when kind is None."""
    return ", ".join(f"{e['repository']} {e['accession']}" for e in items
                     if kind is None or e.get("kind", "data") == kind) or "-"


def _write_summary(records: list[tuple[str, Optional[dict]]]) -> None:
    lines = [
        "# Where each paper's data lives",
        "",
        "Generated by `scripts/run_data_availability.py`. Per paper, `<SDY>_<PMID>_llm.json` has "
        "the quotes and the LLM's reason behind every cell; `<SDY>_<PMID>.json` has the "
        "validated data repositories and their links.",
        "",
        "- **LLM**: whether the LLM answered. Its answer decides every role; every disagreement "
        "with the DA statement or the repository record is a REVIEW line. Without an answer, the "
        "paper's IDs are **Unclear**. **DA statement**: how the paper's Data Availability "
        "statement was found (*section* / *inline_label*), or *none*.",
        "- **Deposited**: this paper's own data. **Reused**: another study's data this paper "
        "analysed. **Referenced**: named but not used. **Unclear**: needs a human look (see the "
        "REVIEW lines in the JSON).",
        "",
        "| Paper | Source | LLM | DA statement | Deposited | Reused | Referenced | Unclear | Trial reg. | Own code |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for stem, rec in records:
        if rec is None:
            lines.append(f"| {stem} | - | - | SKIPPED: no XML or PDF | - | - | - | - | - | - |")
            continue
        lines.append(
            f"| {stem} | {rec['source_format']} | {'yes' if rec['llm_called'] else 'no'} | "
            f"{rec.get('data_availability_source') or 'none'} | "
            f"{_fmt(rec[DEPOSITED])} | {_fmt(rec[REUSED])} | {_fmt(rec[REFERENCED], None)} | "
            f"{_fmt(rec[UNCLEAR], None)} | {_fmt(rec[REGISTRATION], None)} | "
            f"{_fmt(rec[DEPOSITED], 'code')} |")
    lines += [
        "",
        "## Deposited data locations",
        "",
        "Where each deposited, verified dataset sits (`data_repositories` in each paper's "
        "`<SDY>_<PMID>.json`). Files are never downloaded.",
        "",
        "| Paper | ID | Access | Landing page | Download folder | Files | Size |",
        "|---|---|---|---|---|---|---|",
    ]
    for stem, rec in records:
        for item in (rec or {}).get(DEPOSITED, []):
            loc = item.get("location")
            if not loc:
                continue
            folder = (loc.get("download") or {}).get("https") or (loc.get("download") or {}).get("ftp") or "-"
            files = loc["file_count"] or "-"
            size = _format_size(loc["total_size_bytes"]) if loc["total_size_bytes"] else "-"
            flag = f" (error: {loc['error']})" if loc["error"] else ""
            lines.append(f"| {stem} | {item['repository']} {item['accession']} | {loc['access']} | "
                         f"{loc['landing_page']} | {folder} | {files} | {size}{flag} |")
    path = OUT_DIR / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nsummary -> {path.relative_to(_REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paper", nargs="*", help="paper file(s) named <SDY>_<PMID>.xml or .pdf")
    parser.add_argument("--all", action="store_true", help=f"the benchmark papers in {ASSAY_DIR}")
    parser.add_argument("--dry-run", action="store_true",
                        help="no network, no API call, no files: report the LLM cost only")
    parser.add_argument("--no-validate", action="store_true", help="skip the repository lookups")
    parser.add_argument("--no-locate", action="store_true",
                        help="skip finding where each deposited dataset sits (free, network)")
    args = parser.parse_args()

    papers = _papers(args)
    if not papers:
        parser.error("give paper file(s) or --all")

    if args.dry_run:
        dry_run(papers)
    else:
        asyncio.run(run(papers, validate=not args.no_validate, locate_data=not args.no_locate))


if __name__ == "__main__":
    main()
