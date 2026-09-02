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
    """One platform-post of one video, queued into Buffer for a future slot.

    `lane` says which table `project_id` points into: "explainer" -> projects.id,
    "clips" -> clip_candidates.id. The column is a discriminator rather than a
    second table because the queue is a single publishing calendar — both lanes
    compete for the same slots, and a view that showed only half of it would let
    you double-book the same minute.
    """
    __tablename__ = "schedule"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    lane = Column(String, default="explainer")  # explainer|clips
    platform = Column(String)                 # youtube|tiktok|instagram
    due_at = Column(DateTime)
    status = Column(String, default="queued") # queued|posted|failed|cancelled
    buffer_post_id = Column(String, default="")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    lane = Column(String, default="explainer")  # see ScheduleItem.lane
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


class Feedback(Base):
    """Reviewer verdict on a rendered project — a rejection with a reason (and
    optional category tags). Fed forward into the NEXT script generation for the
    topic so the pipeline learns from what got rejected. See explainer/service.py
    (reject_project / feedback_guidance)."""
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    topic_id = Column(Integer, ForeignKey("topics.id"))
    draft_id = Column(Integer, ForeignKey("drafts.id"))
    verdict = Column(String, default="rejected")  # rejected (approved handled by Draft.status)
    reason = Column(Text, default="")             # free-text: why it was rejected
    tags = Column(JSON, default=list)             # ["hook","pacing","captions","visuals","audio",...]
    created_at = Column(DateTime, default=_now)


class CacheItem(Base):
    """Persistent, labeled, enriched content cache — reuse transcripts, generated
    videos/images, YouTube downloads, accent clips, and SVGs across videos. Files are
    content-addressed under EXPLAINER_CACHE; a `ref_key` dedupes by MEANING (a video
    by model+prompt+size+duration, a transcript by video id) so we never pay to
    regenerate the same thing. See explainer/cache.py."""
    __tablename__ = "cache_items"
    id = Column(Integer, primary_key=True)
    kind = Column(String, index=True)          # video|image|transcript|youtube|clip|svg|audio
    sha256 = Column(String, index=True)        # content hash (dedupe identical bytes)
    ref_key = Column(String, index=True)       # semantic dedupe key (reuse-by-meaning)
    path = Column(String, default="")          # location under the cache dir (relative)
    bytes = Column(Integer, default=0)
    mime = Column(String, default="")
    source = Column(Text, default="")          # prompt (generated) OR url (fetched)
    model = Column(String, default="")         # generator model, if any
    size = Column(String, default="")          # e.g. 720x1280
    duration_s = Column(Float, default=0.0)
    labels = Column(JSON, default=list)        # concept tags / keywords for classify+reuse
    meta = Column(JSON, default=dict)          # cost, channel, in/out, extra enrichment
    use_count = Column(Integer, default=1)     # how many times reused (savings signal)
    created_at = Column(DateTime, default=_now)
    last_used_at = Column(DateTime, default=_now, onupdate=_now)


class ClipSource(Base):
    """One long-form video being mined for Shorts (the `clips` lane).

    Downloaded ONCE to the content cache; every candidate window is then cut from
    that local file, so a 12-clip batch costs exactly one YouTube fetch (the box's
    IP gets rate-limited after ~5-8 section fetches). See clips/ingest.py.
    """
    __tablename__ = "clip_sources"
    id = Column(Integer, primary_key=True)
    url = Column(String, nullable=False)
    video_id = Column(String, default="", index=True)
    title = Column(String, default="")
    uploader = Column(String, default="")
    duration_s = Column(Float, default=0.0)
    local_path = Column(String, default="")    # cached full download
    vtt_path = Column(String, default="")      # timed transcript used to find moments
    transcript_source = Column(String, default="")  # vtt|asr — captions can be lossy
    status = Column(String, default="new")     # new|ingested|scanned
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class ClipCandidate(Base):
    """One proposed Short cut from a ClipSource — the unit of the review queue.

    `start_s`/`end_s` are the window as the model proposed it; `cut.py` snaps them
    to real speech boundaries and writes the snapped values back, so the row always
    reflects what was actually cut.
    """
    __tablename__ = "clip_candidates"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("clip_sources.id"), index=True)
    start_s = Column(Float, default=0.0)
    end_s = Column(Float, default=0.0)
    title = Column(String, default="")         # publish title
    hook = Column(String, default="")          # opening line / on-screen hook
    quote = Column(Text, default="")           # what is actually said in the window
    reason = Column(Text, default="")          # why the model picked it
    score = Column(Float, default=0.0)         # model's 0-1 confidence it lands
    mood = Column(String, default="")          # brand.py MOODS key (theme/palette)
    # Loop edit: `payoff_s` is the absolute second the punchline starts, inside
    # (start_s, end_s). `edit` picks the assembly — "linear" plays the window as
    # cut; "loop" rotates it about payoff_s so the clip opens on the punchline.
    # Which detector found it: speech (transcript) or action (motion + vision).
    # Decides how the cut is aligned — sentences for speech, shot cuts for action.
    kind = Column(String, default="speech")    # speech|action
    payoff_s = Column(Float, default=0.0)
    # Defaults to "loop" — the payoff-first rotation is the house cut. On an uncut
    # candidate this is the INTENT; once cut it is the RECORD of what was actually
    # assembled, which is why a loop that fell back writes "linear" back here.
    edit = Column(String, default="loop")      # linear|loop
    clip_path = Column(String, default="")     # cut 16:9 source clip
    audio_path = Column(String, default="")    # extracted master audio
    captions = Column(JSON, default=list)      # [{text,startMs,endMs}] word-level
    render_path = Column(String, default="")   # finished 9:16 MP4
    # What actually gets posted. Empty means "use the title" — the fallback is
    # resolved at post time rather than copied in at cut time, so re-titling a
    # candidate you never hand-wrote a caption for still changes what goes out.
    caption = Column(Text, default="")
    status = Column(String, default="candidate")  # candidate|cut|rendered|approved|rejected|scheduled
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class Setting(Base):
    """Runtime-editable configuration, one JSON blob per key.

    `brand.py` stays the source of the DEFAULTS — it is version-controlled and
    reviewable. This table holds only what a human has since overridden from the
    dashboard, so an untouched install behaves exactly like the brand file and
    `git diff` never fills up with settings churn. See publishing.py.
    """
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    value = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


def _add_missing_columns():
    """Add columns declared on a model but absent from an existing table.

    `create_all` only ever CREATEs — it will not ALTER a table that already
    exists, so a new column on a live DB is silently missing until something
    SELECTs it and blows up. SQLite can only add columns (never drop or retype),
    which is exactly the migration this store needs, so handle that one case
    here rather than taking on Alembic.
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {r[1] for r in conn.execute(
                text(f"PRAGMA table_info('{table.name}')"))}
            if not have:
                continue  # table doesn't exist yet; create_all handles it
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    val = col.default.arg
                    default = f" DEFAULT {val!r}" if isinstance(val, str) else f" DEFAULT {val}"
                conn.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{default}'))
                print(f"store: added {table.name}.{col.name}")


def init_db():
    Base.metadata.create_all(engine)
    _add_missing_columns()
    return DB_PATH


def session():
    return SessionLocal()
