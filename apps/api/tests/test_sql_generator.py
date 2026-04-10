import pytest
from app.agent.sql_generator import _validate_sql


def test_validate_safe_select():
    _validate_sql("SELECT * FROM users WHERE id = 1")


def test_validate_rejects_drop():
    with pytest.raises(ValueError, match="forbidden"):
        _validate_sql("DROP TABLE users")


def test_validate_rejects_truncate():
    with pytest.raises(ValueError, match="forbidden"):
        _validate_sql("TRUNCATE TABLE users")


def test_validate_rejects_alter():
    with pytest.raises(ValueError, match="forbidden"):
        _validate_sql("ALTER TABLE users ADD COLUMN email VARCHAR(255)")


def test_validate_rejects_delete():
    with pytest.raises(ValueError, match="forbidden"):
        _validate_sql("DELETE FROM users WHERE id = 1")


def test_validate_rejects_update():
    with pytest.raises(ValueError, match="forbidden"):
        _validate_sql("UPDATE users SET name = 'x' WHERE id = 1")
