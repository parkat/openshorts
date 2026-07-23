"""SQLite (SQLAlchemy) durable store for the explainer lane — the review queue and
pipeline state. Lives on the persistent ./archive bind mount so it survives
restarts (the base app's in-memory 1h job model is wrong for a review queue).

Tables: topics, projects, drafts, clips, schedule, posts, voices.
Override the path with EXPLAINER_DB.
"""
import os
import datetime
from sqlalchemy import (create_engine, Column, Integer, String, Text, Float,
                        DateTime, ForeignKey, JSON)
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.environ.get("EXPLAINER_DB") or os.path.join("archive", "openshorts.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", future=True,
                       connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
Base = declarative_base()


def _now():
    return datetime.datetime.utcnow()


class Topic(Base):
    __tablename__ = "topics"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    summary = Column(Text, default="")
    source_url = Column(String, default="")
    sources = Column(JSON, default=list)      # [{type:'doc'|'youtube', url, in, out, note}]
    angle = Column(String, default="")
    score = Column(Float, default=0.0)
    status = Column(String, default="new")    # new|approved|rejected
    origin = Column(String, default="manual") # manual|radar
    created_at = Column(DateTime, default=_now)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    title = Column(String, default="")
    status = Column(String, default="draft")  # draft|assets|render|review|scheduled|published|failed
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class Draft(Base):
    __tablename__ = "drafts"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    script = Column(JSON, default=dict)       # shot list (hook..button), each line + source pointer
    factcheck = Column(JSON, default=list)    # [{claim, label, note}]
    voice_id = Column(String, default="")
    status = Column(String, default="draft")  # draft|needs_review|approved
    created_at = Column(DateTime, default=_now)


class Clip(Base):
    __tablename__ = "clips"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    url = Column(String)                      # accent-clip provenance (dispute-ready)
    channel = Column(String, default="")
    start_s = Column(Float, default=0.0)
    end_s = Column(Float, default=0.0)
    local_path = Column(String, default="")
    fetch_date = Column(DateTime, default=_now)


class ScheduleItem(Base):
    __tablename__ = "schedule"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    platform = Column(String)                 # youtube|tiktok|instagram
    due_at = Column(DateTime)
    status = Column(String, default="queued") # queued|posted|failed
    buffer_post_id = Column(String, default="")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    platform = Column(String)
    url = Column(String, default="")
    buffer_post_id = Column(String, default="")
    metrics = Column(JSON, default=dict)
    posted_at = Column(DateTime, default=_now)


class Voice(Base):
    __tablename__ = "voices"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    model = Column(String, default="")        # OpenRouter TTS model
    voice = Column(String, default="")        # voice id/name
    notes = Column(Text, default="")
    retention = Column(Float, default=0.0)     # A/B signal


def init_db():
    Base.metadata.create_all(engine)
    return DB_PATH


def session():
    return SessionLocal()
