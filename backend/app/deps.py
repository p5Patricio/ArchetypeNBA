from contextlib import contextmanager
from sqlmodel import Session, create_engine, SQLModel
from app.config import settings


def _init_engine():
    raw_url = settings.DATABASE_URL
    if raw_url.startswith("postgresql://"):
        url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    else:
        url = raw_url

    connect_args = {"check_same_thread": False} if "sqlite" in url else {}
    return create_engine(
        url,
        pool_pre_ping=True,
        echo=settings.DEBUG,
        connect_args=connect_args,
    )


engine = _init_engine()


def get_db_session():
    """FastAPI dependency that yields a database session."""
    with Session(engine) as session:
        yield session


# Alias for convenience
get_session = get_db_session



@contextmanager
def get_db_context():
    """Synchronous context manager for database sessions (ETL, scripts)."""
    with Session(engine) as session:
        yield session


def create_db_and_tables():
    """Create all tables defined in SQLModel metadata."""
    SQLModel.metadata.create_all(engine)
