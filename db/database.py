import os
import platform
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

# Default SQLite path — stored in a user data directory so it survives
# package upgrades and works correctly when installed via pip/pipx.
# Override with ZSCALER_DB_URL (full SQLAlchemy URL) or ZSCALER_DB_PATH.
if platform.system() == "Windows":
    _DEFAULT_DB_PATH = Path(os.environ.get("APPDATA", Path.home())) / "zs-config" / "zscaler.db"
    _LEGACY_DB_PATH  = Path(os.environ.get("APPDATA", Path.home())) / "z-config"  / "zscaler.db"
else:
    _DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "zs-config" / "zscaler.db"
    _LEGACY_DB_PATH  = Path.home() / ".local" / "share" / "z-config"  / "zscaler.db"

_engine = None
_SessionFactory = None


def get_db_url() -> str:
    if url := os.environ.get("ZSCALER_DB_URL"):
        return url
    db_path = os.environ.get("ZSCALER_DB_PATH", str(_DEFAULT_DB_PATH))
    return f"sqlite:///{db_path}"


def _migrate_db_path() -> None:
    """Move the database file from the legacy z-config path to zs-config if needed."""
    import shutil
    if not _DEFAULT_DB_PATH.exists() and _LEGACY_DB_PATH.exists():
        _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(_LEGACY_DB_PATH), str(_DEFAULT_DB_PATH))


def init_db(db_url: Optional[str] = None) -> None:
    """Create tables and initialise the session factory.

    Call this once at application startup (CLI entry point, script startup,
    or FastAPI lifespan). Safe to call multiple times.
    """
    global _engine, _SessionFactory
    if not os.environ.get("ZSCALER_DB_URL") and not os.environ.get("ZSCALER_DB_PATH"):
        _migrate_db_path()
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(
        db_url or get_db_url(),
        echo=False,
        connect_args={"check_same_thread": False},  # needed for SQLite + threading
    )
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    _migrate(_engine)


def _migrate(engine) -> None:
    """Apply additive column migrations for existing databases."""
    migrations = [
        "ALTER TABLE tenant_configs ADD COLUMN zpa_disabled_resources JSON",
        "ALTER TABLE tenant_configs ADD COLUMN zia_disabled_resources JSON",
        "ALTER TABLE tenant_configs ADD COLUMN zcc_disabled_resources JSON",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # Column already exists


def _ensure_init() -> None:
    if _SessionFactory is None:
        init_db()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a database session with auto commit/rollback."""
    _ensure_init()
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
