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
    # Point seeding at the suite's own fixture content. The app no longer ships starter notes,
    # and tests that need content should say which content they need rather than inheriting
    # whatever happened to be in seed/.
    os.environ["WIKI_SEED_DIR"] = str(Path(__file__).parent / "fixtures")

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

    # Give a source a collection first. to_markdown() has always written this field and
    # import_markdown() silently dropped it, so the round trip lost it and every imported
    # source landed with collection NULL — which left crosslink's collection filter matching
    # nothing. Counting notes and links would never have caught that.
    from wiki_api.database import session_scope
    from wiki_api.services.content import get_doc, list_docs

    with session_scope() as db:
        collected_slug = list_docs(db, doc_class="source", limit=1)[0].slug
        get_doc(db, collected_slug).collection = "round-trip-collection"
        db.commit()

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

    restored = client.get("/api/documents?collection=round-trip-collection", headers=auth).json()
    assert collected_slug in [d["slug"] for d in restored["documents"]]


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


def test_question_retrieval_uses_any_term_matching(client, auth):
    """A natural question shares few words with the note that answers it.

    With all-terms matching, "why does multi-head attention help?" retrieved nothing and Ask
    AI always replied that the wiki was empty.
    """
    from wiki_api.database import session_scope
    from wiki_api.services.search import search

    question = "What is multi-head attention and why does it help?"
    with session_scope() as db:
        assert search(db, question, match_all=True) == []
        loose = search(db, question, match_all=False, top_k=5)
    assert loose, "question retrieval returned nothing"
    assert any("attention" in r["slug"] for r in loose)


def test_literature_note_slug_is_clean(client, auth):
    """Deriving it from the note title produced `summary-source-summary-pep-20`."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import get_doc, store_source, upsert_literature_note

    with session_scope() as db:
        src, _ = store_source(db, title="PEP 20", body="x", subtype="web", url="https://e.test/p")
        note = upsert_literature_note(db, src, "Source summary: PEP 20", "body", [])
        assert note.slug == "summary-pep-20", note.slug
        assert note.derived_from_id == src.id

        # Re-summarizing updates the same note rather than making a second one.
        again = upsert_literature_note(db, src, "Source summary: PEP 20", "new body", [])
        assert again.slug == note.slug
        assert again.body == "new body"

        from wiki_api.services.content import delete_doc

        delete_doc(db, note.slug)
        delete_doc(db, src.slug)
        assert get_doc(db, note.slug) is None


# --- distillation -------------------------------------------------------------


def test_concept_names_are_normalised_for_convergence():
    """The same idea written three ways must reach one note."""
    from wiki_api.services.distill import _normalise

    assert _normalise("Cross-Entropy Loss") == _normalise("cross entropy")
    assert _normalise("Attention (Bahdanau)") == _normalise("attention")
    assert _normalise("Backpropagation") != _normalise("Forward Pass")


def test_find_existing_converges_via_alias_and_title(client, auth):
    """A concept met under an abbreviation must find the note that already covers it."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import build_link_index, create_note, delete_doc
    from wiki_api.services.distill import Concept, find_existing

    with session_scope() as db:
        note = create_note(db, "Multi-Head Attention Mechanism", "body", subtype="zettel")
        note.extra = {"aliases": ["MHA"]}
        db.commit()
        index = build_link_index(db)

        by_alias = find_existing(db, index, Concept(name="MHA"))
        by_title = find_existing(db, index, Concept(name="multi head attention mechanism"))
        unrelated = find_existing(db, index, Concept(name="Kalman Filtering"))

        assert by_alias == note.slug
        assert by_title == note.slug
        assert unrelated is None
        delete_doc(db, note.slug)


def test_extraction_rejects_junk_concepts():
    """A model returning headings or sentences must not become notes."""
    from wiki_api.services.distill import _concepts_from

    data = {
        "concepts": [
            {"name": "Cross-Entropy Loss", "summary": "s", "why": "w", "aliases": ["CE"]},
            {"name": "", "summary": "empty name"},
            {"name": "x" * 200, "summary": "far too long to be a concept"},
            {"name": "。。。", "summary": "nothing sluggable"},
            "not even a dict",
        ]
    }
    out = _concepts_from(data, limit=8)
    assert [c.name for c in out] == ["Cross-Entropy Loss"]
    assert out[0].aliases == ["CE"]


def test_every_job_kind_queues_distillation(monkeypatch):
    """The choke point: capture by any route must lead to linking.

    Previously each handler decided for itself, so arXiv never summarised and crawl, paste
    and import defaulted to off.
    """
    from wiki_api.jobs import runner

    queued: list[dict] = []
    monkeypatch.setattr(runner, "session_scope", lambda: __import__("contextlib").nullcontext(None))
    monkeypatch.setattr(runner, "enqueue", lambda db, kind, params: queued.append(params))

    for kind in ("web", "arxiv", "youtube", "crawl", "pdf", "paste", "transcribe"):
        queued.clear()
        runner._queue_distillation(kind, {}, {"sources": [f"src-{kind}"]})
        assert [q["source_slug"] for q in queued] == [f"src-{kind}"], kind

    # Explicitly opting out is still honoured, and distill jobs do not recurse.
    queued.clear()
    runner._queue_distillation("web", {"distill": False}, {"sources": ["src-x"]})
    runner._queue_distillation("distill", {}, {"sources": ["src-y"]})
    assert queued == []


def test_reasoning_is_stripped_before_it_reaches_a_note():
    """Nemotron models write their chain of thought as ordinary content."""
    from wiki_core.llm import clean_output

    assert clean_output("<think>plan</think>\n# Note\n\nBody.") == "# Note\n\nBody."
    assert clean_output("Okay, the user wants a note.\n\n# Note\n\nBody.") == "# Note\n\nBody."
    # A reply that is *only* preamble must not be emptied.
    assert clean_output("We need to respond with ok") == "We need to respond with ok"


def test_json_is_recovered_from_a_messy_reply():
    from wiki_core.llm import extract_json

    assert extract_json('```json\n{"concepts": []}\n```') == {"concepts": []}
    assert extract_json('Sure! {"a": 1} hope that helps') == {"a": 1}
    assert extract_json("no json here") is None


def test_slugify_treats_separators_as_word_breaks():
    """ "Vanishing/Exploding" was slugging to "vanishingexploding"."""
    from wiki_core.utils import slugify

    assert slugify("Vanishing/Exploding Gradients") == "vanishing-exploding-gradients"
    assert slugify("Q, K & V") == "q-k-v"


def test_import_does_not_redistil_a_restore(monkeypatch):
    """Restoring a backup must not create a second literature note for every source."""
    from wiki_api.jobs import runner

    queued: list[dict] = []
    monkeypatch.setattr(runner, "session_scope", lambda: __import__("contextlib").nullcontext(None))
    monkeypatch.setattr(runner, "enqueue", lambda db, kind, params: queued.append(params))

    runner._queue_distillation("import", {}, {"sources": ["src-a"]})
    assert queued == [], "a restore should not re-distil"

    runner._queue_distillation("import", {"distill": True}, {"sources": ["src-a"]})
    assert [q["source_slug"] for q in queued] == ["src-a"]


def test_normalisation_folds_ml_suffixes():
    """ "Transformer" forked from "Transformer Architecture" during the real load."""
    from wiki_api.services.distill import _normalise

    assert _normalise("Transformer") == _normalise("Transformer Architecture")
    assert _normalise("Attention") == _normalise("Attention Mechanism")
    assert _normalise("Recurrent Neural Network") == _normalise("Recurrent Neural Networks")
    # Genuinely different ideas must stay apart.
    assert _normalise("Positional Encoding") != _normalise("Rotary Positional Encoding")


def test_normalisation_folds_plurals_and_problem_suffix():
    """Three lectures produced three notes for one idea: gradient, gradients, and problem."""
    from wiki_api.services.distill import _normalise

    one = _normalise("Vanishing Gradient")
    assert _normalise("Vanishing Gradients") == one
    assert _normalise("Vanishing Gradient Problem") == one
    # Words that merely end in s are not stems.
    assert _normalise("Loss") == "loss"
    assert _normalise("Bias") == "bias"


def test_blocked_captions_fall_back_to_ytdlp(monkeypatch):
    """The direct caption endpoint is IP-blocked for cloud hosts; yt-dlp is the second route."""
    from wiki_api.services import ingest

    def refuse(_vid):
        raise RuntimeError("IpBlocked: YouTube is blocking requests from your IP")

    monkeypatch.setattr(ingest, "_captions_via_ytdlp", lambda vid: "recovered transcript")
    monkeypatch.setitem(
        __import__("sys").modules,
        "youtube_transcript_api",
        type("m", (), {"YouTubeTranscriptApi": type("A", (), {"fetch": staticmethod(refuse)})}),
    )
    assert ingest.fetch_youtube_transcript("abc") == "recovered transcript"


def test_both_caption_routes_blocked_is_reported_as_a_block(monkeypatch):
    """A block must never be reported as "no captions" — that sends users to paid STT."""
    from wiki_api.services import ingest

    def refuse(_vid):
        raise RuntimeError("IpBlocked: YouTube is blocking requests from your IP")

    monkeypatch.setattr(ingest, "_captions_via_ytdlp", lambda vid: None)
    monkeypatch.setitem(
        __import__("sys").modules,
        "youtube_transcript_api",
        type("m", (), {"YouTubeTranscriptApi": type("A", (), {"fetch": staticmethod(refuse)})}),
    )
    with pytest.raises(ingest.CaptionsBlocked):
        ingest.fetch_youtube_transcript("abc")


def test_video_with_genuinely_no_captions_returns_none(monkeypatch):
    from wiki_api.services import ingest

    def absent(_vid):
        raise RuntimeError("NoTranscriptFound: this video has no captions")

    monkeypatch.setattr(ingest, "_captions_via_ytdlp", lambda vid: None)
    monkeypatch.setitem(
        __import__("sys").modules,
        "youtube_transcript_api",
        type("m", (), {"YouTubeTranscriptApi": type("A", (), {"fetch": staticmethod(absent)})}),
    )
    assert ingest.fetch_youtube_transcript("abc") is None


def test_bracketed_markdown_link_is_not_a_wikilink():
    """Cloudflare's obfuscated emails made 37 phantom edges to "email protected"."""
    from wiki_core.utils import count_wikilinks, parse_wikilinks

    text = "Mail [[email protected]](https://x.com/cdn-cgi/l/email-protection) about it."
    assert parse_wikilinks(text) == []
    assert count_wikilinks(text) == 0
    # A genuine link, including one followed by prose in parentheses, still counts.
    assert len(parse_wikilinks("See [[transformer]] and [[rag|RAG]].")) == 2


def test_two_sources_sharing_a_concept_produce_one_note(client, auth, monkeypatch):
    """The whole point of distillation: the second source links, it does not duplicate.

    Also asserts that every link written lands on a document that exists — the dangling-link
    failure this pipeline was built to end.
    """
    from wiki_api.database import session_scope
    from wiki_api.services import distill as D
    from wiki_api.services.content import build_link_index, get_doc, store_source
    from wiki_core.utils import parse_wikilinks

    # Lecture two names the idea in plural, which is how the real transcripts differed.
    replies = iter(
        [
            [
                D.Concept(
                    name="Vanishing Gradient", summary="Gradients shrink.", why="it limits depth"
                )
            ],
            [
                D.Concept(
                    name="Vanishing Gradients", summary="Gradients shrink.", why="it recurs here"
                )
            ],
        ]
    )
    monkeypatch.setattr(D, "extract_concepts", lambda source, limit=8: next(replies))
    monkeypatch.setattr(D, "call_llm", lambda *a, **k: "A summary.")

    with session_scope() as db:
        first, _ = store_source(db, title="Lecture A", body="body a", subtype="paste")
        second, _ = store_source(db, title="Lecture B", body="body b", subtype="paste")

        one = D.distill(db, first, moc_slug="moc-test-course", moc_title="Test Course")
        two = D.distill(db, second, moc_slug="moc-test-course", moc_title="Test Course")

        assert len(one.created) == 1, "the first source should create the note"
        assert two.created == [], "the second source must not duplicate it"
        assert two.linked == one.created, "the second source must link to the existing note"

        index = build_link_index(db)
        for slug in [one.literature_slug, two.literature_slug, "moc-test-course"]:
            doc = get_doc(db, slug)
            for link in parse_wikilinks(doc.body or ""):
                assert index.resolve(link.target), f"{slug} links to missing {link.target!r}"


def test_reimport_corrects_class_url_and_aliases(client, auth, tmp_path):
    """The update branch dropped every frontmatter field except title, body and subtype.

    A transcript that landed as a note could never be corrected, and re-importing an export
    silently stripped url and aliases from documents that already existed.
    """
    from wiki_api.database import session_scope
    from wiki_api.services.content import delete_doc, get_doc, import_markdown

    path = tmp_path / "src-misfiled-lecture.md"
    path.write_text('---\ntitle: "Misfiled Lecture"\nclass: note\ntype: page\n---\n\nBody.\n')
    with session_scope() as db:
        first = import_markdown(db, path)
        assert first.doc_class == "note"
        assert first.immutable is False
        slug = first.slug

        path.write_text(
            '---\ntitle: "Misfiled Lecture"\nclass: source\ntype: youtube\n'
            'url: "https://youtu.be/abc"\naliases: ["ML"]\n---\n\nBody.\n'
        )
        import_markdown(db, path)
        fixed = get_doc(db, slug)
        assert fixed.doc_class == "source"
        assert fixed.immutable is True, "captured material must be protected from edits"
        assert fixed.url == "https://youtu.be/abc"
        assert fixed.extra.get("aliases") == ["ML"]
        delete_doc(db, slug)


def test_export_is_readable_past_the_drain_boundary(client, auth):
    """A wiki larger than one drain chunk must still produce an extractable zip.

    export_stream drains its buffer every chunk_docs documents. Draining used to reset the
    stream position, so every central-directory offset written after the first drain pointed
    at the wrong byte: `unzip` reported "bad zipfile offset" and no file could be extracted.

    The original round-trip test missed it twice over — its wiki was smaller than one chunk,
    and it only called namelist(), which reads the central directory without touching an
    entry. This one writes past the boundary and reads every member.
    """
    from wiki_api.database import session_scope
    from wiki_api.services.archive import export_stream
    from wiki_api.services.content import create_note, delete_doc

    made = []
    with session_scope() as db:
        for i in range(60):
            made.append(
                create_note(db, f"Drain Boundary Note {i}", f"Body {i}.", subtype="zettel").slug
            )

    try:
        with session_scope() as db:
            # chunk_docs=10 guarantees several drains regardless of the rest of the fixture.
            data = b"".join(export_stream(db, chunk_docs=10))

        zf = zipfile.ZipFile(io.BytesIO(data))
        assert zf.testzip() is None, "a member failed its CRC or could not be located"
        # Reading every entry is what actually exercises the offsets.
        for name in zf.namelist():
            assert zf.read(name) is not None
        assert len([n for n in zf.namelist() if n.endswith(".md")]) > 60
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_neighbourhood_stays_within_the_requested_hops(client, auth):
    """A whole-wiki graph is unreadable; the local one must actually be local."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import create_note, delete_doc
    from wiki_api.services.graph import build_neighbourhood

    made = []
    with session_scope() as db:
        # A chain: centre -> near -> far -> distant
        for name, body in [
            ("Hop Distant", "leaf"),
            ("Hop Far", "[[hop-distant]]"),
            ("Hop Near", "[[hop-far]]"),
            ("Hop Centre", "[[hop-near]]"),
        ]:
            made.append(create_note(db, name, body, subtype="zettel").slug)

        one = build_neighbourhood(db, "hop-centre", hops=1)
        two = build_neighbourhood(db, "hop-centre", hops=2)

    try:
        at_one = {n["slug"] for n in one["nodes"]}
        at_two = {n["slug"] for n in two["nodes"]}
        assert at_one == {"hop-centre", "hop-near"}
        assert at_two == {"hop-centre", "hop-near", "hop-far"}
        assert "hop-distant" not in at_two
        # Every edge returned must join two nodes that were returned.
        for e in two["edges"]:
            assert e["source"] in at_two and e["target"] in at_two
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_neighbourhood_follows_links_in_both_directions(client, auth):
    """A note that links to you is as much a neighbour as one you link to."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import create_note, delete_doc
    from wiki_api.services.graph import build_neighbourhood

    with session_scope() as db:
        create_note(db, "Backlink Centre", "no links out", subtype="zettel")
        create_note(db, "Backlink Pointer", "[[backlink-centre]]", subtype="zettel")
        n = build_neighbourhood(db, "backlink-centre", hops=1)

    try:
        assert "backlink-pointer" in {x["slug"] for x in n["nodes"]}
    finally:
        with session_scope() as db:
            delete_doc(db, "backlink-centre")
            delete_doc(db, "backlink-pointer")


def test_random_returns_a_note_never_a_source(client, auth):
    for _ in range(8):
        r = client.get("/api/random", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert body["doc_class"] == "note"
        assert body["type"] != "index", "the index is not a note to rediscover"
        assert "preview" in body


def test_llms_txt_describes_the_wiki_and_needs_auth(client, auth):
    assert client.get("/api/llms.txt").status_code == 401

    text = client.get("/api/llms.txt", headers=auth).text
    assert text.startswith("# ai-wiki")
    assert "## Start here" in text and "## How to traverse" in text
    # Every map of content must be named, since those are the entry points it promises.
    mocs = client.get("/api/documents?doc_class=note&type=moc", headers=auth).json()["documents"]
    for m in mocs:
        assert m["slug"] in text, f"{m['slug']} missing from llms.txt"


# --- read-only demo account ---------------------------------------------------


@pytest.fixture
def reader_auth(client):
    """A reader token. The role is what the API enforces on, not the UI."""
    from wiki_api.auth_utils import hash_password
    from wiki_api.database import READER, User, session_scope

    email, password = "demo-test@example.com", "demo-pass-123"
    with session_scope() as db:
        if not db.query(User).filter(User.email == email).first():
            db.add(User(email=email, hashed_password=hash_password(password), role=READER))
    token = client.post("/api/auth/login", json={"email": email, "password": password}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def test_reader_can_read_everything(client, reader_auth):
    for path in (
        "/api/stats",
        "/api/documents",
        "/api/search?q=note",
        "/api/orphans",
        "/api/llms.txt",
        "/api/random",
        "/api/jobs",
    ):
        assert client.get(path, headers=reader_auth).status_code == 200, path


def test_reader_is_refused_every_write(client, reader_auth, auth):
    """The demo password is public by design, so the server has to be what says no."""
    writes = [
        ("post", "/api/documents", {"json": {"title": "Sneaky", "body": "x"}}),
        ("put", "/api/documents/index", {"json": {"body": "defaced"}}),
        ("delete", "/api/documents/index", {}),
        ("post", "/api/review/approve", {"json": {}}),
        ("post", "/api/jobs/web", {"json": {"url": "https://example.com"}}),
        ("post", "/api/jobs/paste", {"json": {"title": "t", "text": "x"}}),
        ("post", "/api/jobs/summarize", {"json": {"source_slug": "x"}}),
        ("post", "/api/maintenance/embed", {}),
    ]
    for method, path, kwargs in writes:
        res = getattr(client, method)(path, headers=reader_auth, **kwargs)
        assert res.status_code == 403, f"{method.upper()} {path} returned {res.status_code}"
        assert "read-only" in res.json()["detail"].lower()

    # And nothing leaked through: the index is untouched.
    assert "defaced" not in client.get("/api/documents/index", headers=auth).json()["body"]


def test_admin_role_survives_the_new_column(client, auth):
    me = client.get("/api/auth/me", headers=auth).json()
    assert me["role"] == "admin" and me["can_edit"] is True


# --- semantic association -----------------------------------------------------


def test_similarity_ranks_the_same_idea_above_a_different_one():
    from wiki_api.services.relate import cosine

    a, b, c = [1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 1.0, 0.0]
    assert cosine(a, b) > cosine(a, c)
    assert cosine(a, a) == pytest.approx(1.0)


def test_embeddings_round_trip_through_bytes():
    from wiki_api.services.embed import from_bytes, to_bytes

    vec = [0.5, -0.25, 0.125]
    assert from_bytes(to_bytes(vec)) == pytest.approx(vec)
    assert from_bytes(None) is None


def test_everything_still_works_without_an_embedding_model(client, auth, monkeypatch):
    """Absence of the model is a supported configuration, not a failure."""
    from wiki_api.database import session_scope
    from wiki_api.services import embed
    from wiki_api.services.relate import embed_missing, similar

    monkeypatch.setattr(embed, "_get_model", lambda: None)
    monkeypatch.setattr(embed, "_load_failed", True)
    assert embed.embed_one("anything") is None
    assert embed.embed_document("t", "b") is None
    with session_scope() as db:
        # No model means no *new* vectors...
        assert embed_missing(db)["embedded"] == 0
        # ...but similarity reads vectors already stored, so it keeps working. Only a wiki
        # that never had a model returns nothing here.
        assert isinstance(similar(db, "index"), list)
    assert client.get("/api/related/index", headers=auth).status_code == 200

    # A write still succeeds; it simply carries no vector.
    from wiki_api.services.content import create_note, delete_doc

    with session_scope() as db:
        note = create_note(db, "No Model Available", "body", subtype="zettel")
        assert note.embedding is None
        delete_doc(db, note.slug)


def test_distillation_links_ideas_to_each_other(client, auth, monkeypatch):
    """The defect this pipeline was rebuilt for: 1.7% of edges joined one idea to another.

    Concepts extracted together must end up linked to each other, in both directions.
    """
    from wiki_api.database import session_scope
    from wiki_api.services import distill as D
    from wiki_api.services.content import delete_doc, get_doc, store_source

    concepts = [
        D.Concept(
            name="Alpha Mechanism",
            summary="Alpha does a thing.",
            why="it underpins beta",
            relates_to=[D.Relation(name="Beta Method", reason="alpha is what makes beta work")],
        ),
        D.Concept(name="Beta Method", summary="Beta does another thing.", why="it uses alpha"),
    ]
    monkeypatch.setattr(D, "extract_concepts", lambda source, limit=8: concepts)
    monkeypatch.setattr(D, "call_llm", lambda *a, **k: "A summary.")
    monkeypatch.setattr(D, "_neighbours", lambda db, concept, k=3: [])
    monkeypatch.setattr(D, "_embed_concept", lambda concept: None)

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(db, title="Cross Link Source", body="body", subtype="paste")
            made.append(src.slug)
            result = D.distill(db, src)
            made += result.created + ([result.literature_slug] if result.literature_slug else [])

            assert result.cross_links >= 1, "no idea-to-idea link was written"
            alpha = get_doc(db, "alpha-mechanism").body
            beta = get_doc(db, "beta-method").body
            # Reciprocal: a relationship visible from only one side is half a relationship.
            assert "[[beta-method]]" in alpha
            assert "[[alpha-mechanism]]" in beta
            assert "alpha is what makes beta work" in alpha
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_a_relation_without_a_reason_is_discarded():
    """An unjustified link is the noise this pipeline is meant to avoid."""
    from wiki_api.services.distill import _concepts_from

    got = _concepts_from(
        {
            "concepts": [
                {
                    "name": "Thing",
                    "summary": "s",
                    "why": "w",
                    "relates_to": [
                        {"name": "Other", "reason": "because it extends it"},
                        {"name": "Unjustified"},
                        {"reason": "orphan reason"},
                    ],
                }
            ]
        },
        limit=8,
    )
    assert [r.name for r in got[0].relates_to] == ["Other"]


# --- queue retention ----------------------------------------------------------


def test_sweep_clears_finished_payloads_but_spares_live_jobs():
    """Uploads live in Job.payload so a redeploy cannot lose them; nothing removed them after."""
    from datetime import timedelta

    from wiki_api.database import Job, session_scope, utcnow
    from wiki_api.jobs.runner import sweep_finished_jobs

    ids = {}
    with session_scope() as db:
        old_done = Job(
            kind="pdf", status="done", payload="x" * 5000, finished_at=utcnow() - timedelta(days=3)
        )
        recent_done = Job(kind="pdf", status="done", payload="y" * 100, finished_at=utcnow())
        queued = Job(kind="pdf", status="queued", payload="z" * 100)
        db.add_all([old_done, recent_done, queued])
        db.commit()
        ids = {"old": old_done.id, "recent": recent_done.id, "queued": queued.id}

    got = sweep_finished_jobs()
    assert got["payloads_cleared"] >= 1

    with session_scope() as db:
        assert db.get(Job, ids["old"]).payload is None, "a stale payload should be gone"
        assert db.get(Job, ids["recent"]).payload is not None, "still retryable"
        assert db.get(Job, ids["queued"]).payload is not None, "never touch unfinished work"
        for job_id in ids.values():
            db.delete(db.get(Job, job_id))


def test_schema_ddl_restores_columns_create_all_would_not(client):
    """create_all() creates missing tables, not missing columns.

    Adding `embedding` and `role` to the models and deploying failed the healthcheck in
    production: the tables already existed, so create_all() did nothing, and every query
    named a column the database did not have. This drops those columns and asserts the boot
    DDL puts them back — the upgrade path a real deploy takes, which a locally-created schema
    never exercises.
    """
    from sqlalchemy import inspect, text
    from wiki_api.database import engine
    from wiki_api.schema_ddl import apply_schema_ddl

    added = {"documents": ["embedding", "embedding_model", "embedded_at"], "users": ["role"]}
    with engine.begin() as conn:
        for table, columns in added.items():
            for column in columns:
                conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))

    inspector = inspect(engine)
    assert "embedding" not in {c["name"] for c in inspector.get_columns("documents")}

    apply_schema_ddl()

    inspector = inspect(engine)
    for table, columns in added.items():
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            assert column in present, f"{table}.{column} was not restored by schema_ddl"

    # Idempotent: a second boot must not fail.
    apply_schema_ddl()


def test_every_model_column_is_creatable_on_an_existing_table():
    """Guards the whole class of bug rather than the two columns that caused it.

    Any column added to a model from now on must also appear in PG_STATEMENTS, or the next
    deploy repeats the outage.
    """
    from wiki_api.database import Document, User
    from wiki_api.schema_ddl import PG_STATEMENTS

    ddl = " ".join(PG_STATEMENTS).lower()
    # Columns present in the original schema predate this rule; these are the ones added since.
    added_since = {
        "documents": {"embedding", "embedding_model", "embedded_at"},
        "users": {"role"},
    }
    for model, table in ((Document, "documents"), (User, "users")):
        for column in model.__table__.columns:
            if column.name in added_since[table]:
                assert f"add column if not exists {column.name}" in ddl, (
                    f"{table}.{column.name} is in the model but has no ADD COLUMN statement"
                )


def test_boot_sequence_survives_a_database_missing_the_new_columns(client):
    """The order in app.py's lifespan is load-bearing, not decorative.

    _ensure_admin() reads users.role. It used to run inside init_db(), before
    apply_schema_ddl() had added that column to an existing table, so a real deploy died with
    "column users.role does not exist" while a locally-created schema was fine. This replays
    the boot sequence against a database that lacks the column.
    """
    import sqlalchemy.exc
    from sqlalchemy import text
    from wiki_api.database import engine, ensure_users, init_db
    from wiki_api.schema_ddl import apply_schema_ddl

    def drop_role():
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS role"))

    # Wrong order: the failure the deploy actually hit.
    drop_role()
    init_db()
    with pytest.raises(sqlalchemy.exc.ProgrammingError):
        ensure_users()

    # Right order: create tables, add columns, then touch rows.
    drop_role()
    init_db()
    apply_schema_ddl()
    ensure_users()

    with engine.begin() as conn:
        role = conn.execute(text("SELECT role FROM users LIMIT 1")).scalar()
    assert role in ("admin", "reader")


def test_redistillation_can_be_capped_to_linking_only(client, auth, monkeypatch):
    """max_new=0 links concepts to existing notes and mints none.

    Re-running distillation over material already processed should mostly connect what is
    there; without a cap, 190 sources at six notes each could double the wiki.
    """
    from wiki_api.database import session_scope
    from wiki_api.services import distill as D
    from wiki_api.services.content import delete_doc, store_source

    monkeypatch.setattr(
        D,
        "extract_concepts",
        lambda source, limit=8: [D.Concept(name="Brand New Idea", summary="s", why="w")],
    )
    monkeypatch.setattr(D, "call_llm", lambda *a, **k: "A summary.")
    monkeypatch.setattr(D, "_neighbours", lambda db, concept, k=3: [])
    monkeypatch.setattr(D, "_embed_concept", lambda concept: None)

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(db, title="Cap Test Source", body="body", subtype="paste")
            made.append(src.slug)
            result = D.distill(db, src, max_new=0)
            made += [result.literature_slug] if result.literature_slug else []
            assert result.created == [], "max_new=0 must not create notes"
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_distillation_makes_no_model_calls_while_holding_a_session(monkeypatch):
    """The bug that took the site down: a pooled connection held across two model calls.

    Queueing 195 of those exhausted "QueuePool limit of size 5 overflow 5" and every request
    started returning 500. The handler must do its model work between sessions, not inside one.
    """
    import wiki_api.jobs.handlers as H
    from wiki_api.database import session_scope
    from wiki_api.services import distill as D
    from wiki_api.services.content import delete_doc, store_source

    open_sessions = {"count": 0, "during_llm": []}
    real_scope = H.session_scope

    class Tracking:
        def __enter__(self):
            open_sessions["count"] += 1
            self._cm = real_scope()
            return self._cm.__enter__()

        def __exit__(self, *a):
            open_sessions["count"] -= 1
            return self._cm.__exit__(*a)

    monkeypatch.setattr(H, "session_scope", lambda: Tracking())

    def note_sessions(*args, **kwargs):
        open_sessions["during_llm"].append(open_sessions["count"])
        return []

    monkeypatch.setattr(D, "extract_concepts_from", note_sessions)
    monkeypatch.setattr(D, "summarise_source", lambda *a, **k: (note_sessions(), "A summary.")[1])
    monkeypatch.setattr(D, "_neighbours", lambda db, concept, k=3: [])

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(db, title="Pool Safety Source", body="body", subtype="paste")
            made.append(src.slug)

        ctx = H.JobContext(job_id=0, deadline=time.monotonic() + 300)
        monkeypatch.setattr(ctx, "progress", lambda *a, **k: None)
        result = H.handle_distill({"source_slug": made[0]}, ctx)
        made += [result["literature"]] if result.get("literature") else []

        assert open_sessions["during_llm"], "the model calls never ran"
        assert all(n == 0 for n in open_sessions["during_llm"]), (
            f"a session was open during a model call: {open_sessions['during_llm']}"
        )
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_job_listing_pages_and_reports_the_whole_queue(client, auth):
    """A page of jobs is not the queue.

    /api/jobs returned only the newest 100 with no way to see past them, and silently ignored
    an offset. A cleanup that trusted it cancelled a third of a 195-job queue and reported
    nothing left — so the rest ran unattended.
    """
    from wiki_api.database import Job, session_scope

    made = []
    with session_scope() as db:
        for i in range(12):
            job = Job(kind="paste", status="queued", params={"n": i})
            db.add(job)
        db.commit()
        made = [j.id for j in db.query(Job).filter(Job.kind == "paste").all()]

    try:
        first = client.get("/api/jobs?limit=5&offset=0", headers=auth).json()
        second = client.get("/api/jobs?limit=5&offset=5", headers=auth).json()

        assert len(first["jobs"]) == 5 and len(second["jobs"]) == 5
        # Pages must not overlap, or paging through the queue silently repeats work.
        assert not ({j["id"] for j in first["jobs"]} & {j["id"] for j in second["jobs"]})
        # The counts describe the queue, not the page — that distinction is the bug.
        assert first["total"] >= 12
        assert first["total"] > len(first["jobs"])
        assert first["active"] >= 12

        only_queued = client.get("/api/jobs?status=queued&limit=100", headers=auth).json()
        assert all(j["status"] == "queued" for j in only_queued["jobs"])

        # Walking every page must reach every job.
        seen, offset = set(), 0
        while True:
            page = client.get(f"/api/jobs?limit=10&offset={offset}", headers=auth).json()
            if not page["jobs"]:
                break
            seen |= {j["id"] for j in page["jobs"]}
            offset += 10
        assert set(made) <= seen, "paging missed jobs that exist"
    finally:
        with session_scope() as db:
            for job_id in made:
                job = db.get(Job, job_id)
                if job:
                    db.delete(job)


# --- embeddings stay current --------------------------------------------------


@pytest.fixture
def fake_embedder(monkeypatch):
    """A deterministic stand-in, so these tests do not need the real model."""
    from wiki_api.services import embed

    def fake(title, body):
        # Distinct per content, so "did this get re-embedded?" is answerable.
        seed = float(len(f"{title}{body}") % 97) + 1.0
        return embed.to_bytes([seed, 1.0, 0.5])

    monkeypatch.setattr(embed, "embed_document", fake)
    return fake


def test_every_write_path_embeds_the_document(client, auth, fake_embedder):
    """Embeddings were set in one place, so most documents never had one.

    A source, a note and a literature note all have to end up searchable by meaning, or
    "related" goes quiet on new material and convergence stops seeing it.
    """
    from wiki_api.database import session_scope
    from wiki_api.services.content import (
        create_note,
        delete_doc,
        store_source,
        upsert_literature_note,
    )

    made = []
    try:
        with session_scope() as db:
            note = create_note(db, "Embedding Write Path", "body", subtype="zettel")
            made.append(note.slug)
            assert note.embedding is not None, "create_note left no embedding"

            src, _ = store_source(db, title="Embedding Source", body="text", subtype="paste")
            made.append(src.slug)
            assert src.embedding is not None, "store_source left no embedding"

            lit = upsert_literature_note(
                db, src, title="Embedding Source", body="summary", tags=["literature"]
            )
            made.append(lit.slug)
            assert lit.embedding is not None, "upsert_literature_note left no embedding"
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_editing_a_note_refreshes_its_embedding(client, auth, fake_embedder):
    """A stale vector is worse than none: it keeps matching the text you replaced."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import create_note, delete_doc, update_note

    try:
        with session_scope() as db:
            note = create_note(db, "Stale Vector", "original body", subtype="zettel")
            before = note.embedding

            update_note(db, note, body="a completely different body")
            assert note.embedding != before, "editing the body left the old vector in place"

            # A tag-only edit should not pay for a model call.
            after_body_edit = note.embedding
            update_note(db, note, tags=["zettel", "tagged"])
            assert note.embedding == after_body_edit
    finally:
        with session_scope() as db:
            delete_doc(db, "stale-vector")


def test_a_missing_model_leaves_the_previous_vector_alone(client, auth, monkeypatch):
    """Without a model we keep the old vector: None would hide the note from search entirely."""
    from wiki_api.database import session_scope
    from wiki_api.services import embed
    from wiki_api.services.content import create_note, delete_doc, update_note

    monkeypatch.setattr(embed, "embed_document", lambda title, body: embed.to_bytes([1.0, 2.0]))
    try:
        with session_scope() as db:
            note = create_note(db, "Model Goes Away", "body", subtype="zettel")
            original = note.embedding

        monkeypatch.setattr(embed, "embed_document", lambda title, body: None)
        with session_scope() as db:
            from wiki_api.services.content import get_doc

            note = get_doc(db, "model-goes-away")
            update_note(db, note, body="new body the model cannot embed")
            assert note.embedding == original, "a failed embedding must not erase the old one"
    finally:
        with session_scope() as db:
            delete_doc(db, "model-goes-away")


def test_redistilling_does_not_orphan_previously_linked_concepts(client, auth, monkeypatch):
    """A literature note is often the only thing linking to a concept.

    Rewriting its Concepts list outright orphaned every note the model did not re-extract —
    71 of them after one re-distillation, with nothing failing.
    """
    from wiki_api.database import session_scope
    from wiki_api.services import distill as D
    from wiki_api.services.content import create_note, delete_doc, get_doc, store_source

    monkeypatch.setattr(D, "call_llm", lambda *a, **k: "A summary.")
    monkeypatch.setattr(D, "summarise_source", lambda *a, **k: "A summary.")
    monkeypatch.setattr(D, "_neighbours", lambda db, concept, k=3: [])

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(db, title="Orphaning Source", body="body", subtype="paste")
            made.append(src.slug)
            first = create_note(db, "First Pass Concept", "body", subtype="zettel")
            made.append(first.slug)

            # Pass one links the concept the model found then.
            D.distill(db, src, concepts=[], summary="A summary.")
            lit = get_doc(db, D._write_literature_note(db, src, [(first.slug, "found first")]).slug)
            made.append(lit.slug)
            assert f"[[{first.slug}]]" in lit.body

            # Pass two finds something else entirely.
            second = create_note(db, "Second Pass Concept", "body", subtype="zettel")
            made.append(second.slug)
            D._write_literature_note(db, src, [(second.slug, "found second")])

            lit = get_doc(db, lit.slug)
            assert f"[[{second.slug}]]" in lit.body, "the new concept was not linked"
            assert f"[[{first.slug}]]" in lit.body, "re-distillation orphaned the earlier concept"
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


# --- the CLI ------------------------------------------------------------------


def test_cli_refuses_to_run_without_a_token(monkeypatch):
    """A missing token should explain how to get one, not raise a stack trace."""
    from wiki_cli.client import Wiki, WikiError

    monkeypatch.delenv("WIKI_TOKEN", raising=False)
    with pytest.raises(WikiError) as exc:
        Wiki(url="https://example.com")
    assert "auth/login" in str(exc.value)


def test_cli_reads_queue_depth_from_the_whole_queue(monkeypatch):
    """Not from one page — trusting a page is what let 95 jobs run unattended."""
    from wiki_cli.client import Wiki

    wiki = Wiki(url="https://example.com", token="t")
    monkeypatch.setattr(wiki, "get", lambda path, **kw: {"jobs": [], "total": 195, "active": 95})
    assert wiki.queue_depth() == 95


def test_cli_writes_a_source_the_importer_can_read(tmp_path):
    """The CLI's output format has to be exactly what import_markdown parses."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import import_markdown
    from wiki_cli.capture import Video, write_source

    # A title carrying its own double quotes — this broke frontmatter once.
    video = Video(id="abc12345678", title='Module 6.5: From "Attention" to Llama', duration=600)
    path = write_source(tmp_path, video, "Some transcript text.", "test-collection", via="whisper")

    with session_scope() as db:
        doc = import_markdown(db, path)
        try:
            assert doc is not None
            assert doc.doc_class == "source"
            assert doc.subtype == "youtube"
            assert doc.url == "https://www.youtube.com/watch?v=abc12345678"
            assert "Some transcript text." in doc.body
            # The provenance of a machine transcript must survive into the wiki.
            assert "Whisper" in doc.body
        finally:
            from wiki_api.services.content import delete_doc

            if doc:
                delete_doc(db, doc.slug)


def _long_transcript(paragraphs: int = 320) -> str:
    """A body several windows long, with paragraph breaks to cut on."""
    return "\n\n".join(f"Paragraph {i}. " + ("filler " * 40) for i in range(paragraphs))


def test_a_long_transcript_is_read_past_the_first_window(monkeypatch):
    """SOURCE_CHARS truncated at 24k, and nothing reported the loss.

    The first 62 lectures had a median transcript of 9,800 characters, so every one fitted and
    truncation never showed. An 80-minute CS336 lecture runs to 69,000-92,000 characters, and
    two thirds of each — including the half where the technical depth is — never reached the
    model at all.
    """
    from wiki_api.services import distill as D

    body = _long_transcript()
    assert len(body) > 3 * D.SOURCE_CHARS

    prompts = []

    def fake(prompt, system):
        prompts.append(prompt)
        n = len(prompts)
        return {"concepts": [{"name": f"Idea From Window {n}", "summary": "s", "why": "w"}]}

    monkeypatch.setattr(D, "call_llm_json", fake)
    concepts = D.extract_concepts_from("Long Lecture", body)

    assert len(prompts) >= 3, "the transcript was read in one window"
    # The decisive assertion: the end of the transcript reached the model.
    assert body[-120:] in prompts[-1]
    # Every window contributed, rather than the budget being spent on the opening.
    assert len(concepts) == len(prompts)


def test_a_short_source_is_read_in_exactly_one_call(monkeypatch):
    """Chunking must not change how the wiki's existing sources distil."""
    from wiki_api.services import distill as D

    prompts = []

    def fake(prompt, system):
        prompts.append(prompt)
        return {"concepts": [{"name": "Backpropagation", "summary": "s", "why": "w"}]}

    monkeypatch.setattr(D, "call_llm_json", fake)
    body = "A short transcript, of the length every existing lecture already has."
    D.extract_concepts_from("Short", body)

    assert len(prompts) == 1
    assert body in prompts[0]


def test_one_concept_named_twice_across_windows_becomes_one_concept(monkeypatch):
    """Two windows of one lecture both name its central idea.

    Left alone that forks a duplicate note, or spends a slot of the new-note budget
    rediscovering a note the previous window already made.
    """
    from wiki_api.services import distill as D

    replies = [
        {"concepts": [{"name": "Attention Mechanism", "summary": "long summary", "why": "w"}]},
        {"concepts": [{"name": "attention mechanisms", "summary": "s", "why": "w"}]},
        {"concepts": [{"name": "Rotary Positional Encoding", "summary": "s", "why": "w"}]},
        {"concepts": [{"name": "Speculative Decoding", "summary": "s", "why": "w"}]},
    ]
    calls = {"n": 0}

    def fake(prompt, system):
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply

    monkeypatch.setattr(D, "call_llm_json", fake)
    concepts = D.extract_concepts_from("Long Lecture", _long_transcript())

    names = [c.name for c in concepts]
    assert names.count("Attention Mechanism") == 1
    assert "attention mechanisms" not in names
    # The variant the other window used is a real alias, and aliases resolve wikilinks.
    attention = next(c for c in concepts if c.name == "Attention Mechanism")
    assert "attention mechanisms" in attention.aliases
    # A concept only the third window saw still survives.
    assert "Rotary Positional Encoding" in names


def test_the_new_note_budget_scales_with_transcript_length():
    """Six new notes is right for a ten-minute clip and wrong for an eighty-minute lecture."""
    from wiki_api.services import distill as D

    assert D.max_new_for("x" * 9_800) == D.MAX_NEW_ZETTELS
    assert D.max_new_for("x" * 69_000) > D.MAX_NEW_ZETTELS
    # One pathological source cannot mint fifty stubs.
    assert D.max_new_for("x" * 5_000_000) == D.MAX_NEW_CEILING


def test_chunked_extraction_holds_no_session_across_any_window(monkeypatch):
    """The pool-exhaustion bug, now with four model calls per source instead of one.

    Holding a pooled connection across the model calls took the whole site down once. Chunking
    multiplies the calls, so this property matters more than it did before.
    """
    import wiki_api.jobs.handlers as H
    from wiki_api.database import session_scope
    from wiki_api.services import distill as D
    from wiki_api.services.content import delete_doc, store_source

    open_sessions = {"count": 0, "during_llm": []}
    real_scope = H.session_scope

    class Tracking:
        def __enter__(self):
            open_sessions["count"] += 1
            self._cm = real_scope()
            return self._cm.__enter__()

        def __exit__(self, *a):
            open_sessions["count"] -= 1
            return self._cm.__exit__(*a)

    monkeypatch.setattr(H, "session_scope", lambda: Tracking())

    # Patch the LLM layer, not the extract/summarise functions, so the real chunk loop runs.
    def fake_json(prompt, system):
        open_sessions["during_llm"].append(open_sessions["count"])
        return {"concepts": []}

    def fake_text(prompt, system):
        open_sessions["during_llm"].append(open_sessions["count"])
        return "A summary."

    monkeypatch.setattr(D, "call_llm_json", fake_json)
    monkeypatch.setattr(D, "call_llm", fake_text)
    monkeypatch.setattr(D, "_neighbours", lambda db, concept, k=3: [])

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(
                db, title="Long Pool Safety Source", body=_long_transcript(), subtype="paste"
            )
            made.append(src.slug)

        ctx = H.JobContext(job_id=0, deadline=time.monotonic() + 300)
        monkeypatch.setattr(ctx, "progress", lambda *a, **k: None)
        result = H.handle_distill({"source_slug": made[0]}, ctx)
        made += [result["literature"]] if result.get("literature") else []

        assert len(open_sessions["during_llm"]) >= 4, "the windows never ran"
        assert all(n == 0 for n in open_sessions["during_llm"]), (
            f"a session was open during a model call: {open_sessions['during_llm']}"
        )
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_the_literature_note_reads_the_whole_source_not_its_opening(monkeypatch):
    """A summary of the first third of a lecture presented itself as the summary of all of it."""
    from wiki_api.services import distill as D

    body = _long_transcript()
    seen = {}
    monkeypatch.setattr(D, "call_llm", lambda p, s: (seen.setdefault("prompt", p) and "") or "ok")
    D.summarise_source("Long Lecture", body)

    assert body[-120:] in seen["prompt"], "the close of the source never reached the model"
    assert len(seen["prompt"]) < len(body), "the whole body was sent unbudgeted"


def test_import_carries_the_moc_through_to_distillation(client, auth, monkeypatch):
    """`wiki channel --moc` sent moc as a multipart field and FastAPI discarded it.

    job_import declared only file and distill, so distill() saw moc=None — and it files into a
    Map of Content only when both moc and moc_title are truthy. A whole course imported with
    no MOC entry, and nothing reported it.
    """
    import io
    import zipfile

    from wiki_api.database import Job, session_scope
    from wiki_api.jobs import runner as R

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "sources/src-a.md", "---\ntitle: A\nclass: source\ntype: youtube\n---\n\nBody.\n"
        )

    res = client.post(
        "/api/jobs/import",
        files={"file": ("import.zip", buf.getvalue(), "application/zip")},
        data={"distill": "false", "moc": "moc-cs336", "moc_title": "Stanford CS336"},
        headers=auth,
    )
    assert res.status_code == 200, res.text
    job_id = res.json()["id"]

    try:
        with session_scope() as db:
            params = dict(db.get(Job, job_id).params or {})
        assert params["moc"] == "moc-cs336"
        assert params["moc_title"] == "Stanford CS336"

        # …and that it survives the hop into the distill job the runner queues.
        queued = []
        monkeypatch.setattr(R, "enqueue", lambda db, kind, p, payload=None: queued.append(p))
        R._queue_distillation("import", {**params, "distill": True}, {"sources": ["src-a"]})
        assert queued and queued[0]["moc"] == "moc-cs336"
    finally:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job:
                db.delete(job)
                db.commit()


def test_module_of_recognises_lecture_numbers():
    """CS336 numbers lectures, not modules, so all 18 of them filed as "other"."""
    from wiki_cli.capture import module_of

    cs336 = "Stanford CS336 Language Modeling from Scratch | Spring 2026 | Lecture 4: Attention"
    assert module_of(cs336) == "lecture-04"  # zero-padded so 4 sorts before 12
    assert module_of(cs336.replace("Lecture 4", "Lecture 12")) == "lecture-12"
    # The conventions the existing 62 sources were captured under must not move.
    assert module_of("AIM - Module 2.4: Backpropagation") == "module-2"
    assert module_of("Week 2 Live Session — Gradients") == "live-sessions"


def test_course_boilerplate_is_stripped_without_touching_existing_titles():
    """The importer derives the slug from the title, so normalising titles re-slugs sources.

    "Stanford CS336 Language Modeling from Scratch | Spring 2026 | " spends 62 of a slug's 80
    characters before saying anything. The pattern is anchored tightly because 196 sources are
    already captured under their own titles, and a normaliser that caught one of those would
    re-slug it and import a second copy.
    """
    from wiki_cli.capture import normalise_title
    from wiki_core.utils import slugify

    raw = "Stanford CS336 Language Modeling from Scratch | Spring 2026 | Lecture 4: Attention"
    assert normalise_title(raw) == "CS336 Lecture 4: Attention"
    assert slugify(normalise_title(raw)) == "cs336-lecture-4-attention"

    for untouched in (
        "AIM - Module 2.4: Backpropagation - The Chain Rule in Action",
        "Week 2 Live Session — Backpropagation, Gradients & Jacobians",
        "Admin API - Claude Platform Docs",
        'Module 6.5: From "Attention" to Llama',
    ):
        assert normalise_title(untouched) == untouched


def test_a_shortened_title_keeps_the_original_as_an_alias(tmp_path):
    """The title YouTube published is still how you would search for the lecture."""
    from wiki_api.database import session_scope
    from wiki_api.services.content import delete_doc, import_markdown
    from wiki_cli.capture import Video, write_source

    raw = "Stanford CS336 Language Modeling from Scratch | Spring 2026 | Lecture 4: Attention"
    path = write_source(
        tmp_path, Video(id="c" * 11, title=raw), "Transcript.", "cs336", via="captions"
    )

    with session_scope() as db:
        doc = import_markdown(db, path)
        try:
            assert doc.slug == "src-cs336-lecture-4-attention"
            assert doc.title == "CS336 Lecture 4: Attention"
            assert raw in (doc.extra or {}).get("aliases", [])
            # The collection has to land, or crosslink cannot be scoped to this course.
            assert doc.collection == "cs336"
        finally:
            delete_doc(db, doc.slug)


def test_cli_capture_state_resumes_rather_than_restarting(tmp_path):
    from wiki_cli.capture import CaptureState, Video

    state = CaptureState.load(tmp_path / "state.json")
    videos = [Video(id="a" * 11, title="One"), Video(id="b" * 11, title="Two")]
    assert len(state.outstanding(videos)) == 2

    state.done["a" * 11] = {"slug": "src-one"}
    state.save()

    reloaded = CaptureState.load(tmp_path / "state.json")
    assert [v.title for v in reloaded.outstanding(videos)] == ["Two"]


# --- performance guard --------------------------------------------------------


def test_graph_queries_stay_fast_at_current_scale(client, auth):
    """These load every document body on every request.

    Fine at this size — measured at 0.4-0.6s on a 725-document wiki — but it grows linearly,
    and this is the tripwire. If it fires, the fix is a links table that stores resolved edges
    rather than re-parsing every body; see CLAUDE.md.
    """
    budget = 5.0
    for path in ("/api/graph", "/api/orphans", "/api/stats", "/api/documents/index"):
        start = time.monotonic()
        assert client.get(path, headers=auth).status_code == 200
        elapsed = time.monotonic() - start
        assert elapsed < budget, f"{path} took {elapsed:.1f}s, over the {budget}s budget"


# --- cross-source linking -----------------------------------------------------


def test_crosslink_candidates_skip_same_source_and_existing_links(client, auth, fake_embedder):
    """Concepts from one source are already linked by distillation.

    Re-proposing them wastes a model call and adds nothing; the point of this pass is the
    links distillation structurally cannot make.
    """
    from wiki_api.database import session_scope
    from wiki_api.services.content import create_note, delete_doc, get_doc, store_source
    from wiki_api.services.crosslink import candidates

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(db, title="Shared Source", body="body", subtype="paste")
            made.append(src.slug)
            subject = create_note(db, "Crosslink Subject", "About widgets.", subtype="zettel")
            sibling = create_note(db, "Crosslink Sibling", "About widgets too.", subtype="zettel")
            other = create_note(db, "Crosslink Other", "About widgets elsewhere.", subtype="zettel")
            linked = create_note(db, "Crosslink Linked", "Already referenced.", subtype="zettel")
            made += [subject.slug, sibling.slug, other.slug, linked.slug]

            # sibling shares the subject's source; linked is already referenced
            subject.derived_from_id = sibling.derived_from_id = src.id
            db.commit()
            from wiki_api.services.content import update_note

            update_note(db, get_doc(db, subject.slug), body=f"About widgets. [[{linked.slug}]]")

            found = {d.slug for d in candidates(db, get_doc(db, subject.slug))}
            assert sibling.slug not in found, "a same-source concept was proposed"
            assert linked.slug not in found, "an already-linked note was proposed"
            assert subject.slug not in found
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_crosslink_discards_what_the_model_cannot_justify(monkeypatch):
    """A link with no stated reason is exactly the noise this is meant to avoid."""
    from wiki_api.database import Document
    from wiki_api.services import crosslink

    subject = Document(slug="subject", title="Subject", body="Text.", doc_class="note")
    options = [
        Document(slug="good", title="Good", body="Text.", doc_class="note"),
        Document(slug="vague", title="Vague", body="Text.", doc_class="note"),
    ]
    monkeypatch.setattr(
        crosslink,
        "call_llm_json",
        lambda *a, **k: {
            "links": [
                {"slug": "good", "reason": "is the loss the subject is trained with"},
                {"slug": "vague"},  # no reason
                {"slug": "hallucinated", "reason": "not one of the candidates"},
            ]
        },
    )
    assert crosslink.propose(subject, options) == [
        ("good", "is the loss the subject is trained with")
    ]


def test_crosslink_writes_both_directions(client, auth, fake_embedder, monkeypatch):
    from wiki_api.database import session_scope
    from wiki_api.services import crosslink
    from wiki_api.services.content import create_note, delete_doc, get_doc

    made = []
    try:
        with session_scope() as db:
            a = create_note(db, "Crosslink Alpha", "Alpha text.", subtype="zettel")
            b = create_note(db, "Crosslink Beta", "Beta text.", subtype="zettel")
            made += [a.slug, b.slug]
            written = crosslink.apply_links(db, a.slug, [(b.slug, "is what alpha is trained with")])
            assert written == 1
            assert f"[[{b.slug}]]" in get_doc(db, a.slug).body
            assert f"[[{a.slug}]]" in get_doc(db, b.slug).body, "the link is only visible one way"
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)


def test_crosslink_proposes_ideas_not_paperwork(client, auth, fake_embedder):
    """A literature note is already reachable from every concept it lists.

    Linking one here adds an edge without joining two ideas, which is what this pass exists
    to do — the first probe spent two of its three links exactly that way.
    """
    from wiki_api.database import session_scope
    from wiki_api.services.content import create_note, delete_doc, get_doc, store_source
    from wiki_api.services.crosslink import candidates

    made = []
    try:
        with session_scope() as db:
            src, _ = store_source(db, title="Idea Filter Source", body="widgets", subtype="paste")
            made.append(src.slug)
            subject = create_note(db, "Idea Filter Subject", "About widgets.", subtype="zettel")
            concept = create_note(db, "Idea Filter Concept", "Widgets in depth.", subtype="zettel")
            made += [subject.slug, concept.slug]
            lit = create_note(
                db, "Idea Filter Summary", "A source about widgets.", subtype="literature"
            )
            made.append(lit.slug)

            found = {d.slug for d in candidates(db, get_doc(db, subject.slug))}
            assert lit.slug not in found, "a literature note was proposed as an idea link"
    finally:
        with session_scope() as db:
            for slug in made:
                delete_doc(db, slug)
