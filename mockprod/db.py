import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(os.environ["DATABASE_SYNC_URL"], pool_pre_ping=True)
SessionLocal = sessionmaker(engine, autocommit=False, autoflush=False)


@contextmanager
def get_db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
