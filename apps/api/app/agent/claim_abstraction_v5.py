"""Five-pass whole-document claim abstraction (prompts/claim_abstraction_prompt_v8.md).

The prompt document is the single source of truth: its fenced blocks are the system
prompts, parsed out at call time rather than copied into this module, so editing the
markdown changes the run.

    passes 1-3   per paper   prose -> draft, draft+legends -> claims, provenance audit
    passes 4-5   per paper   abstract coverage audit, claim-set de-duplication

Passes 1 and 2 are self-consistency sampled: `runs` samples at temperature 1.0, keep the
sample whose claim count is the mode. Passes 3-5 are single deterministic calls.

The paper arrives from `jats_parser.parse_jats_xml` as two blocks — its Abstract, Results
and Methods prose, and every figure/table legend — so pass 1 drafts without seeing a legend
and pass 2 reconciles against them. `split_document` makes that cut.

This module previously split each paper into one panel per <fig>/<table-wrap> and looped the
passes over them. That was dropped: panels were paired to prose by <xref> alone, which left
127 of the 30-paper corpus's 494 Results paragraphs (26%) attached to no panel and therefore
read by no pass; findings comparing two figures were split across two runs and survived in
neither; and a paper cost ~79 calls against 13 here. The measurement is in
data/experiments/sdy1260_prompt_ab/comparison.md.

XML only. Papers PMC will not serve as full text have no path here yet.
"""

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.agent.claim_parser import CLAIM_TYPES_PLACEHOLDER, _load_prompt, _strip_fences
from app.agent.jats_parser import _BANNER, _HEADING_BUCKET, parse_jats_xml


#: The only prompt document. v8 reads a paper whole: the `other-panel` demotion reason is
#: retired (nothing else would pick up what it drops), pass 2 selects each claim's legend out
#: of all of them, and pass 1 is told its text is complete rather than an excerpt.
DOCUMENT_PROMPT_FILE = "claim_abstraction_prompt_v8.md"

#: The shared claim_type vocabulary, substituted per block — see load_v5_prompts.
CLAIM_TYPES_FILE = "claim_types.txt"

SAMPLED_TEMPERATURE = 1.0

#: The fields claims.json persists, in the order they are written. Everything else a pass
#: produces — the contrast block, `unspecified`, pass 2's `scope_changes`/`method_added`,
#: pass 3's `provenance_audit` — is extraction scaffolding that no downstream stage reads,
#: and together it was ~53% of the file. It is dropped at the WRITE, never earlier: pass 3
#: attaches its verdict onto each claim and pass 5 reads `polarity`, `contrast`, `targets`
#: and `timepoints` off the in-memory set, so the full shape has to survive until
#: `abstract_claims_from_document` returns.
CLAIMS_OUTPUT_FIELDS = ("claim", "claim_type", "assay_method_in_paper", "sources")

#: Output key -> the key the model actually emits. The extraction passes name the field
#: `assay`, but claims.json publishes it as `assay_method_in_paper` to say what it holds:
#: the method as the paper words it, not an OBI-mapped or registry-resolved identifier.
#: Renaming at the write site keeps passes 2-5, which read `claim["assay"]` internally,
#: working off the name they were written against.
CLAIMS_OUTPUT_SOURCE_KEYS = {"assay_method_in_paper": "assay"}

# A 429 late in a pass discards the samples already paid for. Cap in-flight calls instead.
# Less load-bearing than when a paper was ~79 calls, but the sampled passes still fan out.
MAX_CONCURRENT_CALLS = 8

_HEADING_KEYS = {
    "SHARED PREAMBLE": "preamble",
    "PASS 1": "pass1",
    "PASS 2": "pass2",
    "PASS 3": "pass3",
    "PASS 4": "pass4",
    "PASS 5": "pass5",
}


def load_v5_prompts(filename: str = DOCUMENT_PROMPT_FILE) -> dict[str, str]:
    """Return {preamble, pass1..pass5} — the first fenced block under each `## ` heading.

    The claim_type vocabulary is substituted into each block AFTER the split, never before:
    claim_types.txt contains its own ``` fence around the precedence ladder, which would
    close the enclosing block early and silently truncate the preamble at that point. A
    document with no placeholder is used as-is — v5 carries its vocabulary inline.

    Raises if a heading or its block is missing: a silently absent pass role would still
    produce a runnable prompt (the preamble alone), and the run would look successful.
    """
    text = _load_prompt(filename)
    blocks: dict[str, str] = {}
    current: str | None = None
    fence: list[str] | None = None

    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = next((k for h, k in _HEADING_KEYS.items() if heading.startswith(h)), None)
            fence = None
            continue
        if current is None or current in blocks:
            continue
        if line.startswith("```"):
            if fence is None:
                fence = []
            else:
                blocks[current] = "\n".join(fence).strip()
                fence = None
            continue
        if fence is not None:
            fence.append(line)

    missing = [k for k in _HEADING_KEYS.values() if k not in blocks]
    if missing:
        raise ValueError(f"{filename}: no fenced prompt block for {', '.join(missing)}")

    if CLAIM_TYPES_PLACEHOLDER in text:
        vocabulary = _load_prompt(CLAIM_TYPES_FILE)
        blocks = {k: v.replace(CLAIM_TYPES_PLACEHOLDER, vocabulary) for k, v in blocks.items()}
        unresolved = [k for k, v in blocks.items() if CLAIM_TYPES_PLACEHOLDER in v]
        if unresolved:
            raise ValueError(f"{filename}: {CLAIM_TYPES_PLACEHOLDER} survived substitution")
    return blocks


def system_prompts(blocks: dict[str, str]) -> dict[str, str]:
    """Assemble the per-pass system prompts. Passes 1-2 carry the shared preamble; the
    audit passes (3-5) deliberately do not — they judge claims, they do not extract."""
    return {
        "pass1": blocks["preamble"] + "\n\n" + blocks["pass1"],
        "pass2": blocks["preamble"] + "\n\n" + blocks["pass2"],
        "pass3": blocks["pass3"],
        "pass4": blocks["pass4"],
        "pass5": blocks["pass5"],
    }


# ── JATS -> one document ──────────────────────────────────────────────────────


@dataclass
class PaperDocument:
    """A whole paper as two blocks: its prose, and every figure/table legend.

    The split is what lets the document path keep pass 1's legend blinding without panels.
    `prose` is the Abstract, Results and Methods as `parse_jats_xml` leaves them -- headings,
    document order and all -- and `panels_block` is the `--- Figures ---`/`--- Tables ---`
    banners and everything under them.
    """

    prose: str
    panels_block: str
    abstract: str


def split_document(xml_text: str) -> PaperDocument:
    """Split a JATS article into (prose, all legends, abstract) via `parse_jats_xml`.

`parse_jats_xml` keeps every paragraph in document order regardless of what it
    cites, and drops the reference list, supplementary material, Extended Data, publisher
    boilerplate, Introduction and Discussion instead. That is the property this path is built
    on: the panel splitter it replaced paired prose to a figure by `<xref>` alone and left 26%
    of the corpus's Results paragraphs attached to nothing, read by no pass.

    The cut is the first `--- ` banner. Everything above it is prose and everything from it
    down is legends -- `parse_jats_xml` emits the figure and table blocks last and in that
    order, so one cut separates them from the body whichever blocks a paper has.
    """
    text = parse_jats_xml(xml_text)
    lines = text.split("\n")

    cut = next((i for i, line in enumerate(lines) if _BANNER.match(line)), None)
    if cut is None:
        # Degrading to one block here would send the legends into pass 1 and silently turn a
        # blinded two-pass run into an unblinded one-pass run -- same claims.json, same call
        # count, no error, and the sole reason for pass 2 gone. Refuse instead.
        raise ValueError(
            "parse_jats_xml output has no '--- Figures ---' or '--- Tables ---' banner: "
            "the paper's legends cannot be withheld from pass 1. Check the XML has "
            "<fig>/<table-wrap> nodes."
        )

    return PaperDocument(
        prose="\n".join(lines[:cut]).strip(),
        panels_block="\n".join(lines[cut:]).strip(),
        abstract=_abstract_of(lines[:cut]),
    )


def _abstract_of(prose_lines: list[str]) -> str:
    """The text under the `## ... [abstract]` heading, for pass 4's coverage audit.

    Read off the bucket tag `parse_jats_xml` writes into each heading rather than by matching
    the word "Abstract": the tag already resolved the section, and a structured abstract
    carries its own `Background/Methods/Results` sub-headings, so in document order its
    "Results" comes first and a title match would land on a 600-character summary citing no
    figures.
    """
    out: list[str] = []
    collecting = False
    for line in prose_lines:
        heading = _HEADING_BUCKET.match(line)
        if heading:
            collecting = heading.group(1) == "abstract"
            continue
        if collecting:
            out.append(line)
    return "\n".join(out).strip()


# ── token accounting ──────────────────────────────────────────────────────────


@dataclass
class UsageTracker:
    """Per-pass token totals across a run.

    `cached` is the prefix-cache hit portion of `prompt` (already counted in it, billed at
    a discount) — reported separately so the caching change above is visible rather than
    assumed. Mutation happens between awaits on one event loop, so no lock is needed.
    """

    by_pass: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, label: str, usage) -> None:
        bucket = self.by_pass.setdefault(
            label, {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "total": 0}
        )
        bucket["calls"] += 1
        if usage is None:
            return
        details = getattr(usage, "prompt_tokens_details", None)
        bucket["prompt"] += getattr(usage, "prompt_tokens", 0) or 0
        bucket["cached"] += getattr(details, "cached_tokens", 0) or 0
        bucket["completion"] += getattr(usage, "completion_tokens", 0) or 0
        bucket["total"] += getattr(usage, "total_tokens", 0) or 0

    def summary(self) -> dict:
        totals = {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "total": 0}
        for bucket in self.by_pass.values():
            for key in totals:
                totals[key] += bucket[key]
        return {"by_pass": dict(sorted(self.by_pass.items())), "total": totals}


# ── LLM passes ────────────────────────────────────────────────────────────────


async def _call_json(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    temperature: float,
    tracker: UsageTracker | None = None,
    label: str = "",
    semaphore: asyncio.Semaphore | None = None,
) -> dict:
    async def _go():
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        )
        # Record before parsing: a call whose JSON is malformed still cost its tokens.
        if tracker is not None:
            tracker.record(label, getattr(resp, "usage", None))
        return json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))

    if semaphore is None:
        return await _go()
    async with semaphore:
        return await _go()


def pick_modal(results: list[dict]) -> tuple[dict, dict, bool]:
    """Pick the sample whose claim count is the mode.

    Returns (sample, {count: n_samples}, decisive). Ties break toward the count seen first,
    and within a count toward the first sample — an arbitrary but reproducible choice,
    recorded in the returned tally either way.

    `decisive` is False when the winning count beat its runner-up by fewer than two samples.
    "More than half" is the wrong bar here: SDY1260 Figure 2 returned {2: 3, 10: 2}, a
    strict majority that nonetheless let a one-sample swing decide between 2 claims and 10.
    The mode is still used; the flag records that the count was not determinate.
    """
    if not results:
        raise ValueError("no successful samples to choose from")
    counts = [len(r.get("claims", [])) for r in results]
    tally = Counter(counts)
    ranked = sorted(tally.values(), reverse=True)
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else 0
    modal_count = next(c for c in counts if tally[c] == best)
    chosen = next(r for r in results if len(r.get("claims", [])) == modal_count)
    return chosen, dict(sorted(tally.items())), best - runner_up >= 2


async def _sampled_pass(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    runs: int,
    tracker: UsageTracker | None = None,
    label: str = "",
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[dict, dict, list[str], bool]:
    """Run `runs` samples concurrently and keep the modal-claim-count one.

    A sample that comes back unparseable is dropped rather than aborting the pass: the
    mode is taken over whatever parsed, and the failures are returned for the run record.
    """
    temperature = SAMPLED_TEMPERATURE if runs > 1 else 0
    settled = await asyncio.gather(
        *(
            _call_json(client, model, system, user, temperature, tracker, label, semaphore)
            for _ in range(runs)
        ),
        return_exceptions=True,
    )
    parsed = [r for r in settled if not isinstance(r, BaseException)]
    errors = [f"{type(r).__name__}: {r}" for r in settled if isinstance(r, BaseException)]
    if not parsed:
        raise RuntimeError(f"all {runs} samples failed: {'; '.join(errors)}")
    chosen, tally, decisive = pick_modal(parsed)
    return chosen, tally, errors, decisive


async def run_document(
    client: AsyncOpenAI,
    model: str,
    prompts: dict[str, str],
    doc: PaperDocument,
    runs: int = 5,
    tracker: UsageTracker | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> dict:
    """Passes 1-3 over a whole paper. Returns {claims, not_a_claim, verdicts, run_record}.

    Pass 1 sees `doc.prose` and never a legend; passes 2 and 3 see `doc.panels_block`, which
    holds all of them. Methods needs no separate argument -- `parse_jats_xml` leaves it in the
    prose under its own heading, and the v8 preamble scopes it to the provenance fields there.
    """
    pass1_user = f"PAPER TEXT:\n{doc.prose}"
    draft, tally1, errors1, decisive1 = await _sampled_pass(
        client, model, prompts["pass1"], pass1_user, runs, tracker, "pass1", semaphore
    )

    pass2_user = (
        "DRAFT CLAIMS (from the paper text alone):\n"
        f"{json.dumps(draft, indent=2, ensure_ascii=False)}\n\n"
        f"FIGURE AND TABLE LEGENDS (not seen in pass 1):\n{doc.panels_block}"
    )
    final, tally2, errors2, decisive2 = await _sampled_pass(
        client, model, prompts["pass2"], pass2_user, runs, tracker, "pass2", semaphore
    )

    claims = final.get("claims", [])
    not_a_claim = final.get("not_a_claim", [])

    verdicts: list = []
    audit_error = None
    if claims:
        pass3_user = (
            f"CLAIMS:\n{json.dumps(claims, indent=2, ensure_ascii=False)}\n\n"
            f"FIGURE AND TABLE LEGENDS:\n{doc.panels_block}"
        )
        try:
            audit = await _call_json(
                client, model, prompts["pass3"], pass3_user, 0, tracker, "pass3", semaphore
            )
            verdicts = audit.get("verdicts", [])
        except Exception as exc:  # the claims are already extracted; keep them
            audit_error = f"{type(exc).__name__}: {exc}"

    return {
        "claims": claims,
        "not_a_claim": not_a_claim,
        "verdicts": verdicts,
        "run_record": {
            "scope": "document",
            "prose_chars": len(doc.prose),
            "legends_chars": len(doc.panels_block),
            "pass1_claim_counts": tally1,
            "pass2_claim_counts": tally2,
            # False means the winning claim count beat its runner-up by fewer than two
            # samples, so the count turned on a near-tie rather than on agreement. It carries
            # weight: a single near-tie decides the whole paper's claim count.
            "pass1_decisive": decisive1,
            "pass2_decisive": decisive2,
            "draft_claims": len(draft.get("claims", [])),
            "final_claims": len(claims),
            "sample_errors": errors1 + errors2,
            "audit_error": audit_error,
        },
    }


def apply_verdicts(claims: list[dict], verdicts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Attach each pass-3 verdict to its claim and act on it.

    Only `demote_to_not_a_claim` is mechanical — it moves the claim out. `narrow_to_
    data_derived_part` needs a rewrite the audit pass is explicitly forbidden to make, so
    the claim stays and carries the verdict as a flag for a human.
    """
    by_text = {v.get("claim", ""): v for v in verdicts}
    kept: list[dict] = []
    demoted: list[dict] = []
    for claim in claims:
        verdict = by_text.get(claim.get("claim", ""))
        if verdict:
            claim["provenance_audit"] = verdict
        if verdict and verdict.get("action") == "demote_to_not_a_claim":
            demoted.append(
                {
                    "text": claim.get("claim", ""),
                    "reason": "external-import",
                    "identifiers": claim.get("targets", []),
                    "verifiable_alternative": None,
                    "from_provenance_audit": verdict,
                }
            )
            continue
        kept.append(claim)
    return kept, demoted


async def run_coverage_audit(
    client: AsyncOpenAI,
    model: str,
    prompts: dict[str, str],
    abstract: str,
    claims: dict,
    tracker: UsageTracker | None = None,
) -> dict:
    """Pass 4 — abstract recall check over the pooled claim set."""
    listing = {k: v.get("claim", "") for k, v in claims.items()}
    user = (
        f"ABSTRACT:\n{abstract}\n\n"
        f"EXTRACTED CLAIMS:\n{json.dumps(listing, indent=2, ensure_ascii=False)}"
    )
    return await _call_json(client, model, prompts["pass4"], user, 0, tracker, "pass4")


def project_claims(claims: dict) -> dict:
    """Reduce each claim to CLAIMS_OUTPUT_FIELDS, for writing to claims.json.

    Claim key order is preserved, and a claim that never got one of the three fields still
    carries the key with a null — a downstream reader can then index every entry the same
    way instead of testing for presence.

    A field the model emits under a different name is remapped via
    CLAIMS_OUTPUT_SOURCE_KEYS rather than renamed upstream, so the passes that read it
    internally are untouched.
    """
    return {
        key: {
            field: claim.get(CLAIMS_OUTPUT_SOURCE_KEYS.get(field, field))
            for field in CLAIMS_OUTPUT_FIELDS
        }
        for key, claim in claims.items()
    }


async def run_dedup_audit(
    client: AsyncOpenAI,
    model: str,
    prompts: dict[str, str],
    claims: dict,
    tracker: UsageTracker | None = None,
) -> dict:
    """Pass 5 — claim-set reconciliation. Reports merges and naming normalisations; it
    never applies either.

    `polarity` and `sample_type` are in the listing because the pass reasons about both: a
    positive claim and its null-polarity counterpart must never be merged, and sample_type
    is one of the two fields whose spelling it normalises across the set.
    """
    listing = {
        k: {
            "claim": v.get("claim", ""),
            "claim_type": v.get("claim_type"),
            "polarity": v.get("polarity"),
            "assay": v.get("assay"),
            "sample_type": v.get("sample_type"),
            "targets": v.get("targets", []),
            "timepoints": v.get("timepoints", []),
            "contrast": v.get("contrast"),
        }
        for k, v in claims.items()
    }
    user = f"CLAIM SET:\n{json.dumps(listing, indent=2, ensure_ascii=False)}"
    return await _call_json(client, model, prompts["pass5"], user, 0, tracker, "pass5")


async def abstract_claims_from_document(
    xml_text: str,
    client: AsyncOpenAI,
    model: str,
    runs: int = 5,
    prompt_file: str = DOCUMENT_PROMPT_FILE,
) -> tuple[dict, dict]:
    """Run all five passes over a paper. Returns (claims, audit).

    `claims` is keyed claim_1..N -- the shape the rest of the pipeline reads (claim_filter,
    classify_groups). `audit` holds everything the passes reported that is not itself a claim:
    demotions, provenance verdicts, coverage, proposed merges, and the sampling record.

    13 calls: 2x`runs` sampled extraction passes, 1 provenance audit, and passes 4-5 over the
    pooled set.
    """
    prompts = system_prompts(load_v5_prompts(prompt_file))
    doc = split_document(xml_text)

    tracker = UsageTracker()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    result = await run_document(client, model, prompts, doc, runs, tracker, semaphore)

    kept, demoted = apply_verdicts(result["claims"], result["verdicts"])
    claims = {f"claim_{i}": claim for i, claim in enumerate(kept, start=1)}
    not_a_claim = result["not_a_claim"] + demoted
    result["run_record"]["demoted_by_audit"] = len(demoted)

    coverage, dedup = {}, {}
    if claims:
        coverage, dedup = await asyncio.gather(
            run_coverage_audit(client, model, prompts, doc.abstract, claims, tracker),
            run_dedup_audit(client, model, prompts, claims, tracker),
        )

    audit = {
        "not_a_claim": not_a_claim,
        "abstract_coverage": coverage,
        "claim_set_dedup": dedup,
        "document": result["run_record"],
        "token_usage": tracker.summary(),
        "settings": {"model": model, "runs_per_pass": runs, "prompt_file": prompt_file},
    }
    return claims, audit
