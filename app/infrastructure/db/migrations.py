from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def get_alembic_config(*, url: str | None = None) -> Config:
    """Build an Alembic config object that points at this repository's migration files."""
    repo_root = Path(__file__).resolve().parents[3]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    if url:
        config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade_database(*, url: str, revision: str = "head") -> None:
    """Apply Alembic migrations up to the requested revision."""
    command.upgrade(get_alembic_config(url=url), revision)
