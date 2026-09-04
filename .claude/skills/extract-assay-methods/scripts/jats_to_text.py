"""Parse a JATS XML paper into the structured plain text this skill extracts from,
using this repo's existing parser (apps/api/app/agent/jats_parser.py).

Output shape:
  ## <section heading>        one block per section, in canonical reading order
                              (abstract -> introduction -> results -> methods ->
                              discussion -> other)
  --- Figures ---             [Label] + Title:/Caption: lines per figure
  --- Tables ---              same, plus a Body: line carrying the table grid

Every sentence is prefixed with a `[S<n>]` marker, numbered continuously across the
whole document, so an extracted value can cite the exact sentence that supports it
instead of a paraphrase. Structural lines (`##` headings, `--- Figures ---`,
`[Figure 1]`) are not sentences and stay unnumbered, but the *content* after
`Title:`/`Caption:`/`Body:` is numbered -- captions and table bodies are quotable
evidence. Pass --no-sentence-ids for the plain text.

Numbering is lossless: deleting every `[S<n>] ` marker restores the parser's output
byte for byte, which is what makes a quote checkable against the source later.

The parser already drops the reference list, supplementary-material containers,
Extended Data figures, and publisher boilerplate (acknowledgments, author
contributions, competing interests, and similar), and truncates to
jats_parser.MAX_PAPER_CHARS.

This only works when run from inside the claim_reprodue_agent repo: it imports
apps/api/app/agent/jats_parser.py. It needs no API key and makes no network call.

Usage:
  python scripts/jats_to_text.py <path/to/paper.xml> [output_path] [--no-sentence-ids]

Writes to stdout if output_path is omitted. Exits non-zero if the file yields no
text, so the caller can fall back to the paper's PDF rather than extract from
nothing.
"""

import itertools
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from app.agent.jats_parser import (
    SENTENCE_SPLIT,
    number_sentences,
    parse_jats_xml,
    strip_sentence_ids,
)

# The sentence-numbering itself now lives in app.agent.jats_parser, imported above. It moved
# there because the HTTP route and the assay passes need it too, and apps/api must not import
# from .claude/skills -- so the shared code sits in the package the skill scripts already
# depend on. number_sentences / strip_sentence_ids / SENTENCE_SPLIT are re-exported here so
# anything importing them from this module keeps working.


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    unknown = flags - {"--no-sentence-ids"}
    if unknown or not args:
        print(
            "Usage: python scripts/jats_to_text.py <path/to/paper.xml> [output_path] "
            "[--no-sentence-ids]",
            file=sys.stderr,
        )
        sys.exit(1)

    in_path = Path(args[0])
    if not in_path.is_file():
        print(f"No such file: {in_path}", file=sys.stderr)
        sys.exit(1)

    try:
        xml_text = in_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Could not read {in_path} as text: {exc}", file=sys.stderr)
        sys.exit(1)

    text = parse_jats_xml(xml_text)
    if not text.strip():
        print(
            f"{in_path} produced no text -- it is empty, not JATS XML, or holds no "
            "parseable sections. Fall back to the paper's PDF.",
            file=sys.stderr,
        )
        sys.exit(1)

    if "--no-sentence-ids" not in flags:
        text = number_sentences(text)

    if len(args) > 1:
        out_path = Path(args[1])
        out_path.write_text(text, encoding="utf-8")
        print(f"{len(text):,} chars -> {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
