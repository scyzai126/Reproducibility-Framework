"""Extract a paper's assay registry from its PDF: one LLM call per extraction, voted like the XML route.

The sibling of app.agent.assay_extractor, for the papers PMC will not serve as JATS XML --
the publisher blocks full-text download, so there is nothing for jats_parser to read. Four
corpus papers are in that position (SDY1276/21357945, SDY1291/23151505, SDY1293/20078211,
SDY404/25367297) and had no route through the assay pipeline at all before this module.

prompts/extract_assays_pdf.txt is the authority on the rules, and is deliberately paired with
prompts/extract_assays.txt: from "## What counts as an entry" to the per-field rules the two are
the same text, except for the `evidence` bullet, which on this route has to say that there are no
sentence markers and that `section` is the only record of where the quote sits. An edit to one of
the shared sections belongs in both files. The XML prompt is the original; this one exists
because its input contract cannot survive the change of source:

  * The XML parse hands the model `## Heading  [methods]` section tags, and tells it the tag is
    authoritative. A PDF has no tags, so this prompt has the model read the headings itself.
  * The XML parse prefixes every sentence with an `[S<n>]` marker, which is what `evidence`
    cites and what a later step re-derives `source` from. A PDF has no markers, so entries here
    carry `sentence_ids: []` and lean entirely on a verbatim `quote`.
  * The XML parse drops the Introduction, Discussion, references and boilerplate. This prompt
    has to ask for that explicitly.

Everything downstream is shared and unmodified. `clean_registry` reduces the answer to the same
seven fields, rounds 2-5 run exactly as they do for an XML paper, and quote verification still
works: assay_verifier.check_quote_verbatim searches the whole document when the source has no
sentence markers to cite (and treats any ids an entry invents there as misattributed), and its `_squash` already folds away the ligatures and line-break
hyphens a PDF text layer carries. What is genuinely lost is check_source_section, which needs
ids to locate an entry and reports "unknown" without them.
"""

import hashlib
import logging

from openai import AsyncOpenAI

from app.agent.assay_extractor import (
    EXTRACTION_SEED,
    AssayExtractionError,
    clean_registry,
    contract_warnings,
    parse_registry_json,
)
from app.agent import assay_trace
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.agent.pdf_direct import _pdf_file_content
from app.config import settings

logger = logging.getLogger(__name__)

PROMPT_FILE = "extract_assays_pdf.txt"


def build_prompt(paper_title: str) -> str:
    """Render extract_assays_pdf.txt for one paper.

    Takes no source text -- unlike assay_extractor.build_prompt, which interpolates the whole
    parsed paper. Here the paper travels as a PDF file part on the request instead, so the
    prompt carries only the title.
    """
    return _load_prompt(PROMPT_FILE).replace("{paper_title}", paper_title)


async def extract_assays_from_pdf(
    pdf_bytes: bytes,
    filename: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    run_label: str = "",
) -> dict:
    """Build a paper's assay registry from its PDF. One LLM call for the whole paper.

    `run_label` names this call's reply in the run's trace, as in assay_extractor.extract_assays.

    One call rather than one per section, for the reason assay_extractor.extract_assays gives:
    extraction has to deduplicate *across* the paper, and a model shown one section at a time
    cannot tell that the Results paraphrase it just read is the Methods entry it read earlier.
    Sending the PDF whole also lets the model use the layout -- heading weight, column flow,
    which caption belongs to which figure -- which is the information a text extract throws away
    and the reason this route reads the PDF rather than a PyMuPDF dump of it.
    """
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_prompt(paper_title)},
            {
                "role": "user",
                "content": [
                    _pdf_file_content(pdf_bytes, filename),
                    {"type": "text",
                     "text": "Build the assay inventory for this paper as instructed."},
                ],
            },
        ],
        temperature=0,
        seed=EXTRACTION_SEED,
        # Keyed on the bytes: the prefix here is the system prompt plus the file part, and the
        # file is what the three extraction calls share.
        prompt_cache_key="assay-pdf-" + hashlib.sha1(pdf_bytes).hexdigest()[:16],
    )

    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    assay_trace.record("extract", run_label, reply=raw, source_kind="pdf",
                       **assay_trace.usage_kw(resp))
    if not raw:
        raise AssayExtractionError("model returned an empty response")

    parsed = parse_registry_json(raw)

    registry = clean_registry(parsed)
    # Empty sentence_ids are the contract here, not a defect -- see contract_warnings.
    for warning in contract_warnings(registry, expect_sentence_ids=False):
        logger.warning("assay extraction (pdf): %s", warning)
    return registry
