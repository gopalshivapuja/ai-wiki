"""Tests for DB-backed LLM Wiki."""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/wiki_test.db")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "changeme")


@pytest.fixture(scope="module")
def client():
    from wiki_api.app import app
    from wiki_api.database import Base, SessionLocal, engine, init_db
    from wiki_api.services.seed import seed_if_empty

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search(client):
    r = client.get("/api/search?q=attention&limit=3")
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) > 0


def test_get_page(client):
    r = client.get("/api/pages/transformer-architecture")
    assert r.status_code == 200
    assert "transformer" in r.json()["title"].lower()


def test_graph(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    assert len(r.json()["nodes"]) > 0


def test_login(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "changeme"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["total_pages"] > 0


def test_slugify():
    from wiki_core.utils import slugify

    assert slugify("Scaled Dot-Product Attention") == "scaled-dot-product-attention"


def test_wikilinks():
    from wiki_core.utils import parse_wikilinks

    links = parse_wikilinks("See [[foo|Bar]] and [[baz]].")
    assert len(links) == 2
    assert links[0].target == "foo"
