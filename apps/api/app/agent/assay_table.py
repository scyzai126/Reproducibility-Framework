"""The assay table the /assays page renders, built from the finished registries. Free.

One row per final assay: every entry of every `<registry_dir>/assays_OBI.json` under a registry
root. Round 5 has already keyed those entries by OBI term and folded duplicates, so a row is one
assay the paper performed, with every wording the paper used for it joined into `assay`. **It calls
nothing** -- the OBI term is already on disk.

Two callers, one builder, so the two tables cannot differ:
  * scripts/build_assay_table.py writes the whole corpus to `all_assays_OBI.json` (Corpus tab);
  * GET /agent/assays/table builds one paper's rows on demand (Extract tab), via `only=`.

The rows keep the schema `GET /agent/assay-obi` serves and `AssayObiRow` (apps/web/src/lib/types.ts)
renders -- study, assay, standard_technique_name, sample_type, readouts, obi_id, obi_label, resource,
obi_confidence -- plus:

* the curator's matching assay from `data/benchmark_curator_assay/`, paired by
  scripts/compare_assay_benchmark.py -- the same pairing the benchmark report scores:
  `benchmark_assay`, `benchmark_obi_label`, `benchmark_obi_id` (" / "-joined where several curator
  assays pair with one of ours, null where none does) and `benchmark_items`, one structured entry
  per curator assay with its `key` and `obi_match` (`same`, `related`, `differs`, `ours_unmapped`,
  `curator_unmapped`, `missed`). A curator assay that pairs with nothing of ours becomes its own
  row with `benchmark_only: true`;
* `paper_url` / `paper_source`: the paper's PMC page when the JATS XML the agent read names its
  PMCID (in `<article-meta>`, never the reference list), else PubMed.

`study` is `<pmid>_<SDY>` with the `_pdf` marker dropped, the spelling
`assay_immport.study_accession_of` parses.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

from app.agent import assay_service
from app.agent.assay_service import split_stem

_REPO_ROOT = Path(__file__).resolve().parents[4]
#: The curators' latest pass. v1 was deleted when v2 and v4 were added; the compare script and
#: tests/test_benchmark_assay_data.py name the same folder.
BENCHMARK_DIR = _REPO_ROOT / "data" / "benchmark_curator_assay" / "benchmark_assay_v5"
#: The benchmark pairing lives in a CLI script that is not an importable package.
_COMPARISON_SCRIPT = _REPO_ROOT / "scripts" / "compare_assay_benchmark.py"

_ARTICLE_META = re.compile(r"<article-meta\b.*?</article-meta>", re.S)
_PMCID = re.compile(r'<article-id pub-id-type="pmc(?:id)?">\s*(?:PMC)?(\d+)\s*</article-id>')


def paper_link(pmid: str, sdy: str) -> tuple[str, str]:
    """(url, source) for reading the paper: PMC when its JATS XML names a PMCID, else PubMed.

    Only `<article-meta>` is read -- the reference list carries the PMCIDs of every cited paper.
    """
    xml = assay_service.locate_paper_xml(pmid, sdy)
    if xml is not None:
        meta = _ARTICLE_META.search(xml.read_text(encoding="utf-8", errors="ignore"))
        found = _PMCID.search(meta.group(0)) if meta else None
        if found:
            return f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{found.group(1)}/", "PMC"
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "PubMed"


def _comparison_module():
    spec = importlib.util.spec_from_file_location("compare_assay_benchmark", _COMPARISON_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _curator_label(entry: dict, obi_id: str | None, label_of: dict) -> str | None:
    """The OBI label the curator wrote beside their id, else the ontology's label for that id."""
    for name in ("OBI ontology", "OBI_ontology", "obi_ontology", "OBI", "obi"):
        block = entry.get(name)
        if isinstance(block, dict) and block.get("obi_label"):
            return block["obi_label"]
    return label_of.get(obi_id) if obi_id else None


#: compare_assay_benchmark.py's status for a found curator assay -> how the two OBI terms compare.
_OBI_MATCH = {"MATCH": "same", "MATCH_GRANULARITY": "related", "SPLIT": "related",
              "MATCH_OBI_CONFLICT": "differs"}


def _obi_match(status: str, bench_id: str | None, ours_id: str | None) -> str:
    if status == "MISSED":
        return "missed"
    if status == "MATCH_OBI_UNMAPPED" or not bench_id or not ours_id:
        return "ours_unmapped" if not ours_id else "curator_unmapped"
    if bench_id == ours_id:
        return "same"
    return _OBI_MATCH.get(status, "differs")


def benchmark_pairing(registry_root: Path, benchmark_dir: Path,
                      only: str | None = None) -> tuple[dict, dict]:
    """Pair every curator assay with our registry entries, exactly as the benchmark report does.

    Returns `(paired, missed)`: `paired[(registry_dir_name, our_key)]` is the list of curator
    assays matched to that entry, `missed[study]` the curator assays matched to nothing. Each
    curator assay is `{"key", "name", "label", "id", "obi_match"}`. `only` restricts the pairing
    to one registry directory.
    """
    paired: dict[tuple[str, str], list[dict]] = {}
    missed: dict[str, list[dict]] = {}
    if not benchmark_dir.is_dir() or not registry_root.is_dir():
        return paired, missed
    cmp = _comparison_module()
    cmp.BENCHMARK_DIR, cmp.REGISTRY_DIR = benchmark_dir, registry_root
    cmp.REPO_ROOT = Path(os.path.commonpath([benchmark_dir.resolve(), registry_root.resolve()]))
    pairs, _skipped = cmp.discover_pairs()
    if only is not None:
        pairs = [p for p in pairs if p["registry"].name == only]
    if not pairs:
        return paired, missed
    obi = cmp.ObiGraph()
    for pair in pairs:
        curated = json.loads(pair["benchmark"].read_text(encoding="utf-8"))
        study = f"{pair['pmid']}_{pair['study']}"
        for row in cmp.compare_paper(pair, obi)["rows"]:
            bench = row["benchmark"]
            if bench is None:
                continue
            item = {"key": bench["key"], "name": bench["name_in_paper"],
                    "label": _curator_label(curated.get(bench["key"], {}), bench["obi_id"], obi.label_of),
                    "id": bench["obi_id"]}
            if row["status"] == "MISSED":
                missed.setdefault(study, []).append({**item, "obi_match": "missed"})
            elif row["status"] in cmp.MATCHED_STATUSES:
                for ours in row["ours"]:
                    paired.setdefault((pair["registry"].name, ours["key"]), []).append(
                        {**item, "obi_match": _obi_match(row["status"], bench["obi_id"], ours["obi_id"])})
    return paired, missed


def _item(item: dict) -> dict:
    return {"key": item["key"], "name": item["name"], "obi_label": item["label"],
            "obi_id": item["id"], "obi_match": item["obi_match"]}


def _joined(items: list[dict], field: str) -> str | None:
    values = [str(item[field]) if item[field] else "—" for item in items]
    return " / ".join(values) if items else None


def _wordings(name_in_paper) -> str:
    """Every wording round 5 kept, as one cell. A registry from before round 5 holds a string."""
    if isinstance(name_in_paper, list):
        return " / ".join(n for n in name_in_paper if isinstance(n, str) and n)
    return name_in_paper or ""


def table_rows(registry_root: Path, benchmark_dir: Path = BENCHMARK_DIR,
               only: str | None = None) -> list[dict]:
    """One row per entry of every registry's assays_OBI.json, sorted by study then registry order,
    each carrying its curator match; then one `benchmark_only` row per curator assay we missed.

    `only` names one registry directory (e.g. `19047440_SDY1289`, or `..._pdf`): the rows for
    that paper alone, built exactly as the corpus rows are.
    """
    paired, missed = benchmark_pairing(registry_root, benchmark_dir, only)
    pattern = f"{only}/assays_OBI.json" if only is not None else "*/assays_OBI.json"
    rows: list[dict] = []
    for obi_path in sorted(registry_root.glob(pattern)):
        split = split_stem(obi_path.parent.name)
        if not split:
            continue
        pmid, sdy = split
        paper_url, paper_source = paper_link(pmid, sdy)
        entries = json.loads(obi_path.read_text(encoding="utf-8"))
        for key, entry in entries.items():
            bench = paired.get((obi_path.parent.name, key), [])
            rows.append({
                "study": f"{pmid}_{sdy}",
                "assay": _wordings(entry.get("name_in_paper")),
                "standard_technique_name": entry.get("standard_technique_name") or "",
                "sample_type": entry.get("sample_type") or "",
                "readouts": entry.get("readouts") or "",
                "obi_id": entry.get("obi_id"),
                "obi_label": entry.get("obi_label"),
                "resource": entry.get("resource") if entry.get("obi_id") else "unresolved",
                "obi_confidence": entry.get("obi_confidence"),
                "benchmark_assay": _joined(bench, "name"),
                "benchmark_obi_label": _joined(bench, "label"),
                "benchmark_obi_id": _joined(bench, "id"),
                "benchmark_items": [_item(b) for b in bench],
                "paper_url": paper_url,
                "paper_source": paper_source,
            })
        for item in missed.pop(f"{pmid}_{sdy}", []):
            rows.append({
                "study": f"{pmid}_{sdy}", "assay": "", "standard_technique_name": "", "sample_type": "",
                "readouts": "", "obi_id": None, "obi_label": None, "resource": None,
                "obi_confidence": None, "benchmark_assay": item["name"],
                "benchmark_obi_label": item["label"], "benchmark_obi_id": item["id"],
                "benchmark_items": [_item(item)], "benchmark_only": True,
                "paper_url": paper_url, "paper_source": paper_source,
            })
    return rows
