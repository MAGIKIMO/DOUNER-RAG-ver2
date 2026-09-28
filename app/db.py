import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine, select, text)
from sqlalchemy.engine import URL
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
log = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(254), unique=True, nullable=False)
    password_hash = Column(String(255))
    provider = Column(String(30), default="local", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    language = Column(String(2), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Notice(Base):
    __tablename__ = "notices"
    id = Column(Integer, primary_key=True)
    source = Column(String(100), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    category = Column(String(100), nullable=False, index=True)
    title = Column(String(1000), nullable=False)
    content = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
    url = Column(Text, nullable=False)
    url_hash = Column(String(64), unique=True, nullable=False)
    published_at = Column(DateTime, index=True)
    crawled_at = Column(DateTime, default=utcnow, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)


class ContextChunk(Base):
    __tablename__ = "context_chunks"
    __table_args__ = (UniqueConstraint("source_type", "source_id", "chunk_index"), {"sqlite_autoincrement": True})
    id = Column(Integer, primary_key=True)
    source_type = Column(String(20), nullable=False)
    source_id = Column(Integer, ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(100), nullable=False)
    title = Column(String(1000), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    url = Column(Text, nullable=False)
    published_at = Column(DateTime)
    content_hash = Column(String(64), nullable=False)
    document_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class CrawlLog(Base):
    __tablename__ = "crawl_logs"
    id = Column(Integer, primary_key=True)
    source = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(String(64), primary_key=True)
    parent_id = Column(Integer, ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    filename = Column(String(1000), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    message = Column(Text, nullable=False, default="")
    file_hash = Column(String(64))
    parent_hash = Column(String(64))
    checked_at = Column(DateTime)


class AttachmentPage(Base):
    __tablename__ = "attachment_pages"
    notice_id = Column(Integer, ForeignKey("notices.id", ondelete="CASCADE"), primary_key=True)
    attachment_id = Column(String(64), ForeignKey("attachments.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)


@lru_cache
def engine():
    # DATABASE_URL is an optional local/test override; Compose uses MySQL below.
    url = os.getenv("DATABASE_URL") or URL.create(
        "mysql+pymysql", username=os.getenv("MYSQL_USER", "donga"),
        password=os.getenv("MYSQL_PASSWORD", ""), host=os.getenv("MYSQL_HOST", "db"),
        port=int(os.getenv("MYSQL_PORT", "3306")), database=os.getenv("MYSQL_DATABASE", "donga_rag"),
        query={"charset": "utf8mb4"})
    return create_engine(url, pool_pre_ping=True)


@contextmanager
def session_scope():
    with sessionmaker(bind=engine(), expire_on_commit=False)() as session:
        with session.begin():
            yield session


def init_db():
    Base.metadata.create_all(engine())


@contextmanager
def maintenance_lock():
    # Also coordinates CLI jobs with the HTTP worker. Never release before commit.
    with engine().connect() as connection:
        mysql = connection.dialect.name == "mysql"
        if mysql and connection.scalar(text("SELECT GET_LOCK('donga_rag_maintenance', 0)")) != 1:
            raise RuntimeError("maintenance_busy")
        try:
            yield
        finally:
            if mysql:
                connection.execute(text("SELECT RELEASE_LOCK('donga_rag_maintenance')"))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def save_notice(*, source, source_type, category, title, content, url, published_at=None):
    signature = digest(json.dumps([source, source_type, category, title, content, url,
                                  published_at.isoformat() if published_at else None], ensure_ascii=False))
    with session_scope() as session:
        record = session.scalar(select(Notice).where(Notice.url_hash == digest(url)))
        if record and record.content_hash == signature:
            record.crawled_at = utcnow()
            return "unchanged"
        state = "updated" if record else "created"
        if record is None:
            record = Notice(url=url, url_hash=digest(url))
            session.add(record)
        for key, value in dict(source=source, source_type=source_type, category=category,
                               title=title, content=content, published_at=published_at,
                               content_hash=signature, crawled_at=utcnow()).items():
            setattr(record, key, value)
        return state


def record_crawl(source, status, message):
    try:
        with session_scope() as session:
            session.add(CrawlLog(source=source, status=status, message=message[:4000]))
    except Exception:
        log.error("crawl_log_write_failed source=%s status=%s", source, status)
