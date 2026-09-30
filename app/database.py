"""
Database configuration and session management module.

This module initializes the SQLAlchemy database engine, session factory, 
and declarative base, while providing a dependency-injected session generator 
for FastAPI request lifecycles.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite local database connection string
DATABASE_URL = "sqlite:///./workforce.db"

# connect_args={"check_same_thread": False} allows SQLite to handle multiple concurrent 
# threads in FastAPI asynchronous workers without thread-affinity constraints.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# Thread-local session factory for database transactions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all ORM models to inherit from
Base = declarative_base()


def get_db():
    """
    Provide a transactional database session scope for FastAPI dependency injection.

    Yields:
        Session: An active SQLAlchemy database session.

    Ensures:
        The database session is safely closed after the request is finished,
        preventing connection leaks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()