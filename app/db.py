"""Database engine, session helper, and one-time initialisation/seeding."""
from __future__ import annotations

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import DB_PATH, DEFAULT_SETTINGS

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # scheduler + API run in diff threads
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")  # better read/write concurrency
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def init_db() -> None:
    """Create tables (if missing) and seed the single settings row."""
    import app.models  # noqa: F401  (register models on metadata)
    from app.models import Setting

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.get(Setting, 1) is None:
            session.add(Setting(id=1, **DEFAULT_SETTINGS))
            session.commit()


def get_session():
    """FastAPI dependency that yields a session."""
    with Session(engine) as session:
        yield session
