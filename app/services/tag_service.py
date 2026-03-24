"""
母標籤／子標籤：依 name 自然排序（數字部分按數值），供題庫分類與篩選。
可保持「第1課、第2課、第10課」等順序。
"""
import re
from typing import Any

from sqlalchemy import text

from app.database import get_connection


def _natural_sort_key(name: str) -> list[Any]:
    """將名稱拆成 [非數字, 數字, 非數字, ...] 作為排序鍵，使第1課 < 第2課 < 第10課。"""
    if not name:
        return [""]
    parts = re.split(r"(\d+)", name)
    out = []
    for i, p in enumerate(parts):
        if p.isdigit():
            out.append(int(p))
        else:
            out.append(p)
    return out


# 常見中文數字（單字），用於「第四課」「第五課」等，避免 Unicode 字碼順序（五在四字前）造成亂序
_CN_DIGIT: dict[str, int] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _tag_name_sort_key(name: str) -> tuple[Any, ...]:
    """
    題庫／章節名稱排序鍵：優先依「第」後的數字（阿拉伯或中文單字），再退回自然排序。
    使「第四課」在「第五課」之前，且「第4課」<「第10課」。
    """
    s = (name or "").strip()
    if not s:
        return (2, "")
    # 第4課、第10課（阿拉伯數字）
    m = re.match(r"^第\s*(\d+)", s)
    if m:
        return (0, int(m.group(1)), s)
    # 第四課、第五課（中文單字，常見於使用者自訂名稱）
    m2 = re.match(r"^第\s*([一二三四五六七八九十])\s*", s)
    if m2:
        ch = m2.group(1)
        if ch in _CN_DIGIT:
            return (0, _CN_DIGIT[ch], s)
    # 第十課、第十一課等簡化：僅處理「第十」開頭
    if re.match(r"^第\s*十", s):
        return (0, 10, s)
    # 其餘依自然排序（含英文、純數字片段）
    return (1, tuple(_natural_sort_key(s)))


def list_parent_tags() -> list[dict[str, Any]]:
    """取得所有母標籤（parent_id 為 NULL），依名稱合理排序。相容舊欄位 tag_name。"""
    session = get_connection()
    try:
        rows = session.execute(
            text("SELECT id, COALESCE(name, tag_name) AS name FROM tags WHERE parent_id IS NULL"),
        ).mappings().fetchall()
        items = [{"id": r["id"], "name": r["name"] or ""} for r in rows]
        items.sort(key=lambda x: _tag_name_sort_key(x["name"]))
        return items
    finally:
        session.close()


def list_child_tags(parent_id: int) -> list[dict[str, Any]]:
    """取得指定母標籤下的子標籤，依名稱合理排序。相容舊欄位 tag_name。"""
    session = get_connection()
    try:
        rows = session.execute(
            text("SELECT id, COALESCE(name, tag_name) AS name FROM tags WHERE parent_id = :pid"),
            {"pid": parent_id},
        ).mappings().fetchall()
        items = [{"id": r["id"], "name": r["name"] or ""} for r in rows]
        items.sort(key=lambda x: _tag_name_sort_key(x["name"]))
        return items
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
        parent_row = session.execute(
            text("SELECT id FROM tags WHERE id = :pid AND parent_id IS NULL"),
            {"pid": parent_id},
        ).mappings().fetchone()
        if not parent_row:
            raise ValueError("指定的題庫不存在或不是母標籤，請重新選擇題庫")
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
    except ValueError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise ValueError(f"寫入失敗：{e!s}") from e
    finally:
        session.close()


def rename_parent_tag(tag_id: int, new_name: str) -> dict[str, Any]:
    """重新命名母標籤（題庫）；同層名稱不可與其他題庫重複。"""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("名稱不可為空")
    session = get_connection()
    try:
        row = session.execute(
            text("SELECT id FROM tags WHERE id = :id AND parent_id IS NULL"),
            {"id": tag_id},
        ).mappings().fetchone()
        if not row:
            raise ValueError("找不到該題庫或不是母標籤")
        dup = session.execute(
            text(
                "SELECT id FROM tags WHERE parent_id IS NULL AND id != :id AND (name = :name OR tag_name = :name)"
            ),
            {"id": tag_id, "name": new_name},
        ).mappings().fetchone()
        if dup:
            raise ValueError("已有其他題庫使用此名稱")
        session.execute(
            text("UPDATE tags SET name = :n, tag_name = :n WHERE id = :id"),
            {"n": new_name, "id": tag_id},
        )
        session.commit()
        return {"id": tag_id, "name": new_name}
    except ValueError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise ValueError(f"更新失敗：{e!s}") from e
    finally:
        session.close()


def rename_child_tag(tag_id: int, new_name: str) -> dict[str, Any]:
    """重新命名子標籤（章節）；同一題庫下名稱不可重複。"""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("名稱不可為空")
    session = get_connection()
    try:
        row = session.execute(
            text("SELECT id, parent_id FROM tags WHERE id = :id AND parent_id IS NOT NULL"),
            {"id": tag_id},
        ).mappings().fetchone()
        if not row:
            raise ValueError("找不到該章節或不是子標籤")
        pid = row["parent_id"]
        dup = session.execute(
            text(
                "SELECT id FROM tags WHERE parent_id = :pid AND id != :id AND (name = :name OR tag_name = :name)"
            ),
            {"pid": pid, "id": tag_id, "name": new_name},
        ).mappings().fetchone()
        if dup:
            raise ValueError("此題庫下已有同名章節")
        session.execute(
            text("UPDATE tags SET name = :n, tag_name = :n WHERE id = :id"),
            {"n": new_name, "id": tag_id},
        )
        session.commit()
        return {"id": tag_id, "name": new_name, "parent_id": pid}
    except ValueError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise ValueError(f"更新失敗：{e!s}") from e
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


def delete_child_tag(tag_id: int) -> None:
    """刪除章節（子標籤）。先將 vocabulary / phrases 的 tag_id 清空，再刪除標籤。"""
    session = get_connection()
    try:
        session.execute(text("UPDATE vocabulary SET tag_id = NULL WHERE tag_id = :id"), {"id": tag_id})
        session.execute(text("UPDATE phrases SET tag_id = NULL WHERE tag_id = :id"), {"id": tag_id})
        session.execute(text("DELETE FROM tags WHERE id = :id AND parent_id IS NOT NULL"), {"id": tag_id})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_parent_tag(tag_id: int) -> None:
    """刪除題庫（母標籤）。先清空直接指向母標籤的單字／短語，再清空子標籤關聯、刪除子與母。"""
    session = get_connection()
    try:
        session.execute(text("UPDATE vocabulary SET tag_id = NULL WHERE tag_id = :id"), {"id": tag_id})
        session.execute(text("UPDATE phrases SET tag_id = NULL WHERE tag_id = :id"), {"id": tag_id})
        rows = session.execute(
            text("SELECT id FROM tags WHERE parent_id = :pid"),
            {"pid": tag_id},
        ).mappings().fetchall()
        for r in rows:
            cid = r["id"]
            session.execute(text("UPDATE vocabulary SET tag_id = NULL WHERE tag_id = :id"), {"id": cid})
            session.execute(text("UPDATE phrases SET tag_id = NULL WHERE tag_id = :id"), {"id": cid})
        session.execute(text("DELETE FROM tags WHERE parent_id = :pid"), {"pid": tag_id})
        session.execute(text("DELETE FROM tags WHERE id = :id AND parent_id IS NULL"), {"id": tag_id})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
