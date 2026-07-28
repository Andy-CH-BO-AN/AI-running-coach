from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.settings import (
    get_cloud_database_url,
    get_database_mode,
    get_database_url,
    get_local_database_url,
    get_migration_database_url,
    get_shadow_database_url,
    is_database_available,
    resolve_database_url,
)

load_dotenv()


class DatabaseUnavailableError(RuntimeError):
    """Raised before any engine or session is created in degraded mode."""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_shadow_engine: Engine | None = None
_shadow_session_factory: sessionmaker[Session] | None = None


def _require_database_available() -> None:
    if not is_database_available():
        raise DatabaseUnavailableError("Database access is disabled because DATABASE_AVAILABLE=false.")


def build_engine(
    database_url: str | None = None,
    *,
    target: str = "primary",
    purpose: str = "app",
) -> Engine:
    _require_database_available()
    return create_engine(
        database_url or resolve_database_url(target, purpose=purpose),
        future=True,
        pool_pre_ping=True,
    )


def get_engine() -> Engine:
    """Lazily create primary engine only when normal-mode code needs it."""
    global _engine
    _require_database_available()
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def SessionLocal() -> Session:
    """Compatibility callable for existing repository/session call sites."""
    return get_session_factory()()


def get_shadow_session_factory() -> sessionmaker[Session]:
    global _shadow_engine, _shadow_session_factory
    _require_database_available()
    if _shadow_session_factory is not None:
        return _shadow_session_factory

    shadow_database_url = get_shadow_database_url()
    if shadow_database_url is None:
        raise RuntimeError("Shadow DB is not configured. Set DATABASE_MODE=mirror with Neon URLs.")

    _shadow_engine = build_engine(database_url=shadow_database_url)
    _shadow_session_factory = sessionmaker(
        bind=_shadow_engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    return _shadow_session_factory


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def get_shadow_session() -> Generator[Session, None, None]:
    with get_shadow_session_factory()() as session:
        yield session
