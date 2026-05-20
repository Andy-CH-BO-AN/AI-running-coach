import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5432/ai_running_coach"


def _postgres_env_database_url() -> str | None:
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None

    return str(
        URL.create(
            "postgresql+psycopg",
            username=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=host,
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "ai_running_coach"),
        ).render_as_string(hide_password=False)
    )


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    postgres_url = _postgres_env_database_url()
    if postgres_url:
        return postgres_url

    return DEFAULT_DATABASE_URL


def build_engine(database_url: str | None = None):
    return create_engine(database_url or get_database_url(), future=True)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
