from collections.abc import Iterator
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.database import Base, get_db
from app.main import create_app
from app.models import User
from app.security import hash_password


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    path = Path(__file__).parent / f".test-data-{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        rmtree(path)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    db_session.add(User(username="shared", password_hash=hash_password("test-password")))
    db_session.commit()
    app = create_app(Settings(database_url="sqlite:///:memory:", token_secret="test-only-secret-for-test-cases-only"))
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/auth/login",
            json={"username": "shared", "password": "test-password"},
        )
        test_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        yield test_client
