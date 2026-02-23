import logging
from pathlib import Path

import httpx
from sqlalchemy import text

from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)


class StudySyncer:
    """Downloads and imports an ImmPort study MySQL dump if not already in the local DB."""

    async def ensure_study_downloaded(self, study_accession: str) -> dict:
        """Check if study exists locally; if not, download and import the MySQL dump zip.

        Returns a status dict with keys:
          action  — "skipped" | "imported"
          reason  — "already_present" (when skipped)
          zip_path / extract_dir — paths (when imported)
        """
        if await self._study_exists(study_accession):
            logger.info(
                "Study %s already present in local DB; skipping download.",
                study_accession,
            )
            return {"action": "skipped", "reason": "already_present"}

        logger.info(
            "Study %s not found locally — downloading from ImmPort.", study_accession
        )
        if not settings.IMMPORT_USERNAME or not settings.IMMPORT_PASSWORD:
            raise RuntimeError(
                f"Study {study_accession} is not in the local database and "
                "IMMPORT_USERNAME / IMMPORT_PASSWORD are not configured. "
                "Set them in .env to enable automatic study download."
            )

        token = await self._get_auth_token()
        file_uuid = await self._get_file_uuid(study_accession, token)
        zip_path = await self._download_zip(file_uuid, token, study_accession)
        logger.info("Downloaded study zip to %s", zip_path)

        # Unzip and import into local MySQL
        await self._import_study(zip_path, study_accession)

        extract_dir = zip_path.parent / study_accession
        return {
            "action": "imported",
            "zip_path": str(zip_path),
            "extract_dir": str(extract_dir),
        }

    def _import_study_sync(self, zip_path: Path, study_accession: str) -> None:
        """Synchronous: unzip archive and run loadResearchData.sh to import into MySQL."""
        import subprocess
        import zipfile
        from urllib.parse import urlparse

        # 1. Unzip alongside the zip file
        extract_dir = zip_path.parent / study_accession
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        logger.info("Unzipped %s → %s", zip_path, extract_dir)

        # 2. Locate loadResearchData.sh (zip contains one top-level folder)
        candidates = list(extract_dir.glob("*/scripts/loadResearchData.sh"))
        if not candidates:
            raise FileNotFoundError(
                f"loadResearchData.sh not found after unzipping {zip_path}"
            )
        load_script = candidates[0]
        scripts_dir = load_script.parent  # must cd here; script uses ../MySQL/ relative paths

        # 3. Parse MySQL connection params from MYSQL_URL
        #    Format: mysql+aiomysql://user:pass@host:port/dbname
        raw_url = settings.MYSQL_URL.replace("mysql+aiomysql://", "mysql://", 1)
        parsed = urlparse(raw_url)
        host = parsed.hostname or "localhost"
        user = parsed.username or ""
        password = parsed.password or ""
        database = parsed.path.lstrip("/")

        # 4. Run the script from scripts_dir (relative paths require this cwd)
        result = subprocess.run(
            ["bash", "loadResearchData.sh", host, user, password, database],
            cwd=scripts_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"loadResearchData.sh failed for {study_accession}:\n{result.stderr}"
            )
        logger.info("Import complete for %s", study_accession)

    async def _import_study(self, zip_path: Path, study_accession: str) -> None:
        """Async wrapper: offload blocking zip+subprocess to a thread."""
        import asyncio

        await asyncio.to_thread(self._import_study_sync, zip_path, study_accession)

    async def _study_exists(self, study_accession: str) -> bool:
        """Return True if the study is already present in the local DB."""
        async with async_session() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM study WHERE study_accession = :s"),
                {"s": study_accession},
            )
            count = result.scalar()
            return (count or 0) > 0

    async def _get_auth_token(self) -> str:
        """Authenticate with ImmPort and return a bearer token."""
        url = f"{settings.IMMPORT_BASE_URL}/auth/token"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                data={
                    "username": settings.IMMPORT_USERNAME,
                    "password": settings.IMMPORT_PASSWORD,
                },
                timeout=30,
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"ImmPort auth failed (HTTP {response.status_code}): {response.text}"
            )
        return response.json()["access_token"]

    async def _get_file_uuid(self, study_accession: str, token: str) -> str:
        """Retrieve the fileUUID for the MySQL dump zip from the study manifest."""
        url = f"{settings.IMMPORT_BASE_URL}/data/query/api/study/manifest/{study_accession}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"ImmPort manifest request failed (HTTP {response.status_code}): {response.text}"
            )
        manifest = response.json()
        for entry in manifest:
            path = entry.get("path", "")
            if path.endswith("_MySQL.zip"):
                return entry["fileUUID"]
        raise ValueError(f"No MySQL dump found in manifest for {study_accession}")

    async def _download_zip(
        self, file_uuid: str, token: str, study_accession: str
    ) -> Path:
        """Stream-download the MySQL zip to downloads/{study_accession}.zip."""
        url = f"{settings.IMMPORT_BASE_URL}/data/query/drs/download/s3/{file_uuid}"
        downloads_dir = Path(__file__).resolve().parent.parent.parent / "downloads"
        downloads_dir.mkdir(exist_ok=True)
        zip_path = downloads_dir / f"{study_accession}.zip"

        async with httpx.AsyncClient() as client:
            # Step 1: resolve the signed S3 URL from the DRS endpoint
            drs_resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            if drs_resp.status_code != 200:
                raise RuntimeError(
                    f"ImmPort DRS lookup failed (HTTP {drs_resp.status_code})"
                )
            signed_url = drs_resp.json()["url"]

            # Step 2: stream-download from the signed S3 URL
            async with client.stream("GET", signed_url, timeout=300) as response:
                if response.status_code != 200:
                    raise RuntimeError(
                        f"ImmPort download failed (HTTP {response.status_code})"
                    )
                with open(zip_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        return zip_path
