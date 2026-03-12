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
    """單字與慣用語（含 TTS 音檔路徑、星標、SRS 欄位）。"""

    __tablename__ = "vocabulary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
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
    """短語（格式同單字三欄，句子較長）。"""

    __tablename__ = "phrases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    kanji = Column(String(512), nullable=True)
    kana = Column(Text, nullable=False)
    meaning = Column(Text, nullable=False)
    is_starred = Column(Integer, nullable=False, default=0)
    mastered = Column(Integer, nullable=False, default=0)
    next_review_at = Column(DateTime, nullable=True)
    interval_days = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Tag(Base):
    """多維度分類標籤。"""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_name = Column(String(128), nullable=False, unique=True)


class LessonTag(Base):
    """課程與標籤多對多。"""

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
