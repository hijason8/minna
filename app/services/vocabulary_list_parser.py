"""
單字表文字格式解析：將「網頁版 LLM 產生的單字表」轉成結構化 JSON。
不呼叫任何 LLM API，零 Token 消耗；格式由你與 LLM 約定即可。
"""
import re
from typing import Any

# 第四欄（選填）若為以下任一則視為「星標／難點」
STARRED_MARKS = frozenset({"*", "★", "⭐", "1", "true", "是", "星", "難", "y", "yes"})


def _split_line(line: str) -> list[str] | None:
    """
    將一行依 Tab 或 | 切開，共 3 欄（可含空欄，如 ロビー||大廳）。
    保留空字串以正確對應第 2 欄留空。
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # 先試 Tab（3～4 欄，保留空欄；maxsplit=3 可得最多 4 段）
    if "\t" in line:
        parts = [p.strip() for p in line.split("\t", maxsplit=3)]
        if len(parts) >= 3:
            return parts
    # 再試 |（支援 || 表示第二欄空，最多 4 段）
    if "|" in line:
        parts = re.split(r"\s*\|\s*", line, maxsplit=3)
        parts = [p.strip() for p in parts]
        if len(parts) >= 3:
            return parts
    return None


def _is_header_row(parts: list[str]) -> bool:
    """判斷是否為表頭列（跳過不當成單字）。"""
    if len(parts) < 3:
        return False
    c0 = (parts[0] or "").strip().lower()
    c1 = (parts[1] or "").strip().lower()
    c2 = (parts[2] or "").strip().lower()
    if c0 in ("五十音", "kana", "讀音", "假名", "reading", "かな"):
        return True
    if c1 in ("日文", "漢字", "kanji", "單字", "word"):
        return True
    if c2 in ("中文", "意思", "解釋", "meaning"):
        return True
    return False


def _parse_lesson_id_line(line: str) -> int | None:
    """若為 "lesson_id: 3" 或 "lesson_id:3" 則回傳數字，否則 None。"""
    m = re.match(r"lesson_id\s*:\s*(\d+)", line.strip(), re.I)
    return int(m.group(1)) if m else None


def parse_vocabulary_list(text: str, default_lesson_id: int = 1) -> tuple[list[dict[str, Any]], int]:
    """
    將單字表純文字解析為結構化列表。
    :param text: 網頁 LLM 產生的單字表（見下方格式說明）
    :param default_lesson_id: 未在文中指定 lesson_id 時使用
    :return: (items, lesson_id)，items 為 [{"kanji","kana","meaning","is_starred"}, ...]
    """
    lesson_id = default_lesson_id
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 可選：第一行指定 lesson_id
        lid = _parse_lesson_id_line(line)
        if lid is not None:
            lesson_id = lid
            continue
        parts = _split_line(line)
        if not parts:
            continue
        if _is_header_row(parts):
            continue
        # 格式：第 1 欄五十音、第 2 欄日文漢字、第 3 欄中文解釋
        kana = (parts[0] or "").strip()
        kanji = (parts[1] or "").strip() or None
        meaning = (parts[2] or "").strip()
        if not kana or not meaning:
            continue
        # 日文漢字若與五十音相同則留白（不重複顯示）
        if kanji and kanji == kana:
            kanji = None
        # 第四欄：是否星標
        is_starred = False
        if len(parts) >= 4:
            mark = (parts[3] or "").strip().lower()
            if mark in STARRED_MARKS:
                is_starred = True
        items.append({
            "kanji": kanji,
            "kana": kana,
            "meaning": meaning,
            "lesson_id": lesson_id,
            "is_starred": is_starred,
        })
    return items, lesson_id


def get_format_instruction() -> str:
    """回傳給 LLM 或使用者的「單字表格式說明」，與前端提示詞一致。"""
    return """【輸出規則】
每行一筆，嚴格使用 Tab（或 |）分隔，共 3 欄。
第 1 欄：純假名（五十音）。
第 2 欄：日文漢字（若該單字無漢字或與假名相同，請留空）。
第 3 欄：中文解釋。

【嚴格禁止】不要表頭、不要 Markdown、不要解釋性文字、不要序號。
【首行限定】僅輸出 lesson_id: [數字]。

範例：
lesson_id: 3
ロビー||大廳
へや|部屋|房間
トイレ||廁所
おてあらい|お手洗い|洗手間（較委婉）
"""


# 標準提示詞：與前端「貼給 Web LLM 的提示詞」一致，供 API 複製用
STANDARD_LLM_PROMPT = """【輸出規則】
每行一筆，嚴格使用 Tab（或 |）分隔，共 3 欄。
第 1 欄：純假名（五十音）。
第 2 欄：日文漢字（若該單字無漢字或與假名相同，請留空）。
第 3 欄：中文解釋。

【嚴格禁止】
不要表頭、不要 Markdown 表格符號、不要任何解釋性文字、不要序號。

【首行限定】
僅輸出 lesson_id: [數字]。

【範例格式】
lesson_id: 3
ロビー||大廳
へや|部屋|房間
トイレ||廁所
おてあらい|お手洗い|洗手間（較委婉）"""


def get_standard_llm_prompt() -> str:
    """回傳標準 LLM 提示詞，供 API 或介面「一鍵複製」給網頁版 LLM 使用。"""
    return STANDARD_LLM_PROMPT
