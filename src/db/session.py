from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.settings import (
    get_cloud_database_url,
    get_database_mode,
    get_database_url,
    get_local_database_url,
    get_migration_database_url,
    get_shadow_database_url,
    resolve_database_url,
)

load_dotenv()


def build_engine(
    database_url: str | None = None,
    *,
    target: str = "primary",
    purpose: str = "app",
):
    return create_engine(database_url or resolve_database_url(target, purpose=purpose), future=True, pool_pre_ping=True)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
shadow_database_url = get_shadow_database_url()
shadow_engine = build_engine(database_url=shadow_database_url) if shadow_database_url else None
ShadowSessionLocal = (
    sessionmaker(bind=shadow_engine, autoflush=False, expire_on_commit=False, future=True) if shadow_engine else None
)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def get_shadow_session() -> Generator[Session, None, None]:
    if ShadowSessionLocal is None:
        raise RuntimeError("Shadow DB is not configured. Set DATABASE_MODE=mirror with Neon URLs.")

    with ShadowSessionLocal() as session:
        yield session
