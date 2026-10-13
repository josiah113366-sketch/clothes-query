from pathlib import Path

import psycopg
import pytest

from sim.common.config import ConfigError, load_config
from sim.common.db import SafeDatabaseError, describe_db_error, describe_target, safe_db_errors

PII = "hong.gildong@secret-mail.com"


def test_config_defaults_and_override(tmp_path: Path) -> None:
    config = load_config({"DATABASE_URL": "postgresql://u:p@h/d"}, tmp_path)
    assert config.seed == 42
    assert config.region_file == tmp_path / "data/region_weights_202609.csv"
    config = load_config({"DATABASE_URL": "x", "SIM_SEED": "7"}, tmp_path)
    assert config.seed == 7


def test_config_requires_database_url(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config({}, tmp_path)
    assert load_config({}, tmp_path, require_database=False).database_url == ""


def test_config_repr_hides_url(tmp_path: Path) -> None:
    config = load_config({"DATABASE_URL": "postgresql://sim:secretpw@h/d"}, tmp_path)
    assert "secretpw" not in repr(config)


def test_describe_target_hides_credentials() -> None:
    assert describe_target("postgresql://sim:secretpw@db.example:5433/clothes") == (
        "db.example:5433/clothes"
    )


def test_db_error_is_scrubbed() -> None:
    error = psycopg.errors.UniqueViolation(f"Key (email)=({PII}) already exists.")
    assert PII not in describe_db_error(error)
    with pytest.raises(SafeDatabaseError) as info, safe_db_errors():
        raise error
    assert PII not in str(info.value)
    assert "UniqueViolation" in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
