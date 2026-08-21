from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


TRAINING_TIMEZONE = ZoneInfo("Asia/Taipei")


def resolve_training_calendar_date(now: datetime | None = None) -> date:
    """Resolve an instant against the athlete's Taiwan training calendar."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return instant.astimezone(TRAINING_TIMEZONE).date()
