"""
應用設定：資料庫連線、音檔目錄、每日解析上限等。
雲端部署（如 Railway）請設定 DATABASE_URL；本地開發可用預設 SQLite。
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """應用設定，可透過環境變數覆寫。"""

    # 資料庫連線 URL。未設定時用 SQLite；Railway 會注入 DATABASE_URL（Postgres）
    database_url: str = "sqlite:///app_data.db"

    # 音檔快取根目錄（TTS 產生的 .mp3 存放於此）
    audio_cache_dir: str = "audio_cache"

    # 每日解析 YouTube 網址上限（防爆衝）
    daily_parse_limit: int = 5

    # LLM 重試次數
    max_retries: int = 3

    class Config:
        env_prefix = "APP_"
        env_file = ".env"
        # Railway 等平台常用 DATABASE_URL（無前綴）
        extra = "ignore"


def get_database_url() -> str:
    """取得資料庫 URL；優先使用環境變數 DATABASE_URL（Railway 等）。"""
    import os
    url = os.environ.get("DATABASE_URL", "").strip() or Settings().database_url
    # Railway/Heroku 常給 postgres://，SQLAlchemy 需 postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def get_audio_cache_path() -> Path:
    """取得音檔快取目錄的 Path，若不存在則建立。"""
    settings = Settings()
    path = Path(settings.audio_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
