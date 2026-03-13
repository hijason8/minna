"""
手動貼入 JSON 匯入單字／慣用語。
用於在串接 YouTube／LLM 前先測試抽卡與星標功能。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.database import get_connection, init_db


def _ensure_lesson_exists(session, lesson_id: int) -> None:
    """
    若 lesson_id 對應的課程不存在，則建立一筆手動匯入用的 stub 課程。
    """
    row = session.execute(text("SELECT id FROM lessons WHERE id = :id"), {"id": lesson_id}).mappings().fetchone()
    if row:
        return
    session.execute(
        text("INSERT INTO lessons (id, youtube_url, lesson_name, created_at) VALUES (:id, :url, :name, :created_at)"),
        {"id": lesson_id, "url": f"manual://lesson-{lesson_id}", "name": f"手動匯入 Lesson {lesson_id}", "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")},
    )


def import_vocabulary_json(items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    將手動貼上的 JSON 陣列寫入 vocabulary 表。
    每筆需含：kanji（可空）, kana, meaning, lesson_id；is_starred 可選，預設 False。
    """
    init_db()
    session = get_connection()
    inserted_ids = []
    try:
        for row in items:
            lesson_id = int(row["lesson_id"])
            _ensure_lesson_exists(session, lesson_id)
            kanji = (row.get("kanji") or "").strip() or None
            kana = (row.get("kana") or "").strip()
            meaning = (row.get("meaning") or "").strip()
            is_starred = bool(row.get("is_starred", False))
            if not kana or not meaning:
                continue
            r = session.execute(
                text("""
                    INSERT INTO vocabulary (lesson_id, kanji, kana, meaning, is_starred, weight, created_at)
                    VALUES (:lesson_id, :kanji, :kana, :meaning, :is_starred, 0, :created_at)
                    RETURNING id
                """),
                {
                    "lesson_id": lesson_id,
                    "kanji": kanji,
                    "kana": kana,
                    "meaning": meaning,
                    "is_starred": 1 if is_starred else 0,
                    "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            one = r.mappings().fetchone()
            if one:
                inserted_ids.append(one["id"])
        session.commit()
        return {"imported_count": len(inserted_ids), "vocabulary_ids": inserted_ids}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
