from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.settings import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_configured_url: str | None = None
_configured_echo: bool | None = None
_schema_initialized = False


def configure_database(*, url: str, echo: bool = False, force: bool = False) -> None:
    """Configure the shared SQLAlchemy engine and session factory."""
    global _engine, _session_factory, _configured_url, _configured_echo, _schema_initialized

    if _engine is not None and not force and url == _configured_url and echo == _configured_echo:
        return

    if _engine is not None:
        _engine.dispose()

    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(
        url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    _session_factory = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    _configured_url = url
    _configured_echo = echo
    _schema_initialized = False


def get_engine() -> Engine:
    """Return the configured engine, creating it lazily from settings when needed."""
    if _engine is None:
        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
        )
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the configured session factory, creating it lazily from settings when needed."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def init_database(force: bool = False) -> None:
    """Create all configured tables in the target database."""
    global _schema_initialized
    if _schema_initialized and not force:
        return

    from app.infrastructure.db.models import Base

    Base.metadata.create_all(bind=get_engine())
    _schema_initialized = True


@contextmanager
def session_scope() -> Iterator[Session]:
    """Open a transactional session scope with automatic commit/rollback."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
