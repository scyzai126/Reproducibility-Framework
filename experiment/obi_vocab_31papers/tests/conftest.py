import os
import sys
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("MYSQL_URL", "mysql+aiomysql://user:pass@localhost:3306/testdb")

_EXPERIMENT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _EXPERIMENT.parents[1]
for path in (_REPO_ROOT / "apps" / "api", _REPO_ROOT / "scripts",
             _REPO_ROOT / "experiment" / "obi_analyte_terms", _EXPERIMENT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
