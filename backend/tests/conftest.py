import os, sys
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SEED_DEMO", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.database import Base, get_db
from src import models  # noqa: F401  (register metadata)


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session


@pytest.fixture()
def db(db_factory):
    session = db_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user(db):
    from src.models import User
    row = User(email="analyst@lanqiao.demo", name="许禾 · 数据分析师",
               role="analyst", password_hash="x")
    db.add(row); db.commit()
    return row
