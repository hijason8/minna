"""
YouTube URL 去重與每日解析上限邏輯。
解析新影片前先比對是否已存在，若已存在則不呼叫 AI，直接使用本地單字。
"""
from typing import Optional

from sqlalchemy import text

from app.config import Settings
from app.database import get_connection, init_db, is_postgres


def ensure_db() -> None:
    """確保資料庫與資料表已建立。"""
    init_db()


def get_lesson_id_by_url(youtube_url: str) -> Optional[int]:
    """
    依 YouTube URL 查詢是否已有對應課程，若有則回傳 lesson_id。
    """
    ensure_db()
    session = get_connection()
    try:
        row = session.execute(
            text("SELECT id FROM lessons WHERE youtube_url = :url"),
            {"url": youtube_url.strip()},
        ).mappings().fetchone()
        return row["id"] if row else None
    finally:
        session.close()


def count_parsed_today() -> int:
    """回傳今日已解析的 URL 數量（用於每日上限檢查）。"""
    ensure_db()
    session = get_connection()
    try:
        if is_postgres():
            sql = "SELECT COUNT(*) AS cnt FROM url_parse_history WHERE DATE(parsed_at) = CURRENT_DATE"
        else:
            sql = "SELECT COUNT(*) AS cnt FROM url_parse_history WHERE date(parsed_at) = date('now', 'localtime')"
        row = session.execute(text(sql)).mappings().fetchone()
        return row["cnt"] if row else 0
    finally:
        session.close()


def can_parse_more_today() -> bool:
    """今日是否還可解析新 URL（未達每日上限）。"""
    return count_parsed_today() < Settings().daily_parse_limit


def if_url_exists_then_skip_ai_call(youtube_url: str) -> tuple[bool, Optional[int]]:
    """
    判斷給定 YouTube URL 是否已存在於本地，若存在則應跳過 AI 呼叫。
    同時檢查每日解析上限。
    """
    url = youtube_url.strip()
    if not url:
        return True, None

    existing_lesson_id = get_lesson_id_by_url(url)
    if existing_lesson_id is not None:
        return True, existing_lesson_id

    if not can_parse_more_today():
        return False, None

    return False, None


def record_parsed_url(youtube_url: str, lesson_id: int) -> None:
    """
    記錄此次解析的 URL 與對應 lesson_id，供去重與每日計數使用。
    """
    ensure_db()
    session = get_connection()
    try:
        url = youtube_url.strip()
        if is_postgres():
            session.execute(
                text("""
                    INSERT INTO url_parse_history (youtube_url, lesson_id, parsed_at)
                    VALUES (:url, :lesson_id, NOW())
                    ON CONFLICT (youtube_url) DO UPDATE SET lesson_id = EXCLUDED.lesson_id, parsed_at = NOW()
                """),
                {"url": url, "lesson_id": lesson_id},
            )
        else:
            session.execute(
                text("""
                    INSERT OR REPLACE INTO url_parse_history (youtube_url, lesson_id, parsed_at)
                    VALUES (:url, :lesson_id, datetime('now'))
                """),
                {"url": url, "lesson_id": lesson_id},
            )
        session.commit()
    finally:
        session.close()
