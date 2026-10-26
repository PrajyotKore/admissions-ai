import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.ratelimit import limiter
from app import models as _models  # noqa: F401  (register tables)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(Session):
    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = _db
    limiter.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Actor:
    def __init__(self, client, token, org_id=None, user_id=None):
        self.c, self.token, self.org_id, self.user_id = client, token, org_id, user_id

    def h(self):
        h = {"Authorization": f"Bearer {self.token}"}
        if self.org_id:
            h["X-Organization-Id"] = self.org_id
        return h

    def get(self, url, **kw): return self.c.get(url, headers=self.h(), **kw)
    def post(self, url, **kw): return self.c.post(url, headers=self.h(), **kw)
    def patch(self, url, **kw): return self.c.patch(url, headers=self.h(), **kw)
    def delete(self, url, **kw): return self.c.delete(url, headers=self.h(), **kw)


def signup(client, email, org=None):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1",
                                              "full_name": email.split("@")[0], "organization_name": org})
    assert r.status_code == 201, r.text
    j = r.json()
    org_id = j["organizations"][0]["organization_id"] if j["organizations"] else None
    return Actor(client, j["access_token"], org_id, j["user"]["id"])


@pytest.fixture()
def owner_a(client): return signup(client, "owner-a@example.com", "Alpha Admissions")


@pytest.fixture()
def owner_b(client): return signup(client, "owner-b@example.com", "Beta Consultancy")


@pytest.fixture()
def counsellor_a(client, owner_a):
    r = owner_a.post("/api/team", json={"email": "c-a@example.com", "full_name": "Cee",
                                        "role": "counsellor", "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"email": "c-a@example.com", "password": "correct-horse-1"}).json()
    return Actor(client, login["access_token"], owner_a.org_id, r.json()["user_id"])


def mk_lead(actor, phone="9876543210", name="Asha", **extra):
    return actor.post("/api/leads", json={"name": name, "phone": phone, **extra})
