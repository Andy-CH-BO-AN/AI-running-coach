from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.db.session import resolve_database_url


def build_target_engine(target: str, *, purpose: str = "direct") -> Engine:
    return create_engine(resolve_database_url(target, purpose=purpose), future=True, pool_pre_ping=True)
