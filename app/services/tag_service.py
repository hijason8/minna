"""
母標籤／子標籤：依 name 字母排序，供題庫分類與篩選。
"""
from typing import Any

from sqlalchemy import text

from app.database import get_connection


def list_parent_tags() -> list[dict[str, Any]]:
    """取得所有母標籤（parent_id 為 NULL），依 name 排序。相容舊欄位 tag_name。"""
    session = get_connection()
    try:
        rows = session.execute(
            text("SELECT id, COALESCE(name, tag_name) AS name FROM tags WHERE parent_id IS NULL ORDER BY COALESCE(name, tag_name)"),
        ).mappings().fetchall()
        return [{"id": r["id"], "name": r["name"] or ""} for r in rows]
    finally:
        session.close()


def list_child_tags(parent_id: int) -> list[dict[str, Any]]:
    """取得指定母標籤下的子標籤，依 name 排序。相容舊欄位 tag_name。"""
    session = get_connection()
    try:
        rows = session.execute(
            text("SELECT id, COALESCE(name, tag_name) AS name FROM tags WHERE parent_id = :pid ORDER BY COALESCE(name, tag_name)"),
            {"pid": parent_id},
        ).mappings().fetchall()
        return [{"id": r["id"], "name": r["name"] or ""} for r in rows]
    finally:
        session.close()


def create_parent_tag(name: str) -> dict[str, Any]:
    """新增母標籤。母標籤名稱不重複。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("母標籤名稱不可為空")
    session = get_connection()
    try:
        existing = session.execute(
            text("SELECT id FROM tags WHERE parent_id IS NULL AND (name = :name OR tag_name = :name)"),
            {"name": name},
        ).mappings().fetchone()
        if existing:
            return {"id": existing["id"], "name": name}
        r = session.execute(
            text("INSERT INTO tags (name, parent_id, tag_name) VALUES (:name, NULL, :name) RETURNING id"),
            {"name": name},
        )
        row = r.mappings().fetchone()
        session.commit()
        return {"id": row["id"], "name": name}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_child_tag(parent_id: int, name: str) -> dict[str, Any]:
    """在指定母標籤下新增子標籤。同一母下子標籤名稱不重複。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("子標籤名稱不可為空")
    session = get_connection()
    try:
        existing = session.execute(
            text("SELECT id FROM tags WHERE parent_id = :pid AND (name = :name OR tag_name = :name)"),
            {"pid": parent_id, "name": name},
        ).mappings().fetchone()
        if existing:
            return {"id": existing["id"], "name": name, "parent_id": parent_id}
        r = session.execute(
            text("INSERT INTO tags (name, parent_id, tag_name) VALUES (:name, :pid, :name) RETURNING id"),
            {"name": name, "pid": parent_id},
        )
        row = r.mappings().fetchone()
        session.commit()
        return {"id": row["id"], "name": name, "parent_id": parent_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_child_tag_ids_by_parent(parent_id: int) -> list[int]:
    """取得某母標籤下所有子標籤的 id 列表，供篩選用。"""
    session = get_connection()
    try:
        rows = session.execute(
            text("SELECT id FROM tags WHERE parent_id = :pid ORDER BY name"),
            {"pid": parent_id},
        ).mappings().fetchall()
        return [r["id"] for r in rows]
    finally:
        session.close()
