"""Repair saved Garmin set weights for an explicit, inclusive date range."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import Activity, User
from src.db.session import SessionLocal
from src.ingestion.strength_training import parse_strength_training


def recover_strength_weights(
    metrics: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    parsed = parse_strength_training(
        metrics.get("strength_raw_summary"), metrics.get("strength_raw_exercise_sets")
    )
    parsed_sets = parsed["sets"]
    if not parsed_sets:
        return "no_raw_sets", None
    if not any(item["weight_kg"] is not None for item in parsed_sets):
        return "no_recorded_weight", None

    saved = metrics.get("strength")
    saved_sets = saved.get("sets") if isinstance(saved, dict) else None
    if saved_sets is None or saved_sets == []:
        return "recoverable", parsed
    if not isinstance(saved_sets, list) or not all(isinstance(item, dict) for item in saved_sets):
        return "set_mismatch", None

    def set_keys(sets: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
        return [(item.get("set_index"), item.get("set_type")) for item in sets]

    if set_keys(saved_sets) != set_keys(parsed_sets):
        return "set_mismatch", None
    repaired = [
        {
            **old,
            "reps": new["reps"] if old.get("reps") is None else old["reps"],
            "weight_kg": new["weight_kg"] if old.get("weight_kg") is None else old["weight_kg"],
        }
        for old, new in zip(saved_sets, parsed_sets, strict=True)
    ]
    if repaired == saved_sets:
        return "already_current", None
    return "recoverable", {**saved, "sets": repaired}


def backfill_strength_weights(
    session: Session, start: date, end: date, *, apply: bool
) -> Counter[str]:
    stmt = (
        select(Activity)
        .join(User)
        .where(
            User.external_source == "local",
            User.external_user_id == "default",
            Activity.activity_type == "strength_training",
            Activity.source == "garmin",
            Activity.activity_date.between(start, end),
        )
        .order_by(Activity.id)
    )
    if apply:
        stmt = stmt.with_for_update(of=Activity)

    counts: Counter[str] = Counter()
    for activity in session.scalars(stmt):
        counts["scanned"] += 1
        raw_json = activity.raw_json
        json_metrics = raw_json.get("raw_data") or raw_json.get("raw_metrics") or {}
        stored_metrics = activity.raw_metrics
        metrics_status, metrics_repair = recover_strength_weights(
            {**json_metrics, **stored_metrics, "strength": stored_metrics.get("strength")}
        )
        json_status, json_repair = recover_strength_weights(
            {**stored_metrics, **json_metrics, "strength": json_metrics.get("strength")}
        )
        if json_status == "already_current" and not raw_json.get("raw_data"):
            json_repair = json_metrics["strength"]
        statuses = {metrics_status, json_status}
        if "set_mismatch" in statuses:
            counts["set_mismatch"] += 1
        if metrics_repair is None and json_repair is None:
            if "set_mismatch" not in statuses:
                counts[metrics_status] += 1
            continue
        counts["recoverable"] += 1
        if not apply:
            continue
        if metrics_repair is not None:
            activity.raw_metrics = {**stored_metrics, "strength": metrics_repair}
        if json_repair is not None:
            activity.raw_json = {**raw_json, "raw_data": {**json_metrics, "strength": json_repair}}
        counts["updated"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", required=True, dest="start", type=date.fromisoformat)
    parser.add_argument("--through", required=True, dest="end", type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true", help="Commit the repair instead of previewing it.")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--from must be on or before --through")

    try:
        with SessionLocal() as session, session.begin():
            counts = backfill_strength_weights(session, args.start, args.end, apply=args.apply)
    except SQLAlchemyError as exc:
        raise SystemExit(f"Database backfill failed ({type(exc).__name__}).") from None
    print(f"{'Applied' if args.apply else 'Preview'} {args.start} through {args.end}")
    print(", ".join(f"{key}={counts[key]}" for key in ("scanned", "updated")))
    for key in ("recoverable", "already_current", "no_raw_sets", "no_recorded_weight", "set_mismatch"):
        print(f"{key}={counts[key]}")


if __name__ == "__main__":
    main()
