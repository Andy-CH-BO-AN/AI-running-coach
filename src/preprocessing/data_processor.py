import logging
from typing import Any, Dict, List, Optional

from src.preprocessing.activity_window import (
    calculate_cycling_efficiency,
    calculate_pace,
    calculate_running_efficiency,
    calculate_swimming_efficiency,
    classify_runner_type,
    format_pace,
    normalize_activity_window,
)

logger = logging.getLogger(__name__)


def calculate_hrr(resting_hr: Optional[float], max_hr: Optional[float]) -> Optional[float]:
    if not resting_hr or not max_hr:
        return None

    if resting_hr < 30 or resting_hr > 100:
        logger.warning("Unrealistic resting heart rate: %s", resting_hr)
        return None

    if max_hr < 120 or max_hr > 230:
        logger.warning("Unrealistic max heart rate: %s", max_hr)
        return None

    hrr = max_hr - resting_hr
    return round(hrr, 1) if hrr > 0 else None


def preprocess_data(raw_activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compatibility facade for the ActivityWindow processed projection."""

    return normalize_activity_window(raw_activities).processed_data()


__all__ = [
    "calculate_cycling_efficiency",
    "calculate_hrr",
    "calculate_pace",
    "calculate_running_efficiency",
    "calculate_swimming_efficiency",
    "classify_runner_type",
    "format_pace",
    "preprocess_data",
]
