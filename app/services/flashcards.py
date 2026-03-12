"""
抽卡複習系統（SRS）：牌組取得、下一張卡、複習記錄。
支援 日翻中、中翻日、聽力練習；可篩選 is_starred 作為「強化訓練單元」。
"""
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text

from app.database import get_connection
from app.services.audio_storage import get_vocabulary_audio_path, get_audio_path_if_exists

CardType = Literal["ja_to_zh", "zh_to_ja", "listening"]
Outcome = Literal["again", "good", "easy"]

INTERVAL_DAYS = {"again": 0, "good": 1, "easy": 3}


def _build_deck_filter(lesson_id: int | None, starred_only: bool) -> tuple[str, dict[str, Any]]:
    """組出 WHERE 條件與參數。排除 mastered=1。"""
    conditions = ["(mastered IS NULL OR mastered = 0)"]
    params: dict[str, Any] = {}
    if lesson_id is not None:
        conditions.append("lesson_id = :lesson_id")
        params["lesson_id"] = lesson_id
    if starred_only:
        conditions.append("is_starred = 1")
    return " AND ".join(conditions), params


def get_deck(
    lesson_id: int | None = None,
    starred_only: bool = False,
    card_type: CardType = "ja_to_zh",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """取得牌組列表。"""
    where, params = _build_deck_filter(lesson_id, starred_only)
    params["limit"] = limit
    session = get_connection()
    try:
        rows = session.execute(
            text(f"""
                SELECT id, lesson_id, kanji, kana, meaning, audio_path, is_starred,
                       next_review_at, interval_days
                FROM vocabulary
                WHERE {where}
                ORDER BY next_review_at IS NULL DESC, next_review_at ASC, id
                LIMIT :limit
            """),
            params,
        ).mappings().fetchall()
        return [_format_card(dict(r), card_type) for r in rows]
    finally:
        session.close()


def _format_card(row: dict[str, Any], card_type: CardType) -> dict[str, Any]:
    """依卡片類型組出前端所需結構。"""
    vid = row["id"]
    kanji = row["kanji"] or ""
    kana = row["kana"] or ""
    meaning = row["meaning"] or ""
    audio_path = row["audio_path"]
    if not audio_path:
        p = get_audio_path_if_exists(vid, kana)
        audio_path = str(p) if p else str(get_vocabulary_audio_path(vid, kana))
    base = {
        "vocabulary_id": vid,
        "lesson_id": row["lesson_id"],
        "is_starred": bool(row["is_starred"]),
        "interval_days": row["interval_days"] if row.get("interval_days") is not None else 0,
        "next_review_at": row["next_review_at"],
    }
    if card_type == "ja_to_zh":
        return {**base, "card_type": "ja_to_zh", "front": {"kanji": kanji, "kana": kana}, "back": {"meaning": meaning}}
    if card_type == "zh_to_ja":
        return {**base, "card_type": "zh_to_ja", "front": {"meaning": meaning}, "back": {"kanji": kanji, "kana": kana}}
    return {**base, "card_type": "listening", "front": {"audio_path": audio_path, "kana": kana}, "back": {"meaning": meaning, "kanji": kanji, "kana": kana}}


def get_next_card(
    lesson_id: int | None = None,
    starred_only: bool = False,
    card_type: CardType = "ja_to_zh",
    exclude_vocabulary_id: int | None = None,
) -> dict[str, Any] | None:
    """取得下一張待複習的卡。"""
    where, params = _build_deck_filter(lesson_id, starred_only)
    if exclude_vocabulary_id is not None:
        where += " AND id != :exclude_id"
        params["exclude_id"] = exclude_vocabulary_id
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    params["now"] = now
    session = get_connection()
    try:
        row = session.execute(
            text(f"""
                SELECT id, lesson_id, kanji, kana, meaning, audio_path, is_starred,
                       next_review_at, interval_days
                FROM vocabulary
                WHERE {where} AND (next_review_at IS NULL OR next_review_at <= :now)
                ORDER BY RANDOM()
                LIMIT 1
            """),
            params,
        ).mappings().fetchone()
        if not row:
            row = session.execute(
                text(f"""
                    SELECT id, lesson_id, kanji, kana, meaning, audio_path, is_starred,
                           next_review_at, interval_days
                    FROM vocabulary
                    WHERE {where}
                    ORDER BY RANDOM()
                    LIMIT 1
                """),
                {k: v for k, v in params.items() if k != "now"},
            ).mappings().fetchone()
        return _format_card(dict(row), card_type) if row else None
    finally:
        session.close()


def record_review(vocabulary_id: int, outcome: Outcome) -> dict[str, Any]:
    """記錄複習結果並更新 next_review_at、interval_days。"""
    days = INTERVAL_DAYS[outcome]
    next_review = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days > 0 else None
    session = get_connection()
    try:
        session.execute(
            text("UPDATE vocabulary SET next_review_at = :next_review, interval_days = :days WHERE id = :id"),
            {"next_review": next_review, "days": days, "id": vocabulary_id},
        )
        if outcome == "again":
            session.execute(text("UPDATE vocabulary SET is_starred = 1 WHERE id = :id"), {"id": vocabulary_id})
        if outcome == "easy":
            session.execute(text("UPDATE vocabulary SET mastered = 1, is_starred = 0 WHERE id = :id"), {"id": vocabulary_id})
        session.commit()
        row = session.execute(
            text("SELECT next_review_at, interval_days, is_starred, mastered FROM vocabulary WHERE id = :id"),
            {"id": vocabulary_id},
        ).mappings().fetchone()
        return {
            "vocabulary_id": vocabulary_id,
            "outcome": outcome,
            "next_review_at": row["next_review_at"] if row else None,
            "interval_days": row["interval_days"] if row else 0,
            "is_starred": bool(row["is_starred"]) if row else False,
            "mastered": bool(row["mastered"]) if row else False,
        }
    finally:
        session.close()
