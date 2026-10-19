import os

# Set dummy env vars before any app imports that trigger config loading
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("MYSQL_URL", "mysql+aiomysql://user:pass@localhost:3306/testdb")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_assay_cache(tmp_path, monkeypatch):
    """No test writes a new paper's results into the real data/cache/assays."""
    from app.agent import assay_service

    monkeypatch.setattr(assay_service, "CACHE_ROOT", tmp_path / "cache_assays")


@pytest.fixture(autouse=True)
def _single_extraction(monkeypatch):
    """The chain tests drive round 1 with one canned body each. The default of three voted
    extractions is covered by its own tests, which set this back to 3."""
    from app.agent import assay_service

    monkeypatch.setattr(assay_service, "EXTRACTIONS", 1)


@pytest.fixture(autouse=True)
def _isolated_claims_cache(tmp_path, monkeypatch):
    """No test writes a new paper's claims into the real data/cache/claims."""
    from app.agent import orchestrator

    monkeypatch.setattr(orchestrator, "_CLAIMS_CACHE_DIR", tmp_path / "cache_claims")
