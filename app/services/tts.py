"""
TTS 語音生成與本地快取。
邏輯：Check Local File -> 有則回傳路徑 -> 無則呼叫 TTS API -> 存 MP3 -> 更新 DB -> 回傳路徑。
嚴禁重複呼叫：同一 vocabulary_id + kana 只生成一次。
讀音欄位若含羅馬拼音（如「うけつけ uketuke」），只取日文部分送 TTS，避免唸兩次或怪聲。
"""
import re
from pathlib import Path

from sqlalchemy import text

from app.database import get_connection
from app.services.audio_storage import (
    get_vocabulary_audio_path,
    get_audio_path_if_exists,
    get_phrase_audio_path,
    ensure_audio_cache_dir,
)

# 只保留日文（平假名、片假名、漢字、・等），去掉羅馬拼音與括號內英文
_JAPANESE_ONLY = re.compile(r"[^\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\u30FB\u3000\s]")


def _kana_only_for_tts(text: str) -> str:
    """只取日文部分供 TTS 使用，移除羅馬拼音等，避免發音唸兩次或錯誤。"""
    if not text or not text.strip():
        return text
    cleaned = _JAPANESE_ONLY.sub("", text)
    return cleaned.strip() or text.strip()


def _generate_mp3(kana: str, save_path: Path) -> None:
    """
    使用 Google TTS（gTTS）生成日文語音並存成 MP3。
    僅傳入日文部分（假名／漢字），不含羅馬拼音。
    :param kana: 讀音（可能含羅馬拼音），會先過濾為僅日文
    :param save_path: 存檔路徑（.mp3）
    """
    from gtts import gTTS

    text_to_speak = _kana_only_for_tts(kana)
    tts = gTTS(text=text_to_speak, lang="ja", slow=False)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    tts.save(str(save_path))


def get_or_create_audio(vocabulary_id: int, kana: str) -> Path:
    """
    取得該單字的語音檔路徑；若本地尚無則生成並寫入 DB，再回傳路徑。
    :return: 本地 MP3 的 Path，供播放或回傳給前端
    """
    existing = get_audio_path_if_exists(vocabulary_id, kana)
    if existing is not None:
        return existing
    ensure_audio_cache_dir()
    path = get_vocabulary_audio_path(vocabulary_id, kana)
    _generate_mp3(kana, path)
    # 寫回 DB 方便查詢
    session = get_connection()
    try:
        session.execute(
            text("UPDATE vocabulary SET audio_path = :path WHERE id = :id"),
            {"path": str(path), "id": vocabulary_id},
        )
        session.commit()
    finally:
        session.close()
    return path


def get_or_create_phrase_audio(phrase_id: int) -> Path:
    """
    取得該短語的語音檔路徑；若本地尚無則依 phrases 表的 kana 生成並回傳路徑。
    """
    path = get_phrase_audio_path(phrase_id)
    if path.is_file():
        return path
    session = get_connection()
    try:
        row = session.execute(text("SELECT id, kana FROM phrases WHERE id = :id"), {"id": phrase_id}).mappings().fetchone()
    finally:
        session.close()
    if not row:
        raise ValueError("找不到該短語")
    kana = row["kana"] or ""
    if not _kana_only_for_tts(kana):
        raise ValueError("此短語無假名可發音，請檢查日文欄位")
    ensure_audio_cache_dir()
    _generate_mp3(kana, path)
    return path
