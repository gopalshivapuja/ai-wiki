"""Tests for the DB-backed LLM Wiki."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/wiki_test.db")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("WIKI_SEED_DIR", str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from wiki_api.app import app
    from wiki_api.database import Base, engine

    Base.metadata.drop_all(bind=engine)
    # Enter the context manager so lifespan actually runs — init_db, schema DDL, seeding and
    # the job runner all live there and were previously untested.
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "changeme"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- basics -------------------------------------------------------------------


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seeding_actually_imported_content(client):
    """Guards the bug where production seeded nothing because the path resolved wrong."""
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_pages"] > 0, "no pages were seeded"
    assert data["total_sources"] > 0, "no sources were seeded"


def test_search(client):
    r = client.get("/api/search?q=attention&limit=3")
    assert r.status_code == 200
    assert len(r.json()["results"]) > 0


def test_search_results_carry_kind(client, auth):
    r = client.get("/api/search?q=attention&limit=10", headers=auth)
    results = r.json()["results"]
    assert results
    assert all(x["kind"] in ("page", "source") for x in results)


def test_anonymous_search_excludes_sources(client, auth):
    """Raw sources sit behind auth, so anonymous search must not leak their text."""
    anon = client.get("/api/search?q=transformer&limit=20").json()["results"]
    assert all(x["kind"] == "page" for x in anon)
    authed = client.get("/api/search?q=transformer&limit=20", headers=auth).json()["results"]
    assert any(x["kind"] == "source" for x in authed)


def test_get_page(client):
    r = client.get("/api/pages/transformer-architecture")
    assert r.status_code == 200
    body = r.json()
    assert "transformer" in body["title"].lower()
    assert "backlinks" in body and "links" in body


def test_missing_page_404(client):
    assert client.get("/api/pages/no-such-page-xyz").status_code == 404


def test_graph(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    data = r.json()
    assert len(data["nodes"]) > 0
    slugs = {n["slug"] for n in data["nodes"]}
    for e in data["edges"]:
        assert e["source"] in slugs and e["target"] in slugs


def test_login(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "changeme"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "nope"})
    assert r.status_code == 401


# --- auth ---------------------------------------------------------------------


def test_write_endpoints_require_auth(client):
    assert client.post("/api/zettels", json={"title": "Nope"}).status_code == 401
    assert client.put("/api/pages/transformer-architecture", json={"body": "x"}).status_code == 401
    assert client.delete("/api/pages/transformer-architecture").status_code == 401
    assert client.get("/api/sources").status_code == 401
    assert client.post("/api/jobs/paste", json={"title": "a", "text": "b"}).status_code == 401


# --- CRUD ---------------------------------------------------------------------


def test_zettel_lifecycle(client, auth):
    r = client.post("/api/zettels", json={"title": "Test Concept Alpha"}, headers=auth)
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    assert slug == "test-concept-alpha"

    # duplicate
    assert (
        client.post("/api/zettels", json={"title": "Test Concept Alpha"}, headers=auth).status_code
        == 409
    )

    r = client.put(
        f"/api/pages/{slug}",
        json={"body": "# Alpha\n\nLinks to [[transformer-architecture]].", "tags": ["test"]},
        headers=auth,
    )
    assert r.status_code == 200
    assert "transformer-architecture" in r.json()["body"]

    # the edit must be visible as a backlink on the target
    backlinks = client.get("/api/pages/transformer-architecture").json()["backlinks"]
    assert any(b["slug"] == slug for b in backlinks)

    # outgoing links resolve
    links = client.get(f"/api/pages/{slug}").json()["links"]
    assert any(link["slug"] == "transformer-architecture" and link["exists"] for link in links)

    assert client.delete(f"/api/pages/{slug}", headers=auth).status_code == 204
    assert client.get(f"/api/pages/{slug}").status_code == 404


def test_zettel_rejects_unusable_title(client, auth):
    """A title with no ASCII letters used to create a page at an unreachable empty slug."""
    r = client.post("/api/zettels", json={"title": "注意機構"}, headers=auth)
    assert r.status_code == 409


def test_page_type_validated(client, auth):
    client.post("/api/zettels", json={"title": "Type Check Page"}, headers=auth)
    r = client.put("/api/pages/type-check-page", json={"type": "bogus"}, headers=auth)
    assert r.status_code == 400
    client.delete("/api/pages/type-check-page", headers=auth)


def test_source_read_and_summary_slug(client, auth):
    sources = client.get("/api/sources", headers=auth).json()["sources"]
    assert sources
    slug = sources[0]["slug"]
    r = client.get(f"/api/sources/{slug}", headers=auth)
    assert r.status_code == 200
    assert r.json()["body"]


def test_resolve_endpoint(client):
    assert client.get("/api/resolve?target=transformer-architecture").json()["exists"] is True
    assert client.get("/api/resolve?target=Transformer Architecture").json()["slug"] == (
        "transformer-architecture"
    )
    assert client.get("/api/resolve?target=nothing-here-at-all").json()["exists"] is False


# --- jobs ---------------------------------------------------------------------


def _wait_for_job(client, auth, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=auth).json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_paste_job_runs_end_to_end(client, auth):
    r = client.post(
        "/api/jobs/paste",
        json={"title": "Pasted Test Note", "text": "Some content about vector databases."},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    job = _wait_for_job(client, auth, r.json()["id"])
    assert job["status"] == "done", job
    assert job["result"]["slug"] == "pasted-test-note"

    source = client.get("/api/sources/pasted-test-note", headers=auth)
    assert source.status_code == 200
    assert "vector databases" in source.json()["body"]


def test_job_validation_and_cancel(client, auth):
    bad = client.post("/api/jobs/paste", json={"title": "", "text": "x"}, headers=auth)
    assert bad.status_code == 422

    r = client.post(
        "/api/jobs/crawl", json={"url": "https://example.com/docs", "max_pages": 999}, headers=auth
    )
    assert r.status_code == 422  # above HARD_MAX_PAGES

    r = client.post("/api/jobs/paste", json={"title": "Cancel Me", "text": "x"}, headers=auth)
    job_id = r.json()["id"]
    cancel = client.post(f"/api/jobs/{job_id}/cancel", headers=auth)
    # Either it was cancelled while queued, or it already completed — both are valid races.
    assert cancel.status_code in (200, 409)


def test_pdf_rejects_non_pdf(client, auth):
    r = client.post(
        "/api/jobs/pdf",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth,
    )
    assert r.status_code == 400


# --- security -----------------------------------------------------------------


def test_static_path_traversal_blocked(client):
    for path in ("/../../etc/passwd", "/..%2f..%2fetc%2fpasswd", "/static/../../../etc/passwd"):
        r = client.get(path)
        assert r.status_code in (200, 404, 503), path
        assert b"root:" not in r.content, f"served /etc/passwd via {path}"


def test_ingest_rejects_non_http_schemes(client, auth):
    from wiki_api.services.fetch import FetchError, fetch_text

    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com"):
        with pytest.raises(FetchError):
            fetch_text(url)


def test_ingest_rejects_internal_addresses(client, auth):
    from wiki_api.services.fetch import FetchError, fetch_text

    for url in (
        "http://127.0.0.1:8000/",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(FetchError):
            fetch_text(url)


# --- units --------------------------------------------------------------------


def test_slugify():
    from wiki_core.utils import slugify

    assert slugify("Scaled Dot-Product Attention") == "scaled-dot-product-attention"
    assert slugify("注意機構") == ""


def test_wikilinks():
    from wiki_core.utils import parse_wikilinks

    links = parse_wikilinks("See [[foo|Bar]] and [[baz]].")
    assert len(links) == 2
    assert links[0].target == "foo"
    assert links[0].display == "Bar"


def test_summary_slug_is_namespaced():
    """AI summaries must not be able to land on the curated note about the same material."""
    from wiki_api.services.content import summary_slug

    assert summary_slug("attention-is-all-you-need-paper") != "attention-is-all-you-need-paper"
    assert summary_slug("x").startswith("summary-")


def test_upsert_page_protects_curated_pages():
    from wiki_api.database import session_scope
    from wiki_api.services.content import upsert_page

    with session_scope() as db:
        upsert_page(db, "curated-guard-test", "Curated", "hand written", page_type="zettel")
        with pytest.raises(ValueError):
            upsert_page(
                db,
                "curated-guard-test",
                "Robot",
                "generated",
                page_type="literature",
                protect_curated=True,
            )
        from wiki_api.services.content import delete_page

        delete_page(db, "curated-guard-test")


def test_crawl_scope_rules():
    from wiki_api.services.crawl import in_scope

    start = "https://docs.example.com/guide/intro"
    assert in_scope(start, "https://docs.example.com/guide/setup")
    assert not in_scope(start, "https://docs.example.com/blog/post")
    assert not in_scope(start, "https://evil.example.org/guide/x")
    assert not in_scope(start, "https://docs.example.com/guide/logo.png")

    # A directory start URL keeps its own segment in scope.
    dir_start = "https://docs.example.com/guide/"
    assert in_scope(dir_start, "https://docs.example.com/guide/setup")
    assert not in_scope(dir_start, "https://docs.example.com/reference/api")


def test_crawl_preserves_trailing_slash_for_relative_links():
    """Stripping it made urljoin resolve every relative docs link one directory too high."""
    from urllib.parse import urljoin

    from wiki_api.services.crawl import _normalize

    base = _normalize("https://docs.example.com/tutorial/#top")
    assert urljoin(base, "next.html") == "https://docs.example.com/tutorial/next.html"


def test_search_bm25_directly():
    from wiki_api.database import session_scope
    from wiki_api.services.search_bm25 import search_bm25

    with session_scope() as db:
        results = search_bm25(db, "attention", top_k=5)
    assert results
    assert all({"score", "slug", "title", "snippet", "type", "kind"} <= set(r) for r in results)


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL_PG"),
    reason="set TEST_DATABASE_URL_PG to exercise the Postgres full-text path",
)
def test_search_postgres():
    """Runs the real FTS path. Without this, only the SQLite fallback is ever tested."""
    import wiki_api.database as database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from wiki_api.schema_ddl import apply_schema_ddl
    from wiki_api.services.search_pg import search_postgres

    pg_engine = create_engine(os.environ["TEST_DATABASE_URL_PG"])
    original = database.engine
    database.engine = pg_engine
    try:
        database.Base.metadata.create_all(bind=pg_engine)
        apply_schema_ddl()
        Session = sessionmaker(bind=pg_engine)
        with Session() as db:
            from wiki_api.services.content import upsert_page

            upsert_page(
                db,
                "pg-fts-probe",
                "Postgres FTS Probe",
                "Retrieval augmented generation over a vector index.",
                page_type="zettel",
            )
            results = search_postgres(db, "retrieval augmented", top_k=5)
            assert any(r["slug"] == "pg-fts-probe" for r in results)
            assert all(r["kind"] in ("page", "source") for r in results)
    finally:
        database.engine = original
        pg_engine.dispose()


def test_page_title_decodes_entities_and_strips_site_suffix():
    """Raw entities used to survive into slugs as digits, e.g. "&#8212;" -> "8212"."""
    from wiki_api.services.fetch import page_title
    from wiki_core.utils import slugify

    title = page_title(
        "<html><title>4. More Control Flow Tools &#8212; Python 3.14 documentation</title>", "x"
    )
    assert title == "4. More Control Flow Tools"
    assert "8212" not in slugify(title)


# --- startup guards -----------------------------------------------------------


def test_is_production_detection(monkeypatch):
    from wiki_api.startup import is_production

    for url, expected in [
        ("sqlite:////tmp/x.db", False),
        ("postgresql://wiki:wiki@localhost:5432/wiki", False),
        ("postgresql://wiki:wiki@db:5432/wiki", False),  # docker compose
        ("postgresql://u:p@containers-us-west-1.railway.app:6543/railway", True),
        ("", False),
    ]:
        monkeypatch.setenv("DATABASE_URL", url)
        assert is_production() is expected, url


def test_default_jwt_secret_blocks_production_boot(monkeypatch):
    """The default secret is published in this repo — booting with it means forgeable tokens."""
    from wiki_api.startup import StartupError, check_secrets

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@monorail.proxy.rlwy.net:6543/railway")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(StartupError, match="JWT_SECRET"):
        check_secrets()

    monkeypatch.setenv("JWT_SECRET", "a-real-secret")
    check_secrets()  # must not raise


def test_default_secret_is_allowed_in_local_development(monkeypatch):
    from wiki_api.startup import check_secrets

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/dev.db")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    check_secrets()  # warns, does not raise


def test_wait_for_database_retries_then_gives_up(monkeypatch):
    """A database that never comes up must fail with a clear message, not a raw driver error."""
    import wiki_api.startup as startup
    from sqlalchemy import create_engine

    monkeypatch.setattr(startup.time, "sleep", lambda _s: None)
    dead = create_engine("postgresql://nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 1})
    monkeypatch.setattr("wiki_api.database.engine", dead)

    with pytest.raises(startup.StartupError, match="Could not reach the database"):
        startup.wait_for_database(attempts=2)


def test_wait_for_database_succeeds_on_live_engine():
    from wiki_api.startup import wait_for_database

    wait_for_database(attempts=1)  # the test engine is live
