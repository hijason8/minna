"""
SQLAlchemy ORM 模型：與 SQLite/Postgres 共用同一 schema。
"""
from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Lesson(Base):
    """課程／影片（YouTube URL 對應一筆課程）。"""

    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    youtube_url = Column(String(2048), nullable=False, unique=True)
    lesson_name = Column(String(512), nullable=True)
    grammar_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Vocabulary(Base):
    """單字與慣用語（含 TTS 音檔路徑、星標、SRS 欄位）。依 tag_id 歸類題庫。"""

    __tablename__ = "vocabulary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)  # 保留相容；篩選以 tag_id 為主時可填 1
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=True)
    kanji = Column(String(256), nullable=True)
    kana = Column(String(512), nullable=False)
    meaning = Column(Text, nullable=False)
    audio_path = Column(String(1024), nullable=True)
    is_starred = Column(Integer, nullable=False, default=0)
    weight = Column(Integer, nullable=False, default=0)
    next_review_at = Column(DateTime, nullable=True)
    interval_days = Column(Integer, nullable=False, default=0)
    mastered = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Phrase(Base):
    """短語（格式同單字三欄，句子較長）。依 tag_id 歸類題庫。"""

    __tablename__ = "phrases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=True)
    kanji = Column(String(512), nullable=True)
    kana = Column(Text, nullable=False)
    meaning = Column(Text, nullable=False)
    is_starred = Column(Integer, nullable=False, default=0)
    mastered = Column(Integer, nullable=False, default=0)
    next_review_at = Column(DateTime, nullable=True)
    interval_days = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Tag(Base):
    """
    母標籤／子標籤：parent_id 為 NULL 表示母標籤（如 單字、短語、數字），
    否則為該母標籤下的子標籤。標籤依 name 字母排序。
    tag_name 保留以相容既有 DB（NOT NULL），新建時與 name 同值。
    """

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=True)  # 遷移後可能為 NULL，新建時必填
    tag_name = Column(String(128), nullable=True)  # 舊 schema 相容
    parent_id = Column(Integer, ForeignKey("tags.id"), nullable=True)


class LessonTag(Base):
    """課程與標籤多對多（文法／課程用）。"""

    __tablename__ = "lesson_tags"

    lesson_id = Column(Integer, ForeignKey("lessons.id"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id"), primary_key=True)


class UrlParseHistory(Base):
    """記錄每日已解析的 URL，用於去重。"""

    __tablename__ = "url_parse_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    youtube_url = Column(String(2048), nullable=False, unique=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    parsed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
