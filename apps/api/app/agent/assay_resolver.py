"""Resolve assay method labels for a study from the ImmPort experiment table."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_study_assay_methods(session: AsyncSession, study_accession: str) -> list[str]:
    """Return study assay labels. If the same measurement_technique appears more than
    once, use the experiment name column to distinguish each row instead.
    """
    result = await session.execute(
        text(
            "SELECT measurement_technique, name "
            "FROM experiment "
            "WHERE study_accession = :sa AND measurement_technique IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    rows = result.fetchall()

    # Count occurrences of each measurement_technique
    mt_counts: dict[str, int] = {}
    for mt, _ in rows:
        key = (mt or "").strip().lower()
        if key:
            mt_counts[key] = mt_counts.get(key, 0) + 1

    assay_methods: list[str] = []
    seen: set[str] = set()
    for measurement_technique, name in rows:
        mt = (measurement_technique or "").strip()
        nm = (name or "").strip()
        if not mt:
            continue
        use_name = nm and (mt.lower() == "other" or mt_counts.get(mt.lower(), 1) > 1)
        assay = nm if use_name else mt
        if assay not in seen:
            seen.add(assay)
            assay_methods.append(assay)
    return assay_methods
