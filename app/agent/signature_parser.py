import json


def parse_signature(file_content: str) -> tuple[list[dict], str | None]:
    """Parse a signature JSON and extract paper_description from each participant_group.

    Args:
        file_content: Raw JSON string (from file_reader.read_file()).

    Returns:
        Tuple of (groups, study_accession) where groups is a list of dicts:
        [{"group_name": "...", "group_id": 0, "descriptions": ["...", ...]}]
        and study_accession is the ImmPort study ID (e.g. "SDY1669") or None.
    """
    data = json.loads(file_content)
    groups = data.get("participant_group", [])

    # Extract study_accession from the repository list
    study_accession = None
    repositories = data.get("repository", [])
    if repositories:
        study_accession = repositories[0].get("repository_id")

    results = []
    for group in groups:
        descriptions = group.get("paper_description", [])
        if descriptions:
            results.append(
                {
                    "group_name": group.get("name", ""),
                    "group_id": group.get("id", 0),
                    "descriptions": descriptions,
                }
            )
    return results, study_accession


def format_descriptions_for_llm(groups: list[dict]) -> str:
    """Format extracted participant group descriptions into a prompt-ready string.

    Args:
        groups: Output of parse_signature().

    Returns:
        A formatted string suitable for LLM analysis.
    """
    if not groups:
        return ""

    parts = []
    for group in groups:
        header = f"Participant Group {group['group_id']}: {group['group_name']}"
        descs = "\n".join(f"  - {d}" for d in group["descriptions"])
        parts.append(f"{header}\n{descs}")

    return "\n\n".join(parts)
