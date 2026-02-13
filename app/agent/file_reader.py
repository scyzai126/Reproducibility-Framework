import csv
import io
import json
from pathlib import Path


SUPPORTED_EXTENSIONS = {".txt", ".csv", ".json"}


def read_file(file_path: str) -> str:
    """Read a file and return its content as a string suitable for an LLM prompt.

    Supports .txt, .csv, and .json files.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{suffix}'. Supported: {SUPPORTED_EXTENSIONS}"
        )

    raw = path.read_text(encoding="utf-8")

    if suffix == ".txt":
        return raw

    if suffix == ".json":
        data = json.loads(raw)
        return json.dumps(data, indent=2)

    # .csv
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    return json.dumps(rows, indent=2)
