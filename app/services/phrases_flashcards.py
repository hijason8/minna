"""
短語複習（SRS）：下一張、複習記錄。邏輯同單字，表為 phrases。
"""
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text

from app.database import get_connection

Outcome = Literal["again", "good", "easy"]
INTERVAL_DAYS = {"again": 0, "good": 1, "easy": 3}


def _build_filter(lesson_id: int | None, starred_only: bool) -> tuple[str, dict[str, Any]]:
    conditions = ["(mastered IS NULL OR mastered = 0)"]
    params: dict[str, Any] = {}
    if lesson_id is not None:
        conditions.append("lesson_id = :lesson_id")
        params["lesson_id"] = lesson_id
    if starred_only:
        conditions.append("is_starred = 1")
    return " AND ".join(conditions), params


def get_next_phrase(
    lesson_id: int | None = None,
    starred_only: bool = False,
    exclude_phrase_id: int | None = None,
) -> dict[str, Any] | None:
    where, params = _build_filter(lesson_id, starred_only)
    if exclude_phrase_id is not None:
        where += " AND id != :exclude_id"
        params["exclude_id"] = exclude_phrase_id
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    params["now"] = now
    session = get_connection()
    try:
        row = session.execute(
            text(f"""
                SELECT id, lesson_id, kanji, kana, meaning, is_starred,
                       next_review_at, interval_days
                FROM phrases
                WHERE {where} AND (next_review_at IS NULL OR next_review_at <= :now)
                ORDER BY RANDOM()
                LIMIT 1
            """),
            params,
        ).mappings().fetchone()
        if not row:
            row = session.execute(
                text(f"""
                    SELECT id, lesson_id, kanji, kana, meaning, is_starred,
                           next_review_at, interval_days
                    FROM phrases
                    WHERE {where}
                    ORDER BY RANDOM()
                    LIMIT 1
                """),
                {k: v for k, v in params.items() if k != "now"},
            ).mappings().fetchone()
        if not row:
            return None
        return {
            "phrase_id": row["id"],
            "lesson_id": row["lesson_id"],
            "is_starred": bool(row["is_starred"]),
            "interval_days": row["interval_days"] or 0,
            "next_review_at": row["next_review_at"],
            "front": {"kanji": row["kanji"] or "", "kana": row["kana"] or ""},
            "back": {"meaning": row["meaning"] or ""},
        }
    finally:
        session.close()


def record_phrase_review(phrase_id: int, outcome: Outcome) -> dict[str, Any]:
    days = INTERVAL_DAYS[outcome]
    next_review = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days > 0 else None
    session = get_connection()
    try:
        session.execute(
            text("UPDATE phrases SET next_review_at = :next_review, interval_days = :days WHERE id = :id"),
            {"next_review": next_review, "days": days, "id": phrase_id},
        )
        if outcome == "again":
            session.execute(text("UPDATE phrases SET is_starred = 1 WHERE id = :id"), {"id": phrase_id})
        if outcome == "easy":
            session.execute(text("UPDATE phrases SET mastered = 1, is_starred = 0 WHERE id = :id"), {"id": phrase_id})
        session.commit()
        row = session.execute(
            text("SELECT next_review_at, interval_days, is_starred, mastered FROM phrases WHERE id = :id"),
            {"id": phrase_id},
        ).mappings().fetchone()
        return {
            "phrase_id": phrase_id,
            "outcome": outcome,
            "next_review_at": row["next_review_at"] if row else None,
            "interval_days": row["interval_days"] if row else 0,
            "is_starred": bool(row["is_starred"]) if row else False,
            "mastered": bool(row["mastered"]) if row else False,
        }
    finally:
        session.close()
