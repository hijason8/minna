"""
TTS 音檔本地儲存與路徑檢查。
邏輯：Check Local File -> If exists, Play -> If not, Call Google TTS API -> Save MP3 to Local -> Play。
嚴禁重複呼叫 API，故以本地路徑為準。
"""
from pathlib import Path
from typing import Optional

from app.config import get_audio_cache_path, Settings


def get_phrase_audio_path(phrase_id: int) -> Path:
    """短語 TTS 預期音檔路徑（不檢查是否存在）。"""
    cache_root = get_audio_cache_path()
    return cache_root / f"phrase_{phrase_id}.mp3"


def get_vocabulary_audio_path(vocabulary_id: int, kana: str) -> Path:
    """
    取得某單字/慣用語的預期音檔路徑（不檢查是否存在）。
    檔名規則：{vocabulary_id}_{safe_kana}.mp3，避免重複與路徑問題。
    """
    cache_root = get_audio_cache_path()
    # 將 kana 中不適合檔名的字元替換
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in kana.strip())
    safe = (safe or "audio")[:120]
    filename = f"{vocabulary_id}_{safe}.mp3"
    return cache_root / filename


def audio_file_exists(vocabulary_id: int, kana: str) -> bool:
    """
    檢查該單字/慣用語的 TTS 音檔是否已存在於本地。
    若存在則應直接播放，不呼叫 Google TTS API。
    """
    path = get_vocabulary_audio_path(vocabulary_id, kana)
    return path.is_file()


def get_audio_path_if_exists(vocabulary_id: int, kana: str) -> Optional[Path]:
    """
    若本地已有該詞的 TTS 音檔，回傳 Path；否則回傳 None。
    供播放邏輯使用：有則回傳路徑播放，無則需先呼叫 TTS 並儲存。
    """
    path = get_vocabulary_audio_path(vocabulary_id, kana)
    return path if path.is_file() else None


def ensure_audio_cache_dir() -> Path:
    """
    確保音檔快取目錄存在，並回傳該目錄 Path。
    在寫入新 MP3 前可呼叫以確保目錄存在。
    """
    return get_audio_cache_path()
