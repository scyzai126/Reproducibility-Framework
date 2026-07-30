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


def test_read_json_invalid_content(tmp_path):
    f = tmp_path / "broken.json"
    f.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        read_file(str(f))


def test_read_csv(tmp_path):
    f = tmp_path / "sample.csv"
    f.write_text("name,age\nAlice,30\nBob,25\n")
    result = json.loads(read_file(str(f)))
    assert len(result) == 2
    assert result[0]["name"] == "Bob"


def test_read_csv_header_only(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("name,age\n")
    result = json.loads(read_file(str(f)))
    assert result == []


def test_read_csv_completely_empty(tmp_path):
    f = tmp_path / "blank.csv"
    f.write_text("")
    result = json.loads(read_file(str(f)))
    assert result == []


def test_unsupported_extension(tmp_path):
    f = tmp_path / "sample.xml"
    f.write_text("<root/>")
    with pytest.raises(ValueError, match="Unsupported file type"):
        read_file(str(f))


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        read_file("/nonexistent/path.txt")


def test_read_relative_path(tmp_path, monkeypatch):
    import app.agent.file_reader as file_reader_module

    monkeypatch.setattr(file_reader_module, "PROJECT_ROOT", tmp_path)
    f = tmp_path / "relative.txt"
    f.write_text("relative content")
    assert read_file("relative.txt") == "relative content"
