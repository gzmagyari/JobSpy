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


def _ensure_columns() -> None:
    """Lightweight migrations: add columns introduced after a DB already exists."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(setting)").fetchall()}
        if "chat_model" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE setting ADD COLUMN chat_model VARCHAR DEFAULT 'gpt-4.1'"
            )
            conn.commit()


def init_db() -> None:
    """Create tables (if missing), run migrations, and seed the settings row."""
    import app.models  # noqa: F401  (register models on metadata)
    from app.models import Setting

    SQLModel.metadata.create_all(engine)
    _ensure_columns()
    with Session(engine) as session:
        if session.get(Setting, 1) is None:
            session.add(Setting(id=1, **DEFAULT_SETTINGS))
            session.commit()


def get_session():
    """FastAPI dependency that yields a session."""
    with Session(engine) as session:
        yield session
