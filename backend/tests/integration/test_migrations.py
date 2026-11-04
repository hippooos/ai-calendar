from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert {"planning_sessions", "model_runs", "drafts", "draft_items", "calendar_events", "confirmation_requests"} <= tables
    assert "diagnostic_json" in {column["name"] for column in inspect(engine).get_columns("model_runs")}

    command.downgrade(config, "base")
    assert "planning_sessions" not in set(inspect(engine).get_table_names())


def test_database_url_environment_overrides_alembic_ini(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "from-env.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    assert "planning_sessions" in set(inspect(create_engine(f"sqlite:///{database_path.as_posix()}")).get_table_names())
