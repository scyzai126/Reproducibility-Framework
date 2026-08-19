"""Parse a JATS XML paper into the structured plain text this skill extracts from,
using this repo's existing parser (apps/api/app/agent/jats_parser.py).

Output shape:
  ## <section heading>        one block per section, in canonical reading order
                              (abstract -> introduction -> results -> methods ->
                              discussion -> other)
  --- Figures ---             [Label] + Title:/Caption: lines per figure
  --- Tables ---              same, plus a Body: line carrying the table grid

The parser already drops the reference list, supplementary-material containers,
Extended Data figures, and publisher boilerplate (acknowledgments, author
contributions, competing interests, and similar), and truncates to
jats_parser.MAX_PAPER_CHARS.

This only works when run from inside the claim_reprodue_agent repo: it imports
apps/api/app/agent/jats_parser.py. It needs no API key and makes no network call.

Usage:
  python scripts/jats_to_text.py <path/to/paper.xml> [output_path]

Writes to stdout if output_path is omitted. Exits non-zero if the file yields no
text, so the caller can fall back to the paper's PDF rather than extract from
nothing.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from app.agent.jats_parser import parse_jats_xml


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/jats_to_text.py <path/to/paper.xml> [output_path]",
              file=sys.stderr)
        sys.exit(1)

    in_path = Path(sys.argv[1])
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

    if len(sys.argv) > 2:
        out_path = Path(sys.argv[2])
        out_path.write_text(text, encoding="utf-8")
        print(f"{len(text):,} chars -> {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
