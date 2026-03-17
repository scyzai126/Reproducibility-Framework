import json


def parse_claims(file_content: str) -> tuple[list[dict], str | None]:
    """Parse a claims-based JSON and extract claims + study_accession.

    Returns:
        Tuple of (claims, study_accession) where claims is the raw list of
        claim dicts: [{"id": 0, "source": {...}, "claim_text": "..."}]
    """
    data = json.loads(file_content)
    study_accession = None
    repositories = data.get("repository", [])
    if repositories:
        study_accession = repositories[0].get("repository_id")
    return data.get("claims", []), study_accession


def format_claim_for_llm(claim: dict, study_accession: str | None) -> str:
    """Format a single claim dict into a prompt-ready string."""
    source = claim.get("source", {})
    source_str = f"{source.get('type', '')} {source.get('value', '')}".strip()
    lines = [f"Claim {claim['id']} ({source_str}):"]
    lines.append(claim.get("claim_text", ""))
    if study_accession:
        lines.append(f"Study: {study_accession}")
    return "\n".join(lines)


def format_claims_batch_for_llm(claims: list[dict], study_accession: str | None) -> str:
    """Format all claims into a single batch prompt string for one LLM call."""
    return "\n\n".join(format_claim_for_llm(c, study_accession) for c in claims)


def parse_signature(file_content: str) -> tuple[list[dict], str | None]:
    """Parse a signature JSON and extract paper_description from each participant_group.

    Args:
        file_content: Raw JSON string (from file_reader.read_file()).

    Returns:
        Tuple of (groups, study_accession) where groups is a list of dicts:
        [{"group_id": 0, "descriptions": ["...", ...]}]
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
                    "group_id": group.get("id", 0),
                    "descriptions": descriptions,
                }
            )
    return results, study_accession


def format_descriptions_for_llm(groups: list[dict], study_accession: str | None = None) -> str:
    """Format extracted participant group descriptions into a prompt-ready string.

    Args:
        groups: Output of parse_signature().
        study_accession: ImmPort study ID to append to each group block.

    Returns:
        A formatted string suitable for LLM analysis.
    """
    if not groups:
        return ""

    parts = []
    for group in groups:
        header = f"Participant Group {group['group_id']}:"
        descs = "\n".join(f"  - {d}" for d in group["descriptions"])
        block = f"{header}\n{descs}"
        if study_accession:
            block += f"\n  - study: {study_accession}"
        parts.append(block)

    return "\n\n".join(parts)
