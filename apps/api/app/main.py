import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import router as agent_router
from app.database import async_session
from app.plugins import auto_discover

logger = logging.getLogger(__name__)


async def _check_subject_data_view() -> None:
    """Verify subject_data_view exists and doesn't silently drop rows via bad JOINs.

    Picks one study with subjects from biosample and confirms the view returns
    the same subject count. A lower count means an INNER JOIN on an optional
    table (e.g. immune_exposure) is silently excluding subjects.
    """
    async with async_session() as session:
        db_name = (await session.execute(text("SELECT DATABASE()"))).scalar()
        view_exists = (await session.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.VIEWS "
                "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'subject_data_view'"
            ),
            {"db": db_name},
        )).scalar()
        if not view_exists:
            raise RuntimeError(
                "subject_data_view does not exist in the database — "
                "all subject queries will fail. Create or restore the view before starting."
            )

        # Baseline: subjects who have at least one expsample, mirroring the view's
        # INNER JOIN chain (biosample → expsample_2_biosample → expsample → experiment).
        # Subjects with biosamples but no expsamples are intentionally excluded by the view.
        row = (await session.execute(
            text(
                "SELECT b.study_accession, COUNT(DISTINCT b.subject_accession) AS cnt "
                "FROM biosample b "
                "JOIN `subject` s ON s.subject_accession = b.subject_accession "
                "JOIN expsample_2_biosample e2b ON e2b.biosample_accession = b.biosample_accession "
                "JOIN expsample es ON es.expsample_accession = e2b.expsample_accession "
                "JOIN experiment e ON e.experiment_accession = es.experiment_accession "
                "WHERE b.subject_accession IS NOT NULL "
                "GROUP BY b.study_accession "
                "HAVING cnt > 0 "
                "LIMIT 1"
            )
        )).fetchone()

        if not row:
            logger.warning("Startup check: no studies with linked expsamples found — skipping view coverage check")
            return

        study_accession, baseline_count = row[0], int(row[1])
        view_count = int(
            (await session.execute(
                text(
                    "SELECT COUNT(DISTINCT subject_accession) "
                    "FROM subject_data_view WHERE study_accession = :sa"
                ),
                {"sa": study_accession},
            )).scalar() or 0
        )

        if view_count < baseline_count:
            raise RuntimeError(
                f"subject_data_view drops rows: study {study_accession} has {baseline_count} "
                f"subjects reachable via expsamples but only {view_count} in subject_data_view. "
                "Check for INNER JOINs on optional tables (immune_exposure, planned_visit) "
                "in the view definition — they should be LEFT JOINs."
            )

        logger.info(
            "Startup check passed: subject_data_view covers %d/%d subjects for study %s",
            view_count, baseline_count, study_accession,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _check_subject_data_view()
    yield


app = FastAPI(title="AI Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Discover and register plugins
auto_discover()

# Include routers
app.include_router(agent_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
