"""Tests for ai-wiki.

Runs against a real PostgreSQL database — there is no second dialect to fall back on, and a
fallback search engine would only hide failures in the real one. `docker compose up db`
provides one, or point DATABASE_URL at any local Postgres.
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("DATABASE_URL", "postgresql://wiki:wiki@localhost:5432/wiki_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("WIKI_SEED_DIR", str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

AUTH = {"email": "admin@example.com", "password": "changeme"}


@pytest.fixture(scope="module")
def client():
    from wiki_api.app import app
    from wiki_api.database import Base, engine

    Base.metadata.drop_all(bind=engine)
    # Entered as a context manager so lifespan actually runs: wait_for_database, the secret
    # checks, create_all, the generated-column DDL, seeding, and the job runner.
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/login", json=AUTH)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wait(client, auth, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=auth).json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


# --- basics -------------------------------------------------------------------


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seeding_imported_content(client, auth):
    """Guards the bug where production seeded nothing because the path resolved wrong."""
    s = client.get("/api/stats", headers=auth).json()
    assert s["total_notes"] > 0, "no notes were seeded"
    assert s["total_sources"] > 0, "no sources were seeded"


def test_login_rejects_bad_password_with_a_useful_message(client):
    """A wrong password used to surface as 'Login required' and clear the session."""
    r = client.post("/api/auth/login", json={**AUTH, "password": "nope"})
    assert r.status_code == 401
    assert "password" in r.json()["detail"].lower()


def test_everything_requires_auth(client):
    for method, path in [
        ("get", "/api/search?q=x"),
        ("get", "/api/documents"),
        ("get", "/api/graph"),
        ("get", "/api/stats"),
        ("get", "/api/export"),
        ("post", "/api/documents"),
        ("get", "/api/jobs"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, f"{method} {path} was reachable without a token"


# --- the merged document model ------------------------------------------------


def test_sources_and_notes_share_one_namespace(client, auth):
    docs = client.get("/api/documents", headers=auth).json()["documents"]
    slugs = [d["slug"] for d in docs]
    assert len(slugs) == len(set(slugs)), "slugs must be unique across notes and sources"
    assert any(d["doc_class"] == "source" for d in docs)
    assert any(d["doc_class"] == "note" for d in docs)


def test_wikilinks_resolve_to_sources(client, auth):
    """The point of the merge: a source can be a link target.

    Under the previous two-table model this was structurally impossible.
    """
    sources = client.get("/api/documents?doc_class=source", headers=auth).json()["documents"]
    assert sources
    detail = client.get(f"/api/documents/{sources[0]['slug']}", headers=auth).json()
    assert detail["backlinks"], "no note links to this source"

    graph = client.get("/api/graph", headers=auth).json()
    source_slugs = {n["slug"] for n in graph["nodes"] if n["doc_class"] == "source"}
    assert any(e["target"] in source_slugs for e in graph["edges"])


def test_seed_data_has_no_broken_links(client, auth):
    """A fresh install should not greet you with red links."""
    assert client.get("/api/orphans", headers=auth).json()["wanted"] == []


def test_sources_are_immutable(client, auth):
    sources = client.get("/api/documents?doc_class=source", headers=auth).json()["documents"]
    r = client.put(f"/api/documents/{sources[0]['slug']}", json={"body": "x"}, headers=auth)
    assert r.status_code == 409
    assert "cannot be edited" in r.json()["detail"]


# --- notes --------------------------------------------------------------------


def test_note_lifecycle(client, auth):
    r = client.post(
        "/api/documents",
        json={"title": "Test Concept Alpha", "body": "# A\n\nSee [[transformer-architecture]]."},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]

    dup = client.post("/api/documents", json={"title": "Test Concept Alpha"}, headers=auth)
    assert dup.status_code == 409

    detail = client.get(f"/api/documents/{slug}", headers=auth).json()
    assert any(
        link["slug"] == "transformer-architecture" and link["exists"] for link in detail["links"]
    )

    back = client.get("/api/documents/transformer-architecture", headers=auth).json()["backlinks"]
    assert any(b["slug"] == slug for b in back)

    # PUT returns the same shape as GET, so a client can use the response directly.
    updated = client.put(
        f"/api/documents/{slug}", json={"body": "changed", "tags": ["t"]}, headers=auth
    )
    assert updated.status_code == 200
    assert {"backlinks", "links", "revision_count"} <= set(updated.json())

    assert client.delete(f"/api/documents/{slug}", headers=auth).status_code == 204
    assert client.get(f"/api/documents/{slug}", headers=auth).status_code == 404


def test_note_title_must_be_usable(client, auth):
    """A title with no ASCII letters used to create a page at an unreachable empty slug."""
    r = client.post("/api/documents", json={"title": "注意機構"}, headers=auth)
    assert r.status_code == 409


def test_revisions_capture_and_restore(client, auth):
    client.post("/api/documents", json={"title": "Rev Doc", "body": "v1"}, headers=auth)
    client.put("/api/documents/rev-doc", json={"body": "v2"}, headers=auth)
    client.put("/api/documents/rev-doc", json={"body": "v3"}, headers=auth)

    revs = client.get("/api/documents/rev-doc/revisions", headers=auth).json()["revisions"]
    assert [r["preview"] for r in revs] == ["v2", "v1"]

    client.post(f"/api/documents/rev-doc/restore/{revs[-1]['id']}", headers=auth)
    assert client.get("/api/documents/rev-doc", headers=auth).json()["body"] == "v1"
    client.delete("/api/documents/rev-doc", headers=auth)


def test_validation_errors_are_structured(client, auth):
    """422 detail is a list of objects; the client must render it as a sentence."""
    r = client.post("/api/documents", json={"title": ""}, headers=auth)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


# --- search -------------------------------------------------------------------


def test_search_ranks_and_highlights(client, auth):
    results = client.get("/api/search?q=attention&limit=5", headers=auth).json()["results"]
    assert results
    assert all(
        {"score", "slug", "title", "snippet", "type", "doc_class"} <= set(r) for r in results
    )
    assert [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True)
    assert any("«" in r["snippet"] for r in results), "expected highlighted snippets"


def test_search_handles_punctuation_and_phrases(client, auth):
    # websearch_to_tsquery must not raise on characters a user will actually type.
    for q in ['"self attention"', "what is (attention)?", "attention -foo", "a & b | c"]:
        assert client.get(f"/api/search?q={q}", headers=auth).status_code == 200


def test_search_can_exclude_sources(client, auth):
    r = client.get("/api/search?q=attention&include_sources=false", headers=auth).json()
    assert all(x["doc_class"] == "note" for x in r["results"])


# --- backup -------------------------------------------------------------------


def test_export_import_round_trip(client, auth):
    """The durability story: everything must survive a trip through the archive."""
    before = client.get("/api/stats", headers=auth).json()

    data = client.get("/api/export", headers=auth).content
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert len(names) > before["total_notes"]
    assert any(n.startswith("sources/") for n in names)
    assert any(n.startswith("notes/") for n in names)

    job = client.post(
        "/api/jobs/import",
        files={"file": ("backup.zip", data, "application/zip")},
        headers=auth,
    ).json()
    finished = _wait(client, auth, job["id"])
    assert finished["status"] == "done", finished
    assert finished["result"]["failed"] == []

    after = client.get("/api/stats", headers=auth).json()
    assert after["total_notes"] == before["total_notes"]
    assert after["total_wikilinks"] == before["total_wikilinks"]


# --- jobs ---------------------------------------------------------------------


def test_paste_job_end_to_end(client, auth):
    r = client.post(
        "/api/jobs/paste",
        json={"title": "Pasted Test Note", "text": "Content about vector databases."},
        headers=auth,
    )
    job = _wait(client, auth, r.json()["id"])
    assert job["status"] == "done", job
    slug = job["result"]["slug"]
    assert client.get(f"/api/documents/{slug}", headers=auth).json()["immutable"] is True


def test_job_failure_retry_and_cancel(client, auth):
    bad = client.post("/api/jobs/web", json={"url": "file:///etc/passwd"}, headers=auth)
    failed = _wait(client, auth, bad.json()["id"])
    assert failed["status"] == "failed"
    assert "http" in (failed["error"] or "").lower()

    retried = client.post(f"/api/jobs/{failed['id']}/retry", headers=auth)
    assert retried.status_code == 200
    _wait(client, auth, retried.json()["id"])

    assert client.post(f"/api/jobs/{failed['id']}/cancel", headers=auth).status_code == 409


def test_reap_orphans_leaves_fresh_jobs_alone(client, auth):
    """A booting container must not kill the outgoing container's in-flight work."""
    from datetime import timedelta

    from wiki_api.database import Job, session_scope, utcnow
    from wiki_api.jobs.runner import reap_orphans

    with session_scope() as db:
        fresh = Job(kind="crawl", status="running", params={}, started_at=utcnow())
        old = Job(
            kind="crawl",
            status="running",
            params={},
            started_at=utcnow() - timedelta(hours=1),
        )
        db.add_all([fresh, old])
        db.flush()
        fresh_id, old_id = fresh.id, old.id

    reap_orphans()

    with session_scope() as db:
        assert db.get(Job, old_id).status == "failed"
        assert db.get(Job, fresh_id).status == "running"
        db.query(Job).filter(Job.id.in_([fresh_id, old_id])).delete(synchronize_session=False)


def test_pdf_rejects_non_pdf(client, auth):
    r = client.post(
        "/api/jobs/pdf", files={"file": ("notes.txt", b"hello", "text/plain")}, headers=auth
    )
    assert r.status_code == 400


# --- SPA and security ---------------------------------------------------------


def test_spa_is_served(client):
    """Break the static copy in the Dockerfile and both CI jobs used to stay green."""
    if client.get("/").status_code == 503:
        pytest.skip("frontend not built in this environment")
    for path in ("/", "/browse", "/doc/anything"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert 'id="root"' in r.text, f"{path} did not return the app shell"


def test_unknown_api_path_is_json_404(client):
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_static_path_traversal_blocked(client):
    for path in ("/../../etc/passwd", "/..%2f..%2fetc%2fpasswd", "/static/../../../etc/passwd"):
        r = client.get(path)
        assert b"root:" not in r.content, f"served /etc/passwd via {path}"


def test_fetch_rejects_dangerous_urls():
    from wiki_api.services.fetch import FetchError, fetch_text

    for url in (
        "file:///etc/passwd",
        "ftp://example.com/x",
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


def test_wikilink_parsing():
    from wiki_core.utils import parse_wikilinks

    links = parse_wikilinks("See [[foo|Bar]] and [[baz]].")
    assert [(x.target, x.display) for x in links] == [("foo", "Bar"), ("baz", None)]


def test_crawl_scope_rules():
    from wiki_api.services.crawl import in_scope

    start = "https://docs.example.com/guide/intro"
    assert in_scope(start, "https://docs.example.com/guide/setup")
    assert not in_scope(start, "https://docs.example.com/blog/post")
    assert not in_scope(start, "https://evil.example.org/guide/x")
    assert not in_scope(start, "https://docs.example.com/guide/logo.png")

    dir_start = "https://docs.example.com/guide/"
    assert in_scope(dir_start, "https://docs.example.com/guide/setup")
    assert not in_scope(dir_start, "https://docs.example.com/reference/api")


def test_crawl_preserves_trailing_slash():
    """Stripping it made urljoin resolve every relative docs link one directory too high."""
    from urllib.parse import urljoin

    from wiki_api.services.crawl import _normalize

    base = _normalize("https://docs.example.com/tutorial/#top")
    assert urljoin(base, "next.html") == "https://docs.example.com/tutorial/next.html"


def test_crawl_fetches_each_page_once(monkeypatch):
    """The crawler used to fetch every page twice: once for links, once to store it."""
    from wiki_api.database import session_scope
    from wiki_api.services import crawl
    from wiki_api.services.content import delete_doc

    pages = {
        "https://ex.test/d/": "<html><title>Index</title><a href='a.html'>a</a></html>",
        "https://ex.test/d/a.html": "<html><title>A</title>body text here</html>",
    }
    calls: list[str] = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        return "text/html", pages[url]

    monkeypatch.setattr(crawl, "fetch_text", fake_fetch)
    monkeypatch.setattr(crawl, "POLITENESS_DELAY", 0)

    with session_scope() as db:
        result = crawl.crawl_site(db, "https://ex.test/d/", max_pages=5, max_depth=1)

    assert result["pages"] == 2
    assert sorted(calls) == sorted(pages), "each page must be fetched exactly once"

    with session_scope() as db:
        for slug in result["created"]:
            delete_doc(db, slug)


def test_page_title_decodes_entities():
    """Raw entities used to survive into slugs as digits, e.g. "&#8212;" -> "8212"."""
    from wiki_api.services.fetch import page_title
    from wiki_core.utils import slugify

    title = page_title("<html><title>4. Tools &#8212; Python 3.14 documentation</title>", "x")
    assert title == "4. Tools"
    assert "8212" not in slugify(title)


def test_startup_secret_guard(monkeypatch):
    from wiki_api.startup import StartupError, check_secrets, is_production

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@monorail.proxy.rlwy.net:6543/railway")
    assert is_production()
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(StartupError, match="JWT_SECRET"):
        check_secrets()

    monkeypatch.setenv("JWT_SECRET", "a-real-secret")
    check_secrets()

    monkeypatch.setenv("DATABASE_URL", "postgresql://wiki:wiki@localhost:5432/wiki")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert not is_production()
    check_secrets()  # local development must not be blocked


def test_every_env_var_is_documented():
    """Keeps .env.example honest as new knobs appear."""
    import re

    documented = (REPO_ROOT / ".env.example").read_text()
    undocumented = {
        name
        for py in (REPO_ROOT / "packages").rglob("*.py")
        for name in re.findall(r'os\.environ\.get\(\s*"([A-Z_]+)"', py.read_text())
        if name not in documented
    }
    assert not undocumented, f"add these to .env.example: {sorted(undocumented)}"
