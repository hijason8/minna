"""
SQLAlchemy 資料庫層：支援 SQLite（本地）與 Postgres（Railway 等雲端）。
使用 get_connection() 取得 Session，查詢請用 .execute(text("..."), {"param": val}).mappings().fetchone()/.fetchall()。
"""
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url
from app.models import Base


def _make_engine():
    url = get_database_url()
    # SQLite 需要 check_same_thread=False 給多請求
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True)


_engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def init_db(db_path: Optional[Path] = None) -> None:
    """
    建立所有資料表（若不存在）。
    雲端使用 Postgres 時可忽略 db_path；本地 SQLite 時亦由 database_url 決定路徑。
    """
    Base.metadata.create_all(bind=_engine)


def get_connection() -> Session:
    """
    取得資料庫 Session，供同步操作。
    呼叫端須在結束時呼叫 session.close()，或使用 try/finally。
    """
    return SessionLocal()


def get_db_path() -> Path:
    """回傳顯示用路徑或識別（get_config 等）；Postgres 時回傳假路徑。"""
    url = get_database_url()
    if "postgresql" in url or "postgres://" in url:
        return Path("postgres")
    # sqlite:///app_data.db -> app_data.db
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", ""))
    return Path("app_data.db")


def is_postgres() -> bool:
    """是否為 Postgres（用於需方言區分的 SQL，如 ON CONFLICT）。"""
    return "postgresql" in get_database_url() or get_database_url().startswith("postgres://")
