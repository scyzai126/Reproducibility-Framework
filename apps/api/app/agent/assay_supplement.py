"""The supplement workflow's own parts: one document of main text + supplement, and its prompt.

The main-text workflow (assay_extractor + prompts/extract_assays.txt) is not touched by anything
here. This module builds what the supplement workflow feeds the same six-round chain instead:

- `combine` appends a paper's rendered supplement (paper_supplements.render, stored as
  `data/supplements/<SDY>_<pmid>/supplement.txt`) to the parsed main text and numbers the whole
  once. The main text comes first and one counter numbers both, so every main-text `[S<n>]` is
  the id it has in the main-text workflow, and a supplement sentence is any id past the last of
  them. The supplement sits under a `--- Supplement ---` banner in `## <file>: <heading>
  [methods|other]` blocks -- shapes jats_parser.sentence_sections and number_sentences already
  read, which is why the verifier, the quote check and the derived `source` need no change.
- `extract_assays_with_supplement` is round 1 for that document, on
  prompts/extract_assays_supplement.txt.
- `mark_supplement_evidence` records, from the sentence ids and by code, whether each entry's
  quote came from the supplement.
"""

import logging
import re
from pathlib import Path

from openai import AsyncOpenAI

from app.agent import assay_trace, paper_supplements
from app.agent.assay_extractor import (
    EXTRACTION_SEED,
    MERGED_FIELD,
    MIN_METHODS_CHARS,
    AssayExtractionError,
    clean_registry,
    contract_warnings,
    paper_cache_key,
    paper_names,
    parse_registry_json,
)
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.agent.jats_parser import SENTENCE_MARKER, number_sentences, strip_sentence_ids
from app.config import settings

logger = logging.getLogger(__name__)

PROMPT_FILE = "extract_assays_supplement.txt"

#: The folder under data/benchmark_agent_assays/ this workflow writes to. Its own, so a
#: main-text registry is never read or overwritten by a supplement run.
RESULT_VERSION = "assay_supplement_v1"

#: Opens the supplement in the combined document. A `--- ` line is structural to
#: number_sentences (no marker) and a banner to sentence_sections.
SUPPLEMENT_BANNER = "--- Supplement ---"

#: How much of a supplement's non-methods text (figure legends, table notes) rides along.
#: `[methods]` blocks are never cut by this -- they are the reason the supplement is read, and
#: supplement.txt already holds them to the main text's own cap. The rest fills what is left of
#: this budget, in the file's order, because the heading rule that finds supplementary methods
#: can miss one and a legend is where a supplement-only assay is otherwise named.
SUPPLEMENT_MAX_CHARS = 40_000

#: What trace and result call this route. The chain itself still runs it as `xml`: the document
#: carries sentence markers and section tags, which is all that kind means to rounds 2-6.
SOURCE_KIND = "xml+supplement"

NO_METHODS_NOTE = (
    "STRUCTURE 3 APPLIES: neither the paper nor its supplement has a [methods] section. Build "
    "the inventory from the abstract, the main text, the captions and the supplement text, as "
    "structure 3 describes.\n\n"
)

_BLOCK_HEAD = re.compile(r"^## .*\[(methods|other)\]\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def supplement_text_path(pubmed_id: str, study_accession: str) -> Path:
    """Where download_paper_supplements.py leaves a paper's rendered supplement."""
    name = f"{(study_accession or '').strip()}_{(pubmed_id or '').strip()}"
    return paper_supplements.SUPPLEMENT_ROOT / name / "supplement.txt"


def _blocks(rendered: str) -> list[tuple[str, str, str]]:
    """`[(heading line, bucket, body)]` of a rendered supplement, markers removed."""
    blocks: list[tuple[str, str, list[str]]] = []
    for line in strip_sentence_ids(rendered).split("\n"):
        head = _BLOCK_HEAD.match(line)
        if head:
            blocks.append((line, head.group(1), []))
        elif blocks:
            blocks[-1][2].append(line)
    return [(head, bucket, "\n".join(body).strip()) for head, bucket, body in blocks]


def select_blocks(rendered: str, max_chars: int = SUPPLEMENT_MAX_CHARS) -> str:
    """The part of a rendered supplement the chain reads, unnumbered.

    Every `[methods]` block, whole, then `[other]` blocks while they fit in what `max_chars`
    leaves. An `[other]` block that would cross the budget is cut at its last sentence end
    inside it and is the last block; one with no room for a sentence is left out.
    """
    blocks = [block for block in _blocks(rendered) if block[2]]
    kept = [(head, body) for head, bucket, body in blocks if bucket == "methods"]
    used = sum(len(head) + len(body) for head, body in kept)
    for head, bucket, body in blocks:
        if bucket != "other":
            continue
        room = max_chars - used - len(head)
        if room <= 0:
            break
        if len(body) > room:
            ends = [m.start() for m in _SENTENCE_END.finditer(body, 0, room)]
            if not ends:
                break
            kept.append((head, body[:ends[-1]]))
            break
        kept.append((head, body))
        used += len(head) + len(body)
    return "\n\n".join(f"{head}\n{body}" for head, body in kept)


def combine(main_numbered: str, supplement_rendered: str,
            max_chars: int = SUPPLEMENT_MAX_CHARS) -> tuple[str, int | None]:
    """(combined numbered text, id number of the first supplement sentence).

    `main_numbered` is assay_service.paper_source_text's text, `supplement_rendered` the
    contents of supplement.txt. Both arrive numbered; the markers are stripped (the exact
    inverse of number_sentences) and the joined document is numbered once, so the main text
    keeps its ids and the supplement continues them. The second value is None when the
    supplement contributed no sentence -- an empty file, or nothing but headings.
    """
    supplement = select_blocks(supplement_rendered, max_chars)
    if not supplement:
        return main_numbered, None
    main = strip_sentence_ids(main_numbered).rstrip("\n")
    combined = number_sentences(f"{main}\n\n{SUPPLEMENT_BANNER}\n\n{supplement}")
    head, _, tail = combined.partition(f"\n{SUPPLEMENT_BANNER}\n")
    if not SENTENCE_MARKER.search(tail):
        return main_numbered, None
    return combined, len(SENTENCE_MARKER.findall(head)) + 1


def main_text(source_text: str) -> str:
    """The combined document up to the supplement banner: the main text as it was numbered."""
    return source_text.partition(f"\n{SUPPLEMENT_BANNER}\n")[0].rstrip("\n")


def methods_chars(source_text: str) -> int:
    """Prose under `[methods]` headings anywhere in the document, the supplement included.

    assay_extractor.methods_chars stops at the figure block, which is where the main text's
    sections end; here the supplement's sections come after it. A banner line closes the
    section above it, so captions are not counted.
    """
    total = 0
    in_methods = False
    for line in source_text.splitlines():
        if line.startswith("## "):
            in_methods = "[methods]" in line
        elif line.startswith("--- "):
            in_methods = False
        elif in_methods:
            total += len(SENTENCE_MARKER.sub("", line).strip())
    return total


def has_methods_section(source_text: str) -> bool:
    """Whether main text and supplement together carry a Methods section worth reading."""
    return methods_chars(source_text) >= MIN_METHODS_CHARS


def build_prompt(source_text: str, paper_title: str) -> str:
    """Render extract_assays_supplement.txt for one combined document."""
    text = source_text if has_methods_section(source_text) else NO_METHODS_NOTE + source_text
    return (
        _load_prompt(PROMPT_FILE)
        .replace("{paper_title}", paper_title)
        .replace("{source_text}", text)
    )


async def extract_assays_with_supplement(
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    run_label: str = "",
) -> dict:
    """Round 1 over main text + supplement. One call; same contract as extract_assays.

    The request has the shape assay_extractor.extract_assays sends -- one user message, the
    same seed, the paper's cache key -- so the prefix cache and the Claude adapter treat both
    workflows alike. Only the prompt file and the document differ.
    """
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": build_prompt(source_text, paper_title)}],
        temperature=0,
        seed=EXTRACTION_SEED,
        prompt_cache_key=paper_cache_key(source_text),
    )
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    assay_trace.record("extract", run_label, reply=raw, source_kind=SOURCE_KIND,
                       **assay_trace.usage_kw(resp))
    if not raw:
        raise AssayExtractionError("model returned an empty response")

    registry = clean_registry(parse_registry_json(raw))
    # As in extract_assays: ids and `source` are derived after this returns.
    for warning in contract_warnings(registry, expect_sentence_ids=False):
        logger.warning("assay extraction (supplement): %s", warning)
    return registry


def in_supplement(sentence_ids, first_supplement_id: int | None) -> bool | None:
    """Whether a quote placed at `sentence_ids` lies in the supplement. None when unplaced."""
    numbers = [int(sid[1:]) for sid in (sentence_ids or [])
               if isinstance(sid, str) and sid[1:].isdigit()]
    if not numbers:
        return None
    return first_supplement_id is not None and min(numbers) >= first_supplement_id


def mark_supplement_evidence(assays: dict, first_supplement_id: int | None) -> None:
    """Set `evidence.in_supplement` on every entry and on each folded member's evidence.

    Derived from the sentence ids, never asked of the model: true when the whole quote sits
    past the main text, false when any of it is main text, null when the quote was not placed.
    """
    for entry in (assays or {}).values():
        if not isinstance(entry, dict):
            continue
        for holder in [entry, *(entry.get(MERGED_FIELD) or [])]:
            evidence = holder.get("evidence") if isinstance(holder, dict) else None
            if isinstance(evidence, dict):
                evidence["in_supplement"] = in_supplement(
                    evidence.get("sentence_ids"), first_supplement_id)


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def supplement_entries(assays: dict, source_text: str) -> list[dict]:
    """Entries whose evidence is the supplement's: `[{"key", "named_in_main_text"}]`.

    An entry is listed when its own quote and every folded member's quote are in the
    supplement. `named_in_main_text` says whether any of its paper wordings or aliases also
    occurs in the main text -- false is an assay the main text never names, true is one the
    supplement merely describes better. A string search, free.
    """
    main = _fold(strip_sentence_ids(main_text(source_text)))
    listed = []
    for key, entry in (assays or {}).items():
        if not isinstance(entry, dict):
            continue
        flags = [holder["evidence"].get("in_supplement")
                 for holder in [entry, *(entry.get(MERGED_FIELD) or [])]
                 if isinstance(holder, dict) and isinstance(holder.get("evidence"), dict)]
        if not flags or not all(flag is True for flag in flags):
            continue
        wordings = [*paper_names(entry), *(entry.get("aliases") or [])]
        named = any(_fold(w) in main for w in wordings if isinstance(w, str) and w.strip())
        listed.append({"key": key, "named_in_main_text": named})
    return listed
