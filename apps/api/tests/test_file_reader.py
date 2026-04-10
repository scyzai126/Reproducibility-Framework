import json
import pytest
from app.agent.file_reader import read_file, SUPPORTED_EXTENSIONS


def test_read_txt(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello world")
    assert read_file(str(f)) == "hello world"


def test_read_json(tmp_path):
    data = {"name": "Alice", "age": 30}
    f = tmp_path / "sample.json"
    f.write_text(json.dumps(data))
    result = json.loads(read_file(str(f)))
    assert result == data


def test_read_csv(tmp_path):
    f = tmp_path / "sample.csv"
    f.write_text("name,age\nAlice,30\nBob,25\n")
    result = json.loads(read_file(str(f)))
    assert len(result) == 2
    assert result[0]["name"] == "Alice"


def test_unsupported_extension(tmp_path):
    f = tmp_path / "sample.xml"
    f.write_text("<root/>")
    with pytest.raises(ValueError, match="Unsupported file type"):
        read_file(str(f))


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        read_file("/nonexistent/path.txt")
