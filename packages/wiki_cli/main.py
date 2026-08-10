"""Typer CLI for LLM Wiki."""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from wiki_core.config import BASE_DIR, load_dotenv
from wiki_core.ingest import ingest_arxiv, ingest_pdf, ingest_web, ingest_youtube
from wiki_core.lint import auto_link_suggestions, graph_stats, lint_wiki
from wiki_core.log import append_log
from wiki_core.rag import ai_lint_wiki, ai_summarize_source, query_wiki
from wiki_core.search import search
from wiki_core.zettel import new_zettel

load_dotenv()
app = typer.Typer(help="LLM Wiki + Zettelkasten CLI", no_args_is_help=True)
console = Console()

API_URL = os.environ.get("WIKI_API_URL", "").rstrip("/")


def _api_request(method: str, path: str, **kwargs):
    import urllib.request

    token = os.environ.get("WIKI_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{API_URL}{path}"
    data = json.dumps(kwargs.get("json", {})).encode() if kwargs.get("json") else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


@app.command("search")
def search_cmd(query: str, limit: int = 10, json_out: bool = typer.Option(False, "--json")):
    """BM25 search across wiki and sources."""
    if API_URL:
        results = _api_request("GET", f"/api/search?q={query}&limit={limit}")
        if json_out:
            console.print_json(data=results)
            return
        for r in results.get("results", []):
            console.print(f"[bold]{r['score']:.2f}[/] {r['title']} ({r['path']})")
        return
    results = search(query, top_k=limit)
    if json_out:
        console.print_json(data=[r.__dict__ for r in results])
        return
    for r in results:
        console.print(f"[bold]{r.score:.2f}[/] {r.title} ({r.path})")
        if r.snippet:
            console.print(f"  …{r.snippet}…")


@app.command()
def query(question: str):
    """RAG query with OpenRouter LLM."""
    if API_URL:
        r = _api_request("POST", "/api/llm/query", json={"question": question})
        console.print(r.get("answer", ""))
        return
    answer = query_wiki(question)
    console.print(answer)


@app.command("new-zettel")
def new_zettel_cmd(title: str):
    """Create a new atomic zettel."""
    if API_URL:
        r = _api_request("POST", "/api/zettels", json={"title": title})
        console.print(f"Created: {r.get('slug')}")
        return
    slug = new_zettel(title)
    console.print(f"Created zettel: wiki/atomic/{slug}.md")


@app.command("ai-summarize")
def ai_summarize(source: str):
    """Generate literature note from raw source."""
    path = str((BASE_DIR / source).resolve()) if not source.startswith("/") else source
    if API_URL:
        r = _api_request("POST", "/api/llm/summarize", json={"source_path": source})
        console.print(r.get("path", ""))
        return
    out = ai_summarize_source(path)
    console.print(f"Saved: {out}")


@app.command("ai-lint")
def ai_lint_cmd():
    """LLM graph audit."""
    if API_URL:
        r = _api_request("POST", "/api/llm/audit")
        console.print(r.get("report", ""))
        return
    console.print(ai_lint_wiki())


@app.command("ingest-youtube")
def ingest_youtube_cmd(url: str):
    if API_URL:
        r = _api_request("POST", "/api/ingest/youtube", json={"url": url})
        console.print(r.get("path", ""))
        return
    console.print(ingest_youtube(url))


@app.command("ingest-web")
def ingest_web_cmd(url: str):
    if API_URL:
        r = _api_request("POST", "/api/ingest/web", json={"url": url})
        console.print(r.get("path", ""))
        return
    console.print(ingest_web(url))


@app.command("ingest-pdf")
def ingest_pdf_cmd(path: str):
    if API_URL:
        console.print("Use API upload endpoint for remote PDF ingest.")
        raise typer.Exit(1)
    console.print(ingest_pdf(path))


@app.command("ingest-arxiv")
def ingest_arxiv_cmd(id_or_url: str):
    if API_URL:
        r = _api_request("POST", "/api/ingest/arxiv", json={"id_or_url": id_or_url})
        console.print(r.get("path", ""))
        return
    console.print(ingest_arxiv(id_or_url))


@app.command()
def stats(json_out: bool = typer.Option(False, "--json")):
    """Graph statistics."""
    if API_URL:
        data = _api_request("GET", "/api/stats")
    else:
        data = graph_stats()
    if json_out:
        console.print_json(data=data)
        return
    table = Table(title="Wiki Stats")
    table.add_column("Metric")
    table.add_column("Value")
    for k, v in data.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)


@app.command()
def lint():
    """Check broken links, orphans, missing UIDs."""
    if API_URL:
        r = _api_request("GET", "/api/lint")
        issues = r.get("issues", [])
    else:
        issues = lint_wiki()
    if not issues:
        console.print("[green]No issues found.[/]")
        return
    for i in issues:
        if isinstance(i, str):
            console.print(f"[red]{i}[/]")
        else:
            console.print(f"[red]{i.kind}[/] {i.path}: {i.message}")


@app.command("auto-link")
def auto_link(apply: bool = typer.Option(False, "--apply")):
    """Suggest or apply wikilink opportunities."""
    suggestions = auto_link_suggestions()
    if not apply:
        for rel, term, slug in suggestions:
            console.print(f"• {rel}: '{term}' → [[{slug}]]")
        console.print(f"\nTotal: {len(suggestions)}")
        return
    console.print("Auto-apply not yet implemented for safety; review suggestions manually.")


@app.command()
def log(action: str, summary: str):
    """Append to wiki/log.md."""
    if API_URL:
        _api_request("POST", "/api/log", json={"action": action, "summary": summary})
        return
    line = append_log(action, summary)
    console.print(line)


@app.command()
def read(slug: str):
    """Read a wiki page by slug."""
    if API_URL:
        r = _api_request("GET", f"/api/pages/{slug}")
        console.print(r.get("content", ""))
        return
    from wiki_core.graph import get_page_by_slug

    path = get_page_by_slug(slug)
    if not path:
        console.print(f"[red]Page not found: {slug}[/]")
        raise typer.Exit(1)
    console.print(path.read_text(encoding="utf-8"))


@app.command()
def login(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    api_url: Optional[str] = typer.Option(None, help="API base URL"),
):
    """Login and save API token."""
    import urllib.request

    base = (api_url or API_URL or "http://localhost:8000").rstrip("/")
    data = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read().decode())
    token = token_data["access_token"]
    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    lines = [l for l in lines if not l.startswith("WIKI_API_TOKEN=") and not l.startswith("WIKI_API_URL=")]
    lines.append(f"WIKI_API_URL={base}")
    lines.append(f"WIKI_API_TOKEN={token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Logged in. Token saved to .env[/]")


if __name__ == "__main__":
    app()
