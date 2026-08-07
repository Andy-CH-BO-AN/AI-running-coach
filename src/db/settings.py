from __future__ import annotations

import os

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError, SQLAlchemyError

DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5432/ai_running_coach"
VALID_DATABASE_MODES = {"local", "mirror", "cloud"}
VALID_DATABASE_TARGETS = {"primary", "shadow", "local", "cloud"}
VALID_DATABASE_PURPOSES = {"app", "direct"}
POSTGRES_DRIVER_ALIASES = {"postgres", "postgresql", "postgresql+psycopg2"}
TRANSIENT_POSTGRES_SQLSTATES = frozenset({"57P01", "57P02", "57P03"})
AUTHENTICATION_FAILURE_MARKERS = (
    "password authentication failed",
    "authentication failed",
    "no password supplied",
    "no pg_hba.conf entry",
)
CONFIGURATION_FAILURE_MARKERS = (
    "certificate verify failed",
    "unsupported startup parameter",
)
TRANSIENT_RESTART_ERROR_NAMES = frozenset(
    {
        "adminshutdown",
        "cannotconnectnow",
        "crashshutdown",
    }
)
TRANSIENT_RESTART_MARKERS = (
    "the database system is starting up",
    "the database system is shutting down",
    "the database system is in recovery mode",
    "terminating connection due to administrator command",
    "terminating connection because of crash of another server process",
)


def env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _is_sqlalchemy_connection_error(exc: SQLAlchemyError) -> bool:
    original = getattr(exc, "orig", exc)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    detail = str(original).lower()
    if any(
        marker in detail
        for marker in AUTHENTICATION_FAILURE_MARKERS + CONFIGURATION_FAILURE_MARKERS
    ):
        return False
    if "fatal:" in detail and "does not exist" in detail:
        return False

    if isinstance(sqlstate, str):
        normalized_sqlstate = sqlstate.upper()
        return (
            normalized_sqlstate.startswith("08")
            or normalized_sqlstate in TRANSIENT_POSTGRES_SQLSTATES
        )

    original_error_name = type(original).__name__.lower()
    if original_error_name in TRANSIENT_RESTART_ERROR_NAMES:
        return True
    if any(marker in detail for marker in TRANSIENT_RESTART_MARKERS):
        return True

    if isinstance(exc, DisconnectionError):
        return True
    if not isinstance(exc, (OperationalError, InterfaceError)):
        return False

    connection_markers = (
        "could not connect",
        "connection refused",
        "connection reset",
        "connection closed",
        "connection timed out",
        "connection timeout",
        "connect timeout",
        "timeout expired",
        "network is unreachable",
        "no route to host",
        "server closed",
        "server is not accepting",
        "ssl connection has been closed",
        "ssl syscall error",
        "could not translate host",
        "failed to resolve host",
        "nodename nor servname provided",
        "name or service not known",
        "temporary failure in name resolution",
        "database is unavailable",
    )
    return any(marker in detail for marker in connection_markers) or (
        "ssl" in detail and "connection" in detail
    )


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """Follow explicit wrapping and DBAPI origins, not unrelated implicit context."""
    chain: list[BaseException] = []
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        for related in (
            getattr(current, "orig", None),
            current.__cause__,
        ):
            if isinstance(related, BaseException):
                pending.append(related)
    return chain


def is_database_connection_error(exc: BaseException) -> bool:
    """Classify transient PostgreSQL connectivity loss through wrapped exceptions."""
    chain = _exception_chain(exc)
    if is_database_authentication_error(exc) or is_database_configuration_error(exc):
        return False
    return any(
        _is_sqlalchemy_connection_error(candidate)
        for candidate in chain
        if isinstance(candidate, SQLAlchemyError)
    )


def is_database_authentication_error(exc: BaseException) -> bool:
    """Recognize PostgreSQL authentication failures without exposing their details."""
    for candidate in _exception_chain(exc):
        sqlstate = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if isinstance(sqlstate, str) and sqlstate.upper().startswith("28"):
            return True
        detail = str(candidate).lower()
        if any(marker in detail for marker in AUTHENTICATION_FAILURE_MARKERS):
            return True
    return False


def is_database_configuration_error(exc: BaseException) -> bool:
    """Recognize PostgreSQL connection configuration failures."""
    for candidate in _exception_chain(exc):
        detail = str(candidate).lower()
        if any(marker in detail for marker in CONFIGURATION_FAILURE_MARKERS):
            return True
        if "fatal:" in detail and "does not exist" in detail:
            return True
    return False


def postgres_env_database_url(prefix: str = "POSTGRES_") -> str | None:
    host = env_value(f"{prefix}HOST")
    if not host:
        return None

    return str(
        URL.create(
            "postgresql+psycopg",
            username=env_value(f"{prefix}USER") or "postgres",
            password=env_value(f"{prefix}PASSWORD"),
            host=host,
            port=int(env_value(f"{prefix}PORT") or "5432"),
            database=env_value(f"{prefix}DB") or "ai_running_coach",
        ).render_as_string(hide_password=False)
    )


def normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername in POSTGRES_DRIVER_ALIASES:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def get_database_mode() -> str:
    mode = (env_value("DATABASE_MODE") or "local").lower()
    if mode not in VALID_DATABASE_MODES:
        raise ValueError(
            f"Unsupported DATABASE_MODE={mode!r}. Expected one of: {', '.join(sorted(VALID_DATABASE_MODES))}."
        )
    return mode


def get_local_database_url() -> str:
    explicit_local_url = env_value("LOCAL_DATABASE_URL")
    if explicit_local_url:
        return normalize_database_url(explicit_local_url)

    legacy_database_url = env_value("DATABASE_URL")
    if legacy_database_url:
        return normalize_database_url(legacy_database_url)

    postgres_url = postgres_env_database_url()
    if postgres_url:
        return postgres_url

    return DEFAULT_DATABASE_URL


def get_cloud_database_url(*, purpose: str = "app") -> str:
    if purpose not in VALID_DATABASE_PURPOSES:
        raise ValueError(
            f"Unsupported database purpose={purpose!r}. Expected one of: {', '.join(sorted(VALID_DATABASE_PURPOSES))}."
        )

    if purpose == "direct":
        database_url = env_value("NEON_DATABASE_DIRECT_URL")
        if database_url:
            return normalize_database_url(database_url)
        raise ValueError("Cloud direct DB requested but NEON_DATABASE_DIRECT_URL is not configured.")

    database_url = env_value("NEON_DATABASE_URL") or env_value("NEON_DATABASE_DIRECT_URL")
    if database_url:
        return normalize_database_url(database_url)
    raise ValueError("Cloud DB requested but NEON_DATABASE_URL / NEON_DATABASE_DIRECT_URL not configured.")


def resolve_database_url(target: str = "primary", *, purpose: str = "app") -> str:
    if target not in VALID_DATABASE_TARGETS:
        raise ValueError(
            f"Unsupported database target={target!r}. Expected one of: {', '.join(sorted(VALID_DATABASE_TARGETS))}."
        )

    if purpose not in VALID_DATABASE_PURPOSES:
        raise ValueError(
            f"Unsupported database purpose={purpose!r}. Expected one of: {', '.join(sorted(VALID_DATABASE_PURPOSES))}."
        )

    if target == "local":
        return get_local_database_url()

    if target == "cloud":
        return get_cloud_database_url(purpose=purpose)

    mode = get_database_mode()
    if target == "primary":
        resolved_target = "cloud" if mode == "cloud" else "local"
        return resolve_database_url(resolved_target, purpose=purpose)

    if mode != "mirror":
        raise ValueError("Shadow DB requested but DATABASE_MODE is not 'mirror'.")
    return resolve_database_url("cloud", purpose=purpose)


def get_database_url() -> str:
    return resolve_database_url("primary", purpose="app")


def get_shadow_database_url() -> str | None:
    if get_database_mode() != "mirror":
        return None
    return resolve_database_url("shadow", purpose="app")


def get_migration_database_url() -> str:
    target = (env_value("DATABASE_MIGRATION_TARGET") or "primary").lower()
    return resolve_database_url(target, purpose="direct")
