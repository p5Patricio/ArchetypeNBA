import sys
import os

# Ensure backend root is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_db_session

# In-memory SQLite engine for tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_db_session():
    with Session(test_engine) as session:
        yield session


app.dependency_overrides[get_db_session] = override_get_db_session


@pytest.fixture(scope="function", autouse=True)
def setup_db():
    SQLModel.metadata.drop_all(test_engine)
    SQLModel.metadata.create_all(test_engine)
    yield
    SQLModel.metadata.drop_all(test_engine)



@pytest.fixture
def db_session():
    with Session(test_engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def client():
    return TestClient(app)
