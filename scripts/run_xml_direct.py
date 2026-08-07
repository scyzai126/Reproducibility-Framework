"""Run the JATS-XML pipeline end-to-end: JATS-parsed paper text + the PDF pages
containing each figure/table (attached as images), sent to the model.

Assays and claims are extracted independently and concurrently (each claim
self-names its own assay, without seeing the assay registry), then reconciled:
exact/alias string matching first, a single paper-grounded validation call for
whatever's left, then one OBI-enrichment pass over the final registry. Mirrors
run_pdf_direct.py's flow for the XML pipeline.

Usage:
    python scripts/run_xml_direct.py <jats_text_path> <pdf_path> <out_dir>

Example:
    python scripts/run_xml_direct.py \\
        data/claims/SDY1119_26682988_jats_figures/jats_text.txt \\
        data/pdf/26papers/SDY1119_26682988.pdf \\
        data/claims/SDY1119_26682988_jats_xml

Output files:
    assays.json                     - independently-discovered, reconciled assay registry
    assays_OBI.json                 - assays.json enriched with OBI ontology mappings
    claims.json                     - independently-extracted claims, linked to assays.json;
                                      a claim the linker could not tie to a registry entry is
                                      kept, flagged assay.link_status = "unlinked"
    unlinked_claims.json            - diagnostic list of the unlinked claims and why (only if
                                      non-empty); they remain present in claims.json
    abstract_unmatched_findings.json - Abstract findings with no Results/Figure/Table support (only if non-empty)
    groups.json                     - claims structured into groups + comparisons (classify_groups.txt)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.assay_claim_linker import attach_assay_links, reconcile_claims_with_assays
from app.agent.assay_obi_mapper import enrich_assays_with_obi
from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_vision import (
    _jats_and_figures_content,
    extract_assays_from_jats_xml,
    extract_claims_from_jats_xml,
)
from app.config import settings


async def run_group_step(claims: dict, client) -> dict:
    """Structure each claim into comparison_strategy + groups + comparison via classify_groups.txt."""
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    print(f"Step 3: structuring {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key].get("sources", [])}}
        prompt = template.replace("{claims}", json.dumps(single, indent=2))
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        result: dict = json.loads(raw)
        val = result.get(key, {})
        val.setdefault("claim", claims[key]["claim"])
        val.setdefault("sources", claims[key].get("sources", []))
        groups[key] = val
        print(f"  [{i}/{len(claim_keys)}] {key} done")
    return groups


async def main(jats_text_path: Path, pdf_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    paper_text = jats_text_path.read_text(encoding="utf-8")
    pdf_bytes = pdf_path.read_bytes()
    print(f"JATS text: {len(paper_text)} chars from {jats_text_path}")
    print(f"PDF: {len(pdf_bytes):,} bytes from {pdf_path}")

    client = _get_client()

    print(f"Extracting assays and claims concurrently with {settings.OPENAI_MODEL}...")
    assays, (claims, abstract_unmatched) = await asyncio.gather(
        extract_assays_from_jats_xml(paper_text, pdf_bytes, client),
        extract_claims_from_jats_xml(paper_text, pdf_bytes, client),
    )
    print(f"  assays found: {list(assays.keys())}")
    print(f"  claims found: {len(claims)}")

    print("Reconciling claims against the assay registry...")
    paper_content = _jats_and_figures_content(paper_text, pdf_bytes)
    resolved, merged_assays, unlinked_claims = await reconcile_claims_with_assays(
        claims, assays, paper_content, client
    )
    print(f"  {len(resolved)}/{len(claims)} claims linked, {len(unlinked_claims)} left unlinked")
    if len(merged_assays) > len(assays):
        added = set(merged_assays) - set(assays)
        print(f"  validation added {len(added)} assay(s) missed by discovery: {sorted(added)}")

    final_claims = attach_assay_links(claims, resolved, merged_assays, unlinked_claims)

    (out_dir / "assays.json").write_text(json.dumps(merged_assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays.json")

    print("Enriching final assay registry with OBI terms...")
    final_assays = enrich_assays_with_obi(merged_assays)
    (out_dir / "assays_OBI.json").write_text(json.dumps(final_assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays_OBI.json")

    (out_dir / "claims.json").write_text(json.dumps(final_claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims.json")

    unlinked_path = out_dir / "unlinked_claims.json"
    if unlinked_claims:
        unlinked_path.write_text(json.dumps(unlinked_claims, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  saved unlinked_claims.json ({len(unlinked_claims)} unlinked, all retained in claims.json)")
    elif unlinked_path.exists():
        unlinked_path.unlink()

    unmatched_path = out_dir / "abstract_unmatched_findings.json"
    if abstract_unmatched:
        unmatched_path.write_text(json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  saved abstract_unmatched_findings.json")
    elif unmatched_path.exists():
        unmatched_path.unlink()

    groups = await run_group_step(final_claims, client)
    (out_dir / "groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved groups.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python scripts/run_xml_direct.py <jats_text_path> <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
