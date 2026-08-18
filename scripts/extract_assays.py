"""Extract the claim-generating assays from a set of papers, as JATS XML or as PDF.

Both inputs run the same .claude/skills/extract-assay-methods ruleset:
  * XML — parsed to text with jats_parser.parse_jats_xml, then extract_assays_text.txt.
  * PDF — raw bytes to the model via pdf_direct.extract_assays_from_pdf_direct, which
    uses extract_assays_pdf.txt. Use this for papers PMC will not serve as XML.

Papers are extracted independently so one paper's assay naming cannot influence
another's. A paper supplied in both formats is taken from its XML; the PDF is skipped.

Per-paper registries (full schema: aliases, evidence_location, confidence, claim_role)
are kept under data/claims/assay_registries/<pmid>_<SDY>/assays.json. They are then
flattened into one table with the same five fields as data/claims/all_assays.json.

Usage:
    python scripts/extract_assays.py [--xml-dir DIR] [--pdf PATH ...] [--out FILE]
                                     [--concurrency N] [--force] [--dry-run]

--pdf takes PDF files and/or directories of them. --force re-extracts papers that
already have a per-paper assays.json (default: skip them, so an interrupted run resumes
without re-paying). --dry-run reports every input's size without making an LLM call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences  # noqa: E402
from app.agent.jats_parser import parse_jats_xml  # noqa: E402
from app.agent.pdf_direct import extract_assays_from_pdf_direct  # noqa: E402
from app.config import settings  # noqa: E402

XML_DIR = ROOT / "data" / "JAT_XML"
REGISTRY_DIR = ROOT / "data" / "claims" / "assay_registries"
OUT_PATH = ROOT / "data" / "claims" / "all_assays_full.json"
EXISTING_TABLE = ROOT / "data" / "claims" / "all_assays.json"
XLSX_PATH = ROOT / "data" / "studyid_pmcid.xlsx"


class Paper(NamedTuple):
    study: str  # "<pmid>_<SDY>", matching all_assays.json
    path: Path
    source: str  # "xml" or "pdf"


def _study_key(path: Path) -> str | None:
    """<SDY>_<pmid>.<ext> -> "<pmid>_<SDY>", the key all_assays.json uses."""
    sdy, _, pmid = path.stem.partition("_")
    return f"{pmid}_{sdy}" if pmid else None


def _load_papers(xml_dir: Path | None, pdf_paths: list[Path]) -> list[Paper]:
    """Collect XML and PDF inputs. XML wins when a study is supplied in both formats."""
    papers: list[Paper] = []
    for path in sorted(xml_dir.glob("*.xml")) if xml_dir else []:
        study = _study_key(path)
        if study is None:
            print(f"  ! {path.name}: not <SDY>_<PMID>.xml, skipping")
            continue
        papers.append(Paper(study, path, "xml"))

    seen = {p.study for p in papers}
    for path in _expand_pdf_paths(pdf_paths):
        study = _study_key(path)
        if study is None:
            print(f"  ! {path.name}: not <SDY>_<PMID>.pdf, skipping")
            continue
        if study in seen:
            print(f"  - {study}: PDF skipped, already covered by XML")
            continue
        seen.add(study)
        papers.append(Paper(study, path, "pdf"))
    return sorted(papers)


def _expand_pdf_paths(paths: list[Path]) -> list[Path]:
    """Accept PDF files and directories of PDFs, in the order given."""
    expanded: list[Path] = []
    for path in paths:
        if path.is_dir():
            expanded.extend(sorted(path.glob("*.pdf")))
        elif path.suffix.lower() == ".pdf":
            expanded.append(path)
        else:
            print(f"  ! {path}: not a PDF or directory, skipping")
    return expanded


def _load_vocabulary() -> list[str]:
    """Controlled assay names: those already used in all_assays.json plus the xlsx column."""
    vocab: list[str] = []
    if EXISTING_TABLE.exists():
        for row in json.loads(EXISTING_TABLE.read_text(encoding="utf-8")):
            name = row.get("normalized_name")
            if name and name not in vocab:
                vocab.append(name)
    if XLSX_PATH.exists():
        wb = openpyxl.load_workbook(str(XLSX_PATH), read_only=True, data_only=True)
        ws = wb.active
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        col = headers.index("ASSAY METHODS")
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[col]:
                continue
            for term in str(row[col]).split(","):
                term = term.strip()
                if term and term not in vocab:
                    vocab.append(term)
    return sorted(vocab)


async def _extract_one(paper: Paper, system_prompt: str, client, semaphore) -> dict:
    """Extract one paper's assay registry, from its XML text or its raw PDF."""
    if paper.source == "xml":
        paper_text = parse_jats_xml(paper.path.read_text(encoding="utf-8"))
        if not paper_text.strip():
            print(f"  ! {paper.study}: XML parsed to empty text")
            return {}
        async with semaphore:
            resp = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": paper_text},
                ],
                temperature=0,
            )
        assays = json.loads(
            _strip_fences((resp.choices[0].message.content or "").strip())
        ).get("assays", {})
    else:
        async with semaphore:
            assays = await extract_assays_from_pdf_direct(
                paper.path.read_bytes(), paper.path.name, client
            )

    print(f"  {paper.study} [{paper.source}]: {len(assays)} assays — "
          f"{', '.join(assays) or '(none)'}")
    return assays


def _match_vocabulary(name: str, vocab: list[str]) -> str | None:
    """Exact then case-insensitive vocabulary hit; None when the model must decide."""
    if name in vocab:
        return name
    lowered = {term.lower(): term for term in vocab}
    return lowered.get(name.strip().lower())


async def _normalize_names(names: list[str], vocab: list[str], client) -> dict[str, str]:
    """Map each raw assay name to a controlled term, or back to itself when none fits.

    Exact and case-insensitive matches are resolved locally; only the remainder costs
    a single LLM call over the whole deduplicated list.
    """
    mapping = {}
    unresolved = []
    for name in names:
        hit = _match_vocabulary(name, vocab)
        if hit:
            mapping[name] = hit
        else:
            unresolved.append(name)

    if not unresolved:
        return mapping

    system_prompt = (
        "You normalize assay names from biomedical papers onto a controlled vocabulary.\n\n"
        "For each input name, return the vocabulary term naming the SAME measurement "
        "technique. Match on the technique itself, not on wording: an abbreviation, an "
        "expansion, or a platform alias of a vocabulary term is that term. If no vocabulary "
        "term describes the same measurement, return the input name unchanged — never force "
        "a loose match onto a different technique.\n\n"
        "Controlled vocabulary:\n"
        + "\n".join(f"- {term}" for term in vocab)
        + '\n\nReturn ONLY valid JSON: {"<input name>": "<vocabulary term or the input name>"}, '
        "one key per input name, all inputs present."
    )
    print(f"Normalizing {len(unresolved)} unmatched names against {len(vocab)} vocabulary terms...")
    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(unresolved, ensure_ascii=False, indent=2)},
        ],
        temperature=0,
    )
    picked = json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))
    for name in unresolved:
        mapping[name] = picked.get(name) or name
    return _collapse_case_variants(mapping)


def _collapse_case_variants(mapping: dict[str, str]) -> dict[str, str]:
    """Fold normalized names that differ only by case/whitespace onto one spelling.

    Names the model leaves unmapped keep the paper's wording, and two papers can write
    the same unmapped technique with different capitalization ("Multiplex Cytokine
    Analysis" / "multiplex cytokine analysis"). Those are one assay, so the table must
    not carry both. The most-used spelling wins; ties go to the first alphabetically.
    """
    spellings: dict[str, list[str]] = {}
    for value in mapping.values():
        spellings.setdefault(" ".join(value.split()).lower(), []).append(value)
    canonical = {
        key: max(sorted(set(variants)), key=variants.count) for key, variants in spellings.items()
    }
    return {
        name: canonical[" ".join(value.split()).lower()] for name, value in mapping.items()
    }


def _flatten(registries: dict[str, dict], normalized: dict[str, str]) -> list[dict]:
    """Registry-per-paper -> flat rows matching all_assays.json's five fields."""
    rows = []
    for study in sorted(registries):
        for name, entry in registries[study].items():
            rows.append(
                {
                    "study": study,
                    "assay": entry.get("name_in_paper", name),
                    "normalized_name": normalized.get(name, name),
                    "sample_type": entry.get("sample_type", ""),
                    "readouts": entry.get("readouts", ""),
                }
            )
    return sorted(rows, key=lambda r: (r["study"], r["assay"]))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml-dir", type=Path, default=XML_DIR)
    parser.add_argument(
        "--pdf",
        type=Path,
        nargs="*",
        default=[],
        metavar="PATH",
        help="PDF files and/or directories of PDFs, for papers with no XML",
    )
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--force", action="store_true", help="re-extract papers already done")
    parser.add_argument("--dry-run", action="store_true", help="parse only, no LLM calls")
    args = parser.parse_args()

    papers = _load_papers(args.xml_dir, args.pdf)
    by_source = Counter(p.source for p in papers)
    print(f"{len(papers)} papers ({by_source['xml']} xml, {by_source['pdf']} pdf)\n")

    if args.dry_run:
        total = 0
        for paper in papers:
            if paper.source == "pdf":
                size = paper.path.stat().st_size
                print(f"  {paper.study:24s} {size:9,d} bytes  [pdf]")
                continue
            text = parse_jats_xml(paper.path.read_text(encoding="utf-8"))
            heads = [line[3:] for line in text.splitlines() if line.startswith("## ")]
            has_methods = any(
                k in h.lower()
                for h in heads
                for k in ("method", "procedure", "material", "study design", "protocol")
            )
            total += len(text)
            flag = "" if has_methods else "  <- no Methods section"
            print(f"  {paper.study:24s} {len(text):7,d} chars  {len(heads):2d} sections{flag}")
        print(f"\nTotal {total:,} XML chars (~{total // 4:,} tokens). No LLM calls made.")
        return 0

    client = _get_client()
    system_prompt = _load_prompt("extract_assays_text.txt")
    semaphore = asyncio.Semaphore(args.concurrency)

    registries: dict[str, dict] = {}
    todo: list[Paper] = []
    for paper in papers:
        cached = REGISTRY_DIR / paper.study / "assays.json"
        if cached.exists() and not args.force:
            registries[paper.study] = json.loads(cached.read_text(encoding="utf-8"))
            print(f"  {paper.study}: cached ({len(registries[paper.study])} assays)")
        else:
            todo.append(paper)

    if todo:
        print(f"\nExtracting {len(todo)} papers with {settings.OPENAI_MODEL} "
              f"(concurrency {args.concurrency})...")
        results = await asyncio.gather(
            *(_extract_one(p, system_prompt, client, semaphore) for p in todo),
            return_exceptions=True,
        )
        for paper, result in zip(todo, results):
            if isinstance(result, Exception):
                print(f"  ! {paper.study}: {type(result).__name__}: {result}")
                continue
            registries[paper.study] = result
            out_dir = REGISTRY_DIR / paper.study
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "assays.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    vocab = _load_vocabulary()
    raw_names = sorted({name for reg in registries.values() for name in reg})
    normalized = await _normalize_names(raw_names, vocab, client)

    rows = _flatten(registries, normalized)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    empty = [study for study, reg in registries.items() if not reg]
    print(f"\nWrote {args.out.relative_to(ROOT)}")
    print(f"  {len(rows)} rows across {len(registries)} papers, "
          f"{len({r['normalized_name'] for r in rows})} distinct normalized names")
    if len(registries) < len(papers):
        missing = sorted({p.study for p in papers} - set(registries))
        print(f"  ! {len(missing)} papers produced no registry: {', '.join(missing)}")
    if empty:
        print(f"  ! {len(empty)} papers returned zero assays: {', '.join(empty)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
