"""The experiment tests run from the repo root (`./.venv/bin/pytest experiment/obi_analyte_terms/tests`)
and import the production package, the scripts and the two experiment modules by path."""

import os
import sys
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("MYSQL_URL", "mysql+aiomysql://user:pass@localhost:3306/testdb")

_EXPERIMENT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _EXPERIMENT.parents[1]
for path in (_REPO_ROOT / "apps" / "api", _REPO_ROOT / "scripts", _EXPERIMENT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
