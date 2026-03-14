"""
大家的日本語智慧學習 APP - FastAPI 入口。
Phase 1：資料庫初始化、URL 去重判斷、音檔路徑檢查。
"""
from contextlib import asynccontextmanager
from typing import Optional

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sqlalchemy import text

from app.config import Settings
from app.database import init_db, get_db_path, get_connection
from app.services.url_dedup import (
    if_url_exists_then_skip_ai_call,
    count_parsed_today,
    can_parse_more_today,
)
from app.services.audio_storage import (
    get_audio_path_if_exists,
    get_vocabulary_audio_path,
    audio_file_exists,
    ensure_audio_cache_dir,
)
from app.services.tts import get_or_create_audio
from app.services.vocabulary_import import import_vocabulary_json
from app.services.vocabulary_list_parser import (
    parse_vocabulary_list,
    split_merged_vocab_phrase,
    get_format_instruction,
    get_standard_llm_prompt,
)
from app.services.tag_service import (
    list_parent_tags,
    list_child_tags,
    create_parent_tag,
    create_child_tag,
    delete_child_tag,
    delete_parent_tag,
)
from app.services.flashcards import (
    get_deck,
    get_next_card,
    record_review,
    CardType,
    Outcome,
)
from app.services.phrase_import import import_phrases_json
from app.services.phrases_flashcards import (
    get_next_phrase,
    get_phrase_deck,
    record_phrase_review,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用啟動時初始化資料庫與音檔目錄。"""
    init_db()
    ensure_audio_cache_dir()
    yield
    # 關閉時可做清理（可選）


app = FastAPI(
    title="大家的日本語智慧學習 API",
    description="YouTube 驅動的單字/慣用語學習與抽卡複習",
    lifespan=lifespan,
)

# 允許前端從瀏覽器呼叫 API（同源或 localhost）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端靜態檔（單字表、清單、抽卡 UI）
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """首頁：導向前端；API 健康檢查可改用 /health。"""
    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
        return RedirectResponse(url="/static/index.html")
    return {"status": "ok", "app": "大家的日本語智慧學習 APP"}


@app.get("/health")
async def health():
    """API 健康檢查。"""
    return {"status": "ok"}


@app.get("/api/url/check")
async def check_url(
    url: str = Query(..., description="YouTube 影片網址"),
):
    """
    檢查 URL 是否已存在於本地；若存在則應跳過 AI 呼叫。
    同時檢查今日是否還可解析新網址（每日上限）。
    """
    should_skip, existing_lesson_id = if_url_exists_then_skip_ai_call(url)
    return {
        "youtube_url": url.strip(),
        "should_skip_ai_call": should_skip,
        "existing_lesson_id": existing_lesson_id,
        "daily_parsed_count": count_parsed_today(),
        "daily_limit": Settings().daily_parse_limit,
        "can_parse_more_today": can_parse_more_today(),
    }


@app.get("/api/audio/check")
async def check_audio(
    vocabulary_id: int = Query(..., description="單字/慣用語 id"),
    kana: str = Query(..., description="讀音，用於產生檔名"),
):
    """
    檢查該詞的 TTS 音檔是否已存在於本地。
    若存在則回傳本地路徑，前端可直接播放，不需呼叫 TTS API。
    """
    path = get_audio_path_if_exists(vocabulary_id, kana)
    exists = audio_file_exists(vocabulary_id, kana)
    expected_path = get_vocabulary_audio_path(vocabulary_id, kana)
    return {
        "vocabulary_id": vocabulary_id,
        "kana": kana,
        "audio_exists": exists,
        "local_path": str(path) if path else None,
        "expected_path": str(expected_path),
    }


@app.get("/api/audio/play/{vocabulary_id}")
async def audio_play(
    vocabulary_id: int,
    use_system_tts: bool = Query(False, description="True=不生成 MP3，回傳 kana 供前端用瀏覽器/系統 TTS 播放（零成本）"),
):
    """
    取得該單字的語音並回傳 MP3 供播放。
    邏輯：先查本地快取 -> 有則直接回傳 -> 無則呼叫 TTS 生成並存檔後回傳。
    若 use_system_tts=true，改回傳 JSON { kana, use_system_tts: true }，由前端用 speechSynthesis 等播放。
    """
    session = get_connection()
    try:
        row = session.execute(text("SELECT id, kana FROM vocabulary WHERE id = :id"), {"id": vocabulary_id}).mappings().fetchone()
    finally:
        session.close()
    if not row:
        raise HTTPException(status_code=404, detail="找不到該單字")
    kana = row["kana"] or ""
    if not kana:
        raise HTTPException(status_code=400, detail="該單字無讀音資料")
    if use_system_tts:
        return {"vocabulary_id": vocabulary_id, "kana": kana, "use_system_tts": True}
    path = get_or_create_audio(vocabulary_id, kana)
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


@app.get("/api/audio/phrase/{phrase_id}")
async def audio_phrase(phrase_id: int):
    """取得該短語的 TTS 語音並回傳 MP3。"""
    from app.services.tts import get_or_create_phrase_audio
    try:
        path = get_or_create_phrase_audio(phrase_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


@app.get("/api/config")
async def get_config():
    """回傳前端所需之設定（如每日上限、音檔目錄等）。"""
    return {
        "daily_parse_limit": Settings().daily_parse_limit,
        "audio_cache_dir": str(ensure_audio_cache_dir()),
        "database_path": str(get_db_path()),
    }


# --- 單字表格式解析（網頁 LLM 產出 → 結構化 JSON，零 Token）---

# --- 每課文法重點（儲存／讀取）---

class GrammarContentBody(BaseModel):
    """儲存文法重點的請求體。"""
    content: str = ""


def _ensure_lesson_exists(session, lesson_id: int) -> None:
    """若課程不存在則建立手動匯入用 stub。"""
    row = session.execute(text("SELECT id FROM lessons WHERE id = :id"), {"id": lesson_id}).mappings().fetchone()
    if row:
        return
    session.execute(
        text("INSERT INTO lessons (id, youtube_url, lesson_name, created_at) VALUES (:id, :url, :name, :created_at)"),
        {"id": lesson_id, "url": f"manual://lesson-{lesson_id}", "name": f"手動匯入 Lesson {lesson_id}", "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")},
    )


@app.get("/api/lessons")
async def list_lessons():
    """取得所有課程列表（id, name），供文法頁下拉選單使用。"""
    session = get_connection()
    try:
        rows = session.execute(text("SELECT id, lesson_name FROM lessons ORDER BY id ASC")).mappings().fetchall()
        return {
            "items": [
                {"id": r["id"], "name": (r["lesson_name"] or "").strip() or f"第{r['id']}課"}
                for r in rows
            ]
        }
    finally:
        session.close()


@app.get("/api/grammar")
async def get_all_grammar():
    """取得所有課程的文法重點，依課程編號先後排序。"""
    session = get_connection()
    try:
        rows = session.execute(text("SELECT id, lesson_name, grammar_notes FROM lessons ORDER BY id ASC")).mappings().fetchall()
        return {
            "items": [
                {
                    "lesson_id": r["id"],
                    "lesson_name": (r["lesson_name"] or "").strip() or None,
                    "content": (r["grammar_notes"] or "").strip(),
                }
                for r in rows
            ]
        }
    finally:
        session.close()


@app.get("/api/lessons/{lesson_id:int}/grammar")
async def get_lesson_grammar(lesson_id: int):
    """取得指定課程的文法重點內容。"""
    session = get_connection()
    try:
        row = session.execute(text("SELECT id, grammar_notes FROM lessons WHERE id = :id"), {"id": lesson_id}).mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="課程不存在")
        return {
            "lesson_id": lesson_id,
            "content": (row["grammar_notes"] or "").strip(),
        }
    finally:
        session.close()


@app.put("/api/lessons/{lesson_id:int}/grammar")
async def save_lesson_grammar(lesson_id: int, body: GrammarContentBody):
    """儲存指定課程的文法重點；若課程不存在會自動建立 stub。"""
    if lesson_id < 1:
        raise HTTPException(status_code=400, detail="lesson_id 須為正整數")
    session = get_connection()
    try:
        _ensure_lesson_exists(session, lesson_id)
        session.execute(
            text("UPDATE lessons SET grammar_notes = :content WHERE id = :id"),
            {"content": body.content or "", "id": lesson_id},
        )
        session.commit()
        return {"lesson_id": lesson_id, "saved": True}
    finally:
        session.close()


# --- 單字表格式解析（網頁 LLM 產出 → 結構化 JSON，零 Token）---

@app.get("/api/vocabulary/format")
async def vocabulary_format_instruction():
    """
    回傳「單字表格式說明」與「標準 LLM 提示詞」，
    可貼到網頁版 LLM 提示裡，讓輸出每次都能被本 App 正確解析。
    """
    return {
        "instruction": get_format_instruction(),
        "format_summary": "每行: 日文(Tab/|/,/)讀音(Tab/|/,/)意思 [*星標]",
        "standard_llm_prompt": get_standard_llm_prompt(),
    }


class ParseTextBody(BaseModel):
    """單字表純文字 + 預設課程 id。"""
    text: str = ""
    lesson_id: int = 1


class ImportWithTagBody(BaseModel):
    """合併匯入：單字／短語共用貼文，依同一子標籤寫入（由母標籤決定題庫類型）。"""
    text: str = ""
    tag_id: int = Field(..., description="所屬子標籤 id，單字與短語皆寫入此題庫")


@app.get("/api/tags/parents")
async def api_list_parent_tags():
    """取得所有母標籤，依 name 排序。"""
    return {"items": list_parent_tags()}


@app.get("/api/tags/children")
async def api_list_child_tags(parent_id: int = Query(..., description="母標籤 id")):
    """取得指定母標籤下的子標籤，依 name 排序。"""
    return {"items": list_child_tags(parent_id)}


@app.post("/api/tags/parents")
async def api_create_parent_tag(body: dict):
    """新增母標籤。body: {"name": "單字"}"""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不可為空")
    try:
        return create_parent_tag(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/tags/children")
async def api_create_child_tag(body: dict):
    """在母標籤下新增子標籤。body: {"parent_id": 1, "name": "第3課"}"""
    parent_id = body.get("parent_id")
    name = (body.get("name") or "").strip()
    if parent_id is None:
        raise HTTPException(status_code=400, detail="parent_id 必填")
    if not name:
        raise HTTPException(status_code=400, detail="name 不可為空")
    try:
        return create_child_tag(int(parent_id), name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/tags/children/{tag_id}")
async def api_delete_child_tag(tag_id: int):
    """刪除章節（子標籤）。關聯的單字／短語會改為無標籤。"""
    try:
        delete_child_tag(tag_id)
        return {"deleted": tag_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/tags/parents/{tag_id}")
async def api_delete_parent_tag(tag_id: int):
    """刪除題庫（母標籤）及其下所有章節。關聯的單字／短語會改為無標籤。"""
    try:
        delete_parent_tag(tag_id)
        return {"deleted": tag_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ImportMergedParseBody(BaseModel):
    """僅解析題庫貼文，不寫入 DB。"""
    text: str = ""


@app.post("/api/import-merged/parse")
async def import_merged_parse(body: ImportMergedParseBody):
    """
    解析題庫貼文：上方單字、下方短語、中間空一行。
    回傳區分為 vocab（上方）、phrase（下方）兩部分，供預覽與匯入前確認。
    """
    vocab_text, phrase_text = split_merged_vocab_phrase(body.text or "")
    vocab_items = []
    phrase_items = []
    try:
        if vocab_text:
            vocab_items, _ = parse_vocabulary_list(vocab_text, default_lesson_id=1)
        if phrase_text:
            phrase_items, _ = parse_vocabulary_list(phrase_text, default_lesson_id=1)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失敗：{str(e)}")
    return {
        "vocab": {"items": vocab_items, "count": len(vocab_items)},
        "phrase": {"items": phrase_items, "count": len(phrase_items)},
    }


@app.post("/api/import-merged")
async def import_merged_from_text(body: ImportWithTagBody):
    """
    新增題庫：上方貼單字、下方貼短語，中間空一行。
    單字與短語皆寫入同一子標籤（由母標籤決定題庫）。
    """
    vocab_text, phrase_text = split_merged_vocab_phrase(body.text or "")
    vocab_items = []
    phrase_items = []
    try:
        if vocab_text:
            vocab_items, _ = parse_vocabulary_list(vocab_text, default_lesson_id=1)
        if phrase_text:
            phrase_items, _ = parse_vocabulary_list(phrase_text, default_lesson_id=1)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失敗：{str(e)}")
    if not vocab_items and not phrase_items:
        raise HTTPException(status_code=400, detail="解析後沒有有效單字或短語，請檢查格式（上方單字、下方短語、中間空一行）")
    if phrase_text.strip() and not phrase_items:
        raise HTTPException(status_code=400, detail="下方短語區塊解析後無有效筆數，請確認每行格式為：假名|漢字（可空）|中文")
    out = {}
    try:
        if vocab_items:
            r = import_vocabulary_json(vocab_items, tag_id=body.tag_id)
            out["vocabulary"] = r
        if phrase_items:
            r = import_phrases_json(phrase_items, tag_id=body.tag_id)
            out["phrases"] = r
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入資料庫失敗：{str(e)}")
    return {"tag_id": body.tag_id, **out}


@app.post("/api/vocabulary/parse")
async def vocabulary_parse_text(body: ParseTextBody):
    """
    將「單字表格式」純文字解析為結構化 JSON，不寫入 DB。
    可先呼叫此 API 預覽，確認無誤再呼叫 /import 或 /import-from-text。
    """
    try:
        items, lesson_id = parse_vocabulary_list(
            body.text or "", default_lesson_id=body.lesson_id
        )
        return {"lesson_id": lesson_id, "items": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析時發生錯誤：{str(e)}")


@app.post("/api/vocabulary/import-from-text")
async def vocabulary_import_from_text(body: ParseTextBody):
    """
    單字表純文字 → 解析 → 直接寫入 DB（等同 parse + import 一鍵完成）。
    """
    try:
        items, _ = parse_vocabulary_list(body.text, default_lesson_id=body.lesson_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失敗：{str(e)}")
    if not items:
        raise HTTPException(status_code=400, detail="解析後沒有有效單字，請檢查格式")
    lesson_id = body.lesson_id
    for it in items:
        it["lesson_id"] = lesson_id
    try:
        result = import_vocabulary_json(items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入資料庫失敗：{str(e)}")
    return {"lesson_id": lesson_id, **result}


# --- 手動貼入 JSON 匯入（測試抽卡用）---

class VocabularyImportItem(BaseModel):
    """單筆匯入單字／慣用語。"""
    kanji: str | None = None
    kana: str
    meaning: str
    lesson_id: int
    is_starred: bool = False


@app.post("/api/vocabulary/import")
async def vocabulary_import(items: list[VocabularyImportItem]):
    """
    手動貼入 JSON 陣列，將單字／慣用語寫入本地資料庫。
    若對應 lesson_id 不存在，會自動建立「手動匯入 Lesson N」的 stub 課程。
    """
    if not items:
        raise HTTPException(status_code=400, detail="請提供至少一筆單字")
    raw = [i.model_dump() for i in items]
    result = import_vocabulary_json(raw)
    return result


@app.get("/api/vocabulary")
async def list_vocabulary(
    lesson_id: int | None = Query(None, description="篩選課程 id"),
    tag_id: int | None = Query(None, description="篩選子標籤 id"),
    parent_tag_id: int | None = Query(None, description="篩選母標籤 id（該母下所有子標籤）"),
    starred_only: bool = Query(False, description="僅列出 is_starred"),
):
    """列出已匯入的單字／慣用語。優先依 tag_id / parent_tag_id，其次 lesson_id。"""
    conditions = []
    params = {}
    if tag_id is not None:
        conditions.append("tag_id = :tag_id")
        params["tag_id"] = tag_id
    elif parent_tag_id is not None:
        conditions.append("tag_id IN (SELECT id FROM tags WHERE parent_id = :parent_tag_id)")
        params["parent_tag_id"] = parent_tag_id
    elif lesson_id is not None:
        conditions.append("lesson_id = :lesson_id")
        params["lesson_id"] = lesson_id
    if starred_only:
        conditions.append("is_starred = 1")
        conditions.append("(mastered IS NULL OR mastered = 0)")
    where = " AND ".join(conditions) if conditions else "1=1"
    session = get_connection()
    try:
        rows = session.execute(
            text(f"SELECT id, lesson_id, COALESCE(tag_id, 0) AS tag_id, kanji, kana, meaning, is_starred, COALESCE(mastered, 0) AS mastered FROM vocabulary WHERE {where} ORDER BY id"),
            params,
        ).mappings().fetchall()
        return {
            "items": [
                {
                    "id": r["id"],
                    "lesson_id": r["lesson_id"],
                    "tag_id": r["tag_id"],
                    "kanji": r["kanji"],
                    "kana": r["kana"],
                    "meaning": r["meaning"],
                    "is_starred": bool(r["is_starred"]),
                    "mastered": bool(r["mastered"]),
                }
                for r in rows
            ]
        }
    finally:
        session.close()


class VocabularyPatchBody(BaseModel):
    """更新單字星標、淡化或所屬章節（tag_id）。"""
    is_starred: Optional[bool] = None
    mastered: Optional[bool] = None
    tag_id: Optional[int] = None


@app.patch("/api/vocabulary/{vocabulary_id}")
async def patch_vocabulary(vocabulary_id: int, body: VocabularyPatchBody):
    """更新單字的星標、淡化或所屬章節（移動至其他子標籤）。"""
    session = get_connection()
    try:
        row = session.execute(text("SELECT id FROM vocabulary WHERE id = :id"), {"id": vocabulary_id}).mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到該單字")
        if body.tag_id is not None:
            tag_row = session.execute(
                text("SELECT id FROM tags WHERE id = :id AND parent_id IS NOT NULL"),
                {"id": body.tag_id},
            ).mappings().fetchone()
            if not tag_row:
                raise HTTPException(status_code=400, detail="指定的章節不存在或不是子標籤")
            session.execute(text("UPDATE vocabulary SET tag_id = :tag_id WHERE id = :id"), {"tag_id": body.tag_id, "id": vocabulary_id})
        if body.is_starred is not None:
            val = 1 if body.is_starred else 0
            session.execute(
                text("UPDATE vocabulary SET is_starred = :val, mastered = CASE WHEN :starred THEN 0 ELSE mastered END WHERE id = :id"),
                {"val": val, "starred": bool(body.is_starred), "id": vocabulary_id},
            )
        if body.mastered is not None:
            val = 1 if body.mastered else 0
            session.execute(
                text("UPDATE vocabulary SET mastered = :val, is_starred = CASE WHEN :mastered THEN 0 ELSE is_starred END WHERE id = :id"),
                {"val": val, "mastered": bool(body.mastered), "id": vocabulary_id},
            )
        session.commit()
        return {"id": vocabulary_id, "updated": True}
    finally:
        session.close()


@app.delete("/api/vocabulary/{vocabulary_id}")
async def delete_vocabulary(vocabulary_id: int):
    """刪除一筆單字（匯入錯誤時可刪除後重新匯入）。"""
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM vocabulary WHERE id = :id"), {"id": vocabulary_id})
        session.commit()
        if r.rowcount == 0:
            raise HTTPException(status_code=404, detail="找不到該單字")
        return {"deleted": vocabulary_id}
    finally:
        session.close()


@app.delete("/api/vocabulary/lesson/{lesson_id}")
async def delete_vocabulary_by_lesson(lesson_id: int):
    """刪除該課程下全部單字（匯入錯誤時可整課刪除後重新匯入）。"""
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM vocabulary WHERE lesson_id = :lesson_id"), {"lesson_id": lesson_id})
        session.commit()
        return {"deleted_count": r.rowcount, "lesson_id": lesson_id}
    finally:
        session.close()


@app.delete("/api/vocabulary/tag/{tag_id}")
async def delete_vocabulary_by_tag(tag_id: int):
    """刪除該子標籤下全部單字。"""
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM vocabulary WHERE tag_id = :tag_id"), {"tag_id": tag_id})
        session.commit()
        return {"deleted_count": r.rowcount, "tag_id": tag_id}
    finally:
        session.close()


@app.delete("/api/vocabulary/legacy")
async def delete_vocabulary_legacy():
    """刪除母標籤規則前建立的單字（tag_id 為 NULL 的舊資料）。"""
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM vocabulary WHERE tag_id IS NULL"))
        session.commit()
        return {"deleted_count": r.rowcount}
    finally:
        session.close()


# --- 短語（格式同單字三欄，句子較長）---

class PhraseParseBody(BaseModel):
    text: str = ""
    lesson_id: int = 1


@app.post("/api/phrases/import-from-text")
async def phrases_import_from_text(body: PhraseParseBody):
    """短語純文字 → 解析（同單字格式）→ 寫入 phrases 表。"""
    try:
        items, _ = parse_vocabulary_list(body.text or "", default_lesson_id=body.lesson_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失敗：{str(e)}")
    if not items:
        raise HTTPException(status_code=400, detail="解析後沒有有效短語，請檢查格式")
    lesson_id = body.lesson_id
    for it in items:
        it["lesson_id"] = lesson_id
    try:
        result = import_phrases_json(items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入資料庫失敗：{str(e)}")
    return {"lesson_id": lesson_id, **result}


@app.get("/api/phrases")
async def list_phrases(
    lesson_id: int | None = Query(None),
    tag_id: int | None = Query(None),
    parent_tag_id: int | None = Query(None),
    starred_only: bool = Query(False),
):
    """列出短語。優先依 tag_id / parent_tag_id，其次 lesson_id。"""
    conditions = []
    params = {}
    if tag_id is not None:
        conditions.append("tag_id = :tag_id")
        params["tag_id"] = tag_id
    elif parent_tag_id is not None:
        conditions.append("tag_id IN (SELECT id FROM tags WHERE parent_id = :parent_tag_id)")
        params["parent_tag_id"] = parent_tag_id
    elif lesson_id is not None:
        conditions.append("lesson_id = :lesson_id")
        params["lesson_id"] = lesson_id
    if starred_only:
        conditions.append("is_starred = 1")
        conditions.append("(mastered IS NULL OR mastered = 0)")
    where = " AND ".join(conditions) if conditions else "1=1"
    session = get_connection()
    try:
        rows = session.execute(
            text(f"SELECT id, lesson_id, COALESCE(tag_id, 0) AS tag_id, kanji, kana, meaning, is_starred, COALESCE(mastered, 0) AS mastered FROM phrases WHERE {where} ORDER BY id"),
            params,
        ).mappings().fetchall()
        return {
            "items": [
                {
                    "id": r["id"],
                    "lesson_id": r["lesson_id"],
                    "tag_id": r["tag_id"],
                    "kanji": r["kanji"],
                    "kana": r["kana"],
                    "meaning": r["meaning"],
                    "is_starred": bool(r["is_starred"]),
                    "mastered": bool(r["mastered"]),
                }
                for r in rows
            ]
        }
    finally:
        session.close()


class PhrasePatchBody(BaseModel):
    is_starred: Optional[bool] = None
    mastered: Optional[bool] = None
    tag_id: Optional[int] = None


@app.patch("/api/phrases/{phrase_id}")
async def patch_phrase(phrase_id: int, body: PhrasePatchBody):
    """更新短語星標、淡化或所屬章節（移動至其他子標籤）；星標與淡化互斥。"""
    session = get_connection()
    try:
        row = session.execute(text("SELECT id FROM phrases WHERE id = :id"), {"id": phrase_id}).mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到該短語")
        if body.tag_id is not None:
            tag_row = session.execute(
                text("SELECT id FROM tags WHERE id = :id AND parent_id IS NOT NULL"),
                {"id": body.tag_id},
            ).mappings().fetchone()
            if not tag_row:
                raise HTTPException(status_code=400, detail="指定的章節不存在或不是子標籤")
            session.execute(text("UPDATE phrases SET tag_id = :tag_id WHERE id = :id"), {"tag_id": body.tag_id, "id": phrase_id})
        if body.is_starred is not None:
            val = 1 if body.is_starred else 0
            session.execute(
                text("UPDATE phrases SET is_starred = :val, mastered = CASE WHEN :starred THEN 0 ELSE mastered END WHERE id = :id"),
                {"val": val, "starred": bool(body.is_starred), "id": phrase_id},
            )
        if body.mastered is not None:
            val = 1 if body.mastered else 0
            session.execute(
                text("UPDATE phrases SET mastered = :val, is_starred = CASE WHEN :mastered THEN 0 ELSE is_starred END WHERE id = :id"),
                {"val": val, "mastered": bool(body.mastered), "id": phrase_id},
            )
        session.commit()
        return {"id": phrase_id, "updated": True}
    finally:
        session.close()


@app.delete("/api/phrases/{phrase_id}")
async def delete_phrase(phrase_id: int):
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM phrases WHERE id = :id"), {"id": phrase_id})
        session.commit()
        if r.rowcount == 0:
            raise HTTPException(status_code=404, detail="找不到該短語")
        return {"deleted": phrase_id}
    finally:
        session.close()


@app.delete("/api/phrases/lesson/{lesson_id}")
async def delete_phrases_by_lesson(lesson_id: int):
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM phrases WHERE lesson_id = :lesson_id"), {"lesson_id": lesson_id})
        session.commit()
        return {"deleted_count": r.rowcount, "lesson_id": lesson_id}
    finally:
        session.close()


@app.delete("/api/phrases/tag/{tag_id}")
async def delete_phrases_by_tag(tag_id: int):
    """刪除該子標籤下全部短語。"""
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM phrases WHERE tag_id = :tag_id"), {"tag_id": tag_id})
        session.commit()
        return {"deleted_count": r.rowcount, "tag_id": tag_id}
    finally:
        session.close()


@app.delete("/api/phrases/legacy")
async def delete_phrases_legacy():
    """刪除母標籤規則前建立的短語（tag_id 為 NULL 的舊資料）。"""
    session = get_connection()
    try:
        r = session.execute(text("DELETE FROM phrases WHERE tag_id IS NULL"))
        session.commit()
        return {"deleted_count": r.rowcount}
    finally:
        session.close()


@app.get("/api/phrases/deck")
async def api_get_phrase_deck(
    lesson_id: int | None = Query(None),
    tag_id: int | None = Query(None),
    parent_tag_id: int | None = Query(None),
    starred_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=200),
):
    """取得未淡化的短語牌組（隨機 limit 張）。優先依 tag_id / parent_tag_id。"""
    cards = get_phrase_deck(lesson_id=lesson_id, starred_only=starred_only, tag_id=tag_id, parent_tag_id=parent_tag_id, limit=limit)
    return {"cards": cards, "count": len(cards)}


@app.get("/api/phrases/next")
async def api_get_next_phrase(
    lesson_id: int | None = Query(None),
    starred_only: bool = Query(False),
    exclude_id: int | None = Query(None),
):
    card = get_next_phrase(
        lesson_id=lesson_id,
        starred_only=starred_only,
        exclude_phrase_id=exclude_id,
    )
    if card is None:
        raise HTTPException(status_code=404, detail="目前沒有可複習的短語")
    return card


class PhraseReviewBody(BaseModel):
    phrase_id: int
    outcome: Outcome


@app.post("/api/phrases/review")
async def api_phrase_review(body: PhraseReviewBody):
    return record_phrase_review(body.phrase_id, body.outcome)


# --- 單字（困難）---

@app.get("/api/vocabulary/starred")
async def list_starred_vocabulary():
    """
    困難單字：統整所有 is_starred = true 的單字，供強化訓練或清單檢視。
    """
    session = get_connection()
    try:
        rows = session.execute(
            text("SELECT id, lesson_id, kanji, kana, meaning, is_starred, COALESCE(mastered, 0) AS mastered FROM vocabulary WHERE is_starred = 1 ORDER BY id")
        ).mappings().fetchall()
        return {
            "items": [
                {
                    "id": r["id"],
                    "lesson_id": r["lesson_id"],
                    "kanji": r["kanji"],
                    "kana": r["kana"],
                    "meaning": r["meaning"],
                    "is_starred": True,
                    "mastered": bool(r["mastered"]),
                }
                for r in rows
            ],
            "count": len(rows),
        }
    finally:
        session.close()


# --- 抽卡複習（SRS）---

@app.get("/api/flashcards")
async def api_get_deck(
    lesson_id: int | None = Query(None, description="篩選課程 id"),
    tag_id: int | None = Query(None, description="篩選子標籤 id"),
    parent_tag_id: int | None = Query(None, description="篩選母標籤 id"),
    starred_only: bool = Query(False, description="僅星標＝強化訓練單元"),
    card_type: CardType = Query("ja_to_zh", description="ja_to_zh | zh_to_ja | listening"),
    limit: int = Query(50, ge=1, le=200),
):
    """取得牌組（多張卡）。優先依 tag_id / parent_tag_id，其次 lesson_id。"""
    cards = get_deck(lesson_id=lesson_id, starred_only=starred_only, tag_id=tag_id, parent_tag_id=parent_tag_id, card_type=card_type, limit=limit)
    return {"cards": cards, "count": len(cards)}


@app.get("/api/flashcards/next")
async def api_get_next_card(
    lesson_id: int | None = Query(None),
    starred_only: bool = Query(False, description="僅星標＝強化訓練單元"),
    card_type: CardType = Query("ja_to_zh"),
    exclude_id: int | None = Query(None, description="排除此 vocabulary_id，避免剛答完「困難」又抽到同一張"),
):
    """取得下一張待複習的卡（到期優先）。"""
    card = get_next_card(
        lesson_id=lesson_id,
        starred_only=starred_only,
        card_type=card_type,
        exclude_vocabulary_id=exclude_id,
    )
    if card is None:
        raise HTTPException(status_code=404, detail="目前沒有可複習的卡片")
    return card


class ReviewBody(BaseModel):
    """複習結果。"""
    vocabulary_id: int
    outcome: Outcome


@app.post("/api/flashcards/review")
async def api_record_review(body: ReviewBody):
    """記錄複習結果（again / good / easy），更新下次複習時間。"""
    result = record_review(body.vocabulary_id, body.outcome)
    return result
