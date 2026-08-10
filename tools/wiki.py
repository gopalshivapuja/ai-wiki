#!/usr/bin/env python3
"""
LLM Wiki & Zettelkasten Manager CLI

Commands:
    new-zettel "Title"          Create a new atomic zettel note with timestamp UID -> wiki/atomic/
    ingest-youtube <URL or ID>  Fetch YouTube transcript & metadata -> sources/youtube/
    ingest-web <URL>            Scrape web article -> sources/web/
    ingest-pdf <PDF_PATH>       Extract text from PDF -> sources/pdfs/
    ingest-arxiv <ID or URL>    Fetch arXiv research paper metadata & abstract -> sources/pdfs/
    search "<query>"            BM25 relevance-ranked search across wiki & sources
    query "<question>"          RAG search + OpenRouter LLM answer synthesis with citations & model fallbacks
    ai-summarize <source_file>  OpenRouter LLM automated literature note generation with fallbacks
    ai-lint                     OpenRouter LLM knowledge graph consistency & gap audit with fallbacks
    stats                       Compute network density, zettel metrics & hub notes
    auto-link                   Scan wiki for missing bidirectional wikilink opportunities
    lint                        Check wiki for broken links, orphans, missing UIDs & bloated notes
    log <ACTION> <SUMMARY>      Append entry to wiki/log.md
"""

import sys
import os
import re
import math
import datetime
import urllib.request
import urllib.error
import json
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
SOURCES_DIR = BASE_DIR / "sources"
WIKI_DIR = BASE_DIR / "wiki"
ATOMIC_DIR = WIKI_DIR / "atomic"
INDEX_FILE = WIKI_DIR / "index.md"
LOG_FILE = WIKI_DIR / "log.md"
ENV_FILE = BASE_DIR / ".env"

def load_dotenv_env():
    """Load variables from .env file into os.environ if present."""
    if ENV_FILE.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(ENV_FILE)
        except ImportError:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

load_dotenv_env()

def get_openrouter_models():
    primary = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
    fallbacks_str = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
    models = []
    if primary:
        models.append(primary)
    if fallbacks_str:
        for m in fallbacks_str.split(","):
            m_clean = m.strip()
            if m_clean and m_clean not in models:
                models.append(m_clean)
    
    # Default recommended fallback list (openrouter/free auto-routes to active free models)
    default_list = [
        "openrouter/free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "cohere/north-mini-code:free"
    ]
    for m in default_list:
        if m not in models:
            models.append(m)
    return models

def call_openrouter(prompt: str, system_prompt: str = "You are a helpful AI Knowledge Base Assistant.") -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key or api_key == "your_openrouter_api_key_here":
        print("\n[ERROR] OpenRouter API key not configured!")
        print(f"Please add your OPENROUTER_API_KEY to '{ENV_FILE}'.")
        print("Example in .env: OPENROUTER_API_KEY=sk-or-v1-...\n")
        return ""

    models = get_openrouter_models()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/llm-wiki/wiki",
        "X-Title": "LLM Wiki Agent",
        "Content-Type": "application/json"
    }

    last_error = None
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 2048
        }

        print(f"Querying OpenRouter LLM ({model})...")
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30) as resp:
                res_json = json.loads(resp.read().decode('utf-8'))
                text = res_json['choices'][0]['message']['content'].strip()
                if text:
                    print(f"-> Successfully generated response using model: '{model}'\n")
                    return text
        except urllib.error.HTTPError as http_err:
            last_error = f"HTTP {http_err.code}: {http_err.reason}"
            print(f"[FALLBACK NOTICE] Model '{model}' returned {last_error}. Trying next fallback...")
        except Exception as e:
            last_error = str(e)
            print(f"[FALLBACK NOTICE] Model '{model}' failed: {e}. Trying next fallback...")

    print(f"\n[ERROR] All candidate models failed. Last error: {last_error}")
    return ""

def ensure_directories():
    (SOURCES_DIR / "youtube").mkdir(parents=True, exist_ok=True)
    (SOURCES_DIR / "web").mkdir(parents=True, exist_ok=True)
    (SOURCES_DIR / "pdfs").mkdir(parents=True, exist_ok=True)
    (SOURCES_DIR / "documents").mkdir(parents=True, exist_ok=True)
    (SOURCES_DIR / "assets").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "templates").mkdir(parents=True, exist_ok=True)
    ATOMIC_DIR.mkdir(parents=True, exist_ok=True)
    (WIKI_DIR / "concepts").mkdir(parents=True, exist_ok=True)
    (WIKI_DIR / "entities").mkdir(parents=True, exist_ok=True)
    (WIKI_DIR / "sources").mkdir(parents=True, exist_ok=True)
    (WIKI_DIR / "syntheses").mkdir(parents=True, exist_ok=True)

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text.strip('-')[:80]

def append_to_log(action_type: str, summary: str):
    ensure_directories()
    today = datetime.date.today().isoformat()
    log_line = f"## [{today}] {action_type} | {summary}\n"
    
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# LLM Wiki Activity Log\n\nChronological record of wiki operations.\n\n")
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line)
    print(f"Log appended: {log_line.strip()}")

# --- Zettelkasten Helper ---
def new_zettel(title: str):
    ensure_directories()
    now = datetime.datetime.now()
    uid = now.strftime("%Y%m%d%H%M%S")
    slug = slugify(title)
    filename = f"{uid}-{slug}.md"
    target_path = ATOMIC_DIR / filename

    today = now.strftime("%Y-%m-%d")
    content = f"""---
uid: "{uid}"
title: "{title}"
type: zettel
created: {today}
updated: {today}
tags: [zettel, atomic]
sources: []
---

# {title}

**UID:** `{uid}`  
**Created:** {today}  

## Context & Core Principle

*State the single atomic concept or idea clearly in self-contained detail.*

## Related Knowledge & Links

- `[[moc-llm-architectures]]` — Map of Content grouping architectural concepts.
"""
    target_path.write_text(content, encoding="utf-8")
    print(f"Created new atomic zettel: {target_path}")
    append_to_log("zettel", f"Created atomic zettel '{title}' (UID: {uid})")

# --- OpenRouter RAG Knowledge Query ---
def query_wiki_llm(question: str):
    ensure_directories()
    query_terms = [t.lower() for t in re.findall(r'\w+', question) if len(t) > 2]
    files = list(WIKI_DIR.rglob("*.md"))
    doc_freqs = {}
    doc_tokens = {}

    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        tokens = [t.lower() for t in re.findall(r'\w+', text)]
        doc_tokens[f] = tokens
        for token in set(tokens):
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    N = len(files)
    scores = []
    for f in files:
        tokens = doc_tokens[f]
        if not tokens:
            continue
        score = 0.0
        doc_len = len(tokens)
        for q_term in query_terms:
            tf = tokens.count(q_term)
            if tf > 0:
                df = doc_freqs.get(q_term, 1)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                norm_tf = (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * (doc_len / 300.0)))
                score += idf * norm_tf
        if score > 0:
            scores.append((score, f))

    scores.sort(key=lambda x: x[0], reverse=True)
    top_docs = [f for score, f in scores[:5]]

    if not top_docs:
        print("No relevant context found in wiki for this query.")
        top_docs = list(WIKI_DIR.rglob("*.md"))[:3]

    context_blocks = []
    for f in top_docs:
        rel_path = f.relative_to(BASE_DIR)
        context_blocks.append(f"--- START FILE: {rel_path} (Stem: {f.stem}) ---\n{f.read_text(encoding='utf-8')}\n--- END FILE ---")

    context_str = "\n\n".join(context_blocks)
    system_prompt = (
        "You are an expert AI Knowledge Base Assistant maintaining an LLM Wiki with Zettelkasten architecture.\n"
        "Answer the user's question accurately using ONLY the provided context files.\n"
        "Always cite your sources using Obsidian wikilinks syntax `[[note-stem]]` or `[[note-stem|Display Title]]`.\n"
        "Format your answer with clear headers, bullet points, and markdown."
    )

    user_prompt = f"USER QUESTION: {question}\n\nRELEVANT WIKI CONTEXT:\n{context_str}\n\nANSWER:"
    answer = call_openrouter(user_prompt, system_prompt)

    if answer:
        print("\n=======================================================")
        print(f"  AI KNOWLEDGE BASE ANSWER ({question})")
        print("=======================================================\n")
        print(answer)
        print("\n=======================================================\n")
        append_to_log("query", f"LLM RAG Query executed: '{question}'")

# --- OpenRouter AI Source Summarizer ---
def ai_summarize_source(source_path_str: str):
    ensure_directories()
    path = Path(source_path_str).resolve()
    if not path.exists():
        print(f"Error: Source file not found at {path}")
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    system_prompt = (
        "You are an expert LLM Knowledge Base Summarizer.\n"
        "Read the raw source text and generate a structured Literature Note in markdown.\n"
        "Include:\n"
        "1. Executive Summary & Core Claims\n"
        "2. Key Takeaways (numbered)\n"
        "3. Proposed Atomic Zettels (single concepts to extract into wiki/atomic/)\n"
        "4. Suggested Wikilinks (`[[concept]]`)"
    )

    prompt = f"SOURCE FILE: {path.name}\n\nRAW CONTENT:\n{text[:8000]}\n\nLITERATURE NOTE SUMMARY:"
    summary_res = call_openrouter(prompt, system_prompt)

    if summary_res:
        today = datetime.date.today().isoformat()
        slug = slugify(path.stem)
        target_path = WIKI_DIR / "sources" / f"{slug}.md"
        lit_content = f"""---
title: "Source Summary: {path.stem}"
type: source
created: {today}
updated: {today}
tags: [source-summary, ai-generated]
sources:
  - "sources/{path.parent.name}/{path.name}"
---

# Source Summary: {path.stem}

**Original Source:** `{path.name}`  
**Ingested:** {today}  

---

{summary_res}
"""
        target_path.write_text(lit_content, encoding="utf-8")
        print(f"\nSaved AI Literature Note Summary to: {target_path}")
        append_to_log("ai-summarize", f"Generated AI Literature Note for '{path.name}'")

# --- OpenRouter AI Wiki Health Audit ---
def ai_lint_wiki():
    ensure_directories()
    index_text = INDEX_FILE.read_text(encoding="utf-8") if INDEX_FILE.exists() else ""
    atomic_titles = [f.stem for f in ATOMIC_DIR.glob("*.md")] if ATOMIC_DIR.exists() else []

    system_prompt = (
        "You are a Knowledge Base Graph Auditor.\n"
        "Analyze the provided wiki index and atomic zettel list. Identify:\n"
        "1. Conceptual gaps (topics missing from the knowledge base)\n"
        "2. Structural recommendations for new Maps of Content (MOCs)\n"
        "3. Research suggestions for further ingestion"
    )

    prompt = f"WIKI INDEX:\n{index_text}\n\nATOMIC ZETTELS:\n{atomic_titles}\n\nAUDIT REPORT:"
    audit = call_openrouter(prompt, system_prompt)

    if audit:
        print("\n=======================================================")
        print("  AI KNOWLEDGE BASE GRAPH AUDIT REPORT")
        print("=======================================================\n")
        print(audit)
        print("\n=======================================================\n")
        append_to_log("ai-lint", "Executed LLM AI Knowledge Graph Audit")

# --- ArXiv Ingest ---
def ingest_arxiv(id_or_url: str):
    ensure_directories()
    m = re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', id_or_url)
    arxiv_id = m.group(1) if m else id_or_url.strip()

    api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    print(f"Fetching arXiv paper metadata for ID '{arxiv_id}'...")
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode('utf-8')
    except Exception as e:
        print(f"Error fetching arXiv API: {e}")
        return

    title_m = re.search(r'<title>(.*?)</title>', xml, re.DOTALL)
    title = title_m.group(1).strip().replace('\n', ' ') if title_m else f"arXiv Paper {arxiv_id}"
    if '<entry>' in xml:
        entry_part = xml.split('<entry>')[1]
        etitle_m = re.search(r'<title>(.*?)</title>', entry_part, re.DOTALL)
        if etitle_m:
            title = etitle_m.group(1).strip().replace('\n', ' ')

    summary_m = re.search(r'<summary>(.*?)</summary>', xml, re.DOTALL)
    summary = summary_m.group(1).strip().replace('\n', ' ') if summary_m else "No abstract available."

    authors = re.findall(r'<name>(.*?)</name>', xml)
    authors_str = ", ".join(authors[:5]) if authors else "Unknown Authors"

    slug = slugify(title) or f"arxiv-{arxiv_id}"
    filename = f"{slug}.md"
    target_path = SOURCES_DIR / "pdfs" / filename

    today = datetime.date.today().isoformat()
    content = f"""---
title: "{title}"
type: pdf_source
arxiv_id: "{arxiv_id}"
url: "https://arxiv.org/abs/{arxiv_id}"
authors: "{authors_str}"
ingested: {today}
---

# {title}

**arXiv ID:** [{arxiv_id}](https://arxiv.org/abs/{arxiv_id})  
**Authors:** {authors_str}  
**Ingested:** {today}  

---

## Abstract

{summary}
"""
    target_path.write_text(content, encoding="utf-8")
    print(f"Saved arXiv raw source to: {target_path}")

    lit_path = WIKI_DIR / "sources" / filename
    lit_content = f"""---
title: "Source Summary: {title}"
type: source
created: {today}
updated: {today}
tags: [source-summary, arxiv, paper]
sources:
  - "sources/pdfs/{filename}"
---

# Source Summary: {title}

**Original Source:** [[{slug}|{title} (arXiv:{arxiv_id})]]  
**Authors:** {authors_str}  
**Ingested:** {today}  

---

## Abstract & Key Takeaways

{summary}

---

## Linked Concepts & Entities
- `[[moc-llm-architectures]]`
"""
    lit_path.write_text(lit_content, encoding="utf-8")
    print(f"Created literature note summary in: {lit_path}")
    append_to_log("ingest", f"arXiv paper ingested: '{title}' (arXiv:{arxiv_id})")

# --- Local Hybrid BM25 / TF-IDF Search ---
def search_wiki(query: str, top_k: int = 5):
    ensure_directories()
    query_terms = [t.lower() for t in re.findall(r'\w+', query) if len(t) > 2]
    if not query_terms:
        print("Search query too short.")
        return

    files = list(WIKI_DIR.rglob("*.md")) + list(SOURCES_DIR.rglob("*.md"))
    doc_freqs = {}
    doc_tokens = {}
    doc_titles = {}

    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        tokens = [t.lower() for t in re.findall(r'\w+', text)]
        doc_tokens[f] = tokens
        
        t_match = re.search(r'^#\s+(.*)$', text, re.MULTILINE)
        doc_titles[f] = t_match.group(1).strip() if t_match else f.stem

        unique_tokens = set(tokens)
        for token in unique_tokens:
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    N = len(files)
    scores = []

    for f in files:
        tokens = doc_tokens[f]
        if not tokens:
            continue
        score = 0.0
        doc_len = len(tokens)
        
        for q_term in query_terms:
            tf = tokens.count(q_term)
            if tf > 0:
                df = doc_freqs.get(q_term, 1)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                norm_tf = (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * (doc_len / 300.0)))
                score += idf * norm_tf

        if score > 0:
            scores.append((score, f))

    scores.sort(key=lambda x: x[0], reverse=True)

    print(f"\n--- Search Results for '{query}' ({len(scores)} matches) ---")
    for score, f in scores[:top_k]:
        rel_path = f.relative_to(BASE_DIR)
        title = doc_titles[f]
        text = f.read_text(encoding="utf-8", errors="ignore")
        snippet = ""
        for q_term in query_terms:
            idx = text.lower().find(q_term)
            if idx != -1:
                start = max(0, idx - 40)
                end = min(len(text), idx + 100)
                snippet = text[start:end].replace('\n', ' ')
                break
        print(f"• [{score:.2f}] {title} ({rel_path})")
        if snippet:
            print(f"   Snippet: \"...{snippet}...\"")
    print()

# --- Graph Statistics & Analytics ---
def graph_stats():
    ensure_directories()
    print("\n--- Knowledge Base & Zettel Analytics ---")
    
    atomic_files = list(ATOMIC_DIR.glob("*.md")) if ATOMIC_DIR.exists() else []
    concept_files = list((WIKI_DIR / "concepts").glob("*.md"))
    entity_files = list((WIKI_DIR / "entities").glob("*.md"))
    source_summary_files = list((WIKI_DIR / "sources").glob("*.md"))
    moc_files = [f for f in (WIKI_DIR / "syntheses").glob("*.md") if f.name.startswith("moc-")]
    raw_sources = list(SOURCES_DIR.rglob("*.md"))

    print(f"Total Atomic Zettels: {len(atomic_files)}")
    print(f"Total Concept Pages: {len(concept_files)}")
    print(f"Total Entity Pages:  {len(entity_files)}")
    print(f"Literature Summaries:{len(source_summary_files)}")
    print(f"Maps of Content:     {len(moc_files)}")
    print(f"Raw Source Files:    {len(raw_sources)}")

    wikilink_pattern = re.compile(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]')
    total_links = 0
    all_wiki = list(WIKI_DIR.rglob("*.md"))
    for f in all_wiki:
        text = f.read_text(encoding="utf-8")
        total_links += len(wikilink_pattern.findall(text))

    avg_links = (total_links / len(all_wiki)) if all_wiki else 0
    print(f"Total Internal Wikilinks: {total_links}")
    print(f"Average Links per Note:   {avg_links:.2f}\n")

# --- Auto-Link Opportunities ---
def auto_link_suggestions():
    ensure_directories()
    print("\n--- Automatic Wikilink Opportunity Scan ---")
    
    titles_map = {}
    for f in WIKI_DIR.rglob("*.md"):
        if f.stem in ["index", "log"]:
            continue
        text = f.read_text(encoding="utf-8")
        t_match = re.search(r'^#\s+(.*)$', text, re.MULTILINE)
        title = t_match.group(1).strip() if t_match else f.stem
        titles_map[title.lower()] = f.stem
        titles_map[f.stem.lower()] = f.stem

    suggestions = 0
    wikilink_pattern = re.compile(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]')

    for f in WIKI_DIR.rglob("*.md"):
        rel_path = f.relative_to(BASE_DIR)
        text = f.read_text(encoding="utf-8")
        existing_links = {l.lower() for l in wikilink_pattern.findall(text)}
        
        for term, target_stem in titles_map.items():
            if len(term) < 4 or target_stem == f.stem or target_stem in existing_links:
                continue
            pattern = r'\b' + re.escape(term) + r'\b'
            if re.search(pattern, text, re.IGNORECASE) and f"[[{target_stem}]]" not in text:
                print(f"• In '{rel_path}': Mentioned '{term}' -> Suggest adding [[{target_stem}]]")
                suggestions += 1

    print(f"\nScan complete. Total link suggestions: {suggestions}\n")

# --- YouTube Ingest ---
def extract_youtube_id(url_or_id: str) -> str:
    if len(url_or_id) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id
    patterns = [
        r'(?:v=|\/)([a-zA-Z0-9_-]{11})(?:[&?\/]|$)',
        r'youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})'
    ]
    for p in patterns:
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    return url_or_id

def fetch_youtube_metadata(video_id: str) -> dict:
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {"title": f"YouTube Video {video_id}", "author_name": "Unknown Channel"}

def ingest_youtube(url_or_id: str):
    ensure_directories()
    video_id = extract_youtube_id(url_or_id)
    meta = fetch_youtube_metadata(video_id)
    title = meta.get("title", f"YouTube Video {video_id}")
    channel = meta.get("author_name", "Unknown Channel")
    
    transcript_text = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            paragraphs = []
            current_p = []
            for entry in transcript_list:
                text = entry['text'].replace('\n', ' ')
                current_p.append(text)
                if len(' '.join(current_p)) > 300:
                    paragraphs.append(' '.join(current_p))
                    current_p = []
            if current_p:
                paragraphs.append(' '.join(current_p))
            transcript_text = "\n\n".join(paragraphs)
        except Exception as te:
            transcript_text = f"*(Transcript fetch error: {te}. Transcript may be disabled for this video.)*"
    except ImportError:
        transcript_text = "*(youtube-transcript-api library not installed. Install via `pip install youtube-transcript-api` to fetch automated transcripts.)*"

    slug = slugify(title) or f"youtube-{video_id}"
    filename = f"{slug}.md"
    target_path = SOURCES_DIR / "youtube" / filename

    today = datetime.date.today().isoformat()
    content = f"""---
title: "{title}"
type: youtube_source
video_id: "{video_id}"
url: "https://www.youtube.com/watch?v={video_id}"
channel: "{channel}"
ingested: {today}
---

# {title}

**Channel:** {channel}  
**URL:** [https://www.youtube.com/watch?v={video_id}](https://www.youtube.com/watch?v={video_id})  
**Ingested:** {today}  

## Full Transcript / Content Notes

{transcript_text}
"""
    target_path.write_text(content, encoding="utf-8")
    print(f"Saved YouTube raw source to: {target_path}")
    append_to_log("ingest", f"YouTube source ingested: '{title}' ({target_path.name})")

# --- Web Ingest ---
def ingest_web(url: str):
    ensure_directories()
    print(f"Fetching web page: {url}...")
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error fetching URL {url}: {e}")
        return

    title = url
    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()
        title = re.sub(r'\s+', ' ', title)

    markdown_body = ""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0
        markdown_body = h.handle(html)
    except ImportError:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            markdown_body = soup.get_text(separator='\n\n')
        except ImportError:
            markdown_body = re.sub(r'<[^>]+>', '', html)

    slug = slugify(title) or "web-article"
    filename = f"{slug}.md"
    target_path = SOURCES_DIR / "web" / filename

    today = datetime.date.today().isoformat()
    content = f"""---
title: "{title}"
type: web_source
url: "{url}"
ingested: {today}
---

# {title}

**Source URL:** [{url}]({url})  
**Ingested:** {today}  

---

{markdown_body}
"""
    target_path.write_text(content, encoding="utf-8")
    print(f"Saved web raw source to: {target_path}")
    append_to_log("ingest", f"Web article ingested: '{title}' ({target_path.name})")

# --- PDF Ingest ---
def ingest_pdf(pdf_path_str: str):
    ensure_directories()
    pdf_path = Path(pdf_path_str).resolve()
    if not pdf_path.exists():
        print(f"Error: PDF file not found at {pdf_path}")
        return

    title = pdf_path.stem.replace('_', ' ').replace('-', ' ').title()
    text_content = []

    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        print(f"Extracting {len(reader.pages)} pages from {pdf_path.name}...")
        for idx, page in enumerate(reader.pages, 1):
            page_text = page.extract_text() or ""
            text_content.append(f"### Page {idx}\n\n{page_text}")
    except ImportError:
        text_content.append("*(pypdf library not installed. Install via `pip install pypdf` to extract text automatically.)*")

    full_text = "\n\n---\n\n".join(text_content)
    slug = slugify(pdf_path.stem)
    filename = f"{slug}.md"
    target_path = SOURCES_DIR / "pdfs" / filename

    today = datetime.date.today().isoformat()
    content = f"""---
title: "{title}"
type: pdf_source
original_file: "{pdf_path.name}"
ingested: {today}
---

# {title}

**Original File:** `{pdf_path.name}`  
**Ingested:** {today}  

---

## Extracted Text

{full_text}
"""
    target_path.write_text(content, encoding="utf-8")
    print(f"Saved PDF raw source to: {target_path}")
    append_to_log("ingest", f"PDF source ingested: '{title}' ({target_path.name})")

# --- Linting ---
def lint_wiki():
    ensure_directories()
    print("\n--- LLM Wiki & Zettelkasten Lint Check ---")
    issues_found = 0

    wiki_pages = {}
    for p in WIKI_DIR.rglob("*.md"):
        wiki_pages[p.stem] = p
        if p.parent == ATOMIC_DIR and '-' in p.stem:
            parts = p.stem.split('-', 1)
            wiki_pages[parts[1]] = p
    for p in BASE_DIR.glob("*.md"):
        wiki_pages[p.stem] = p
        wiki_pages[p.name] = p

    wikilink_pattern = re.compile(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]')
    for filepath in WIKI_DIR.rglob("*.md"):
        rel_path = filepath.relative_to(BASE_DIR)
        text = filepath.read_text(encoding="utf-8")
        matches = wikilink_pattern.findall(text)
        for target in matches:
            target_trim = target.strip()
            target_slug = slugify(target_trim)
            matched = any(
                s == target_trim or s == target_slug or slugify(s) == target_slug or s.lower() == target_trim.lower()
                for s in wiki_pages.keys()
            )
            if not matched:
                print(f"[BROKEN WIKILINK] In '{rel_path}': [[{target}]] target not found in wiki.")
                issues_found += 1

    if ATOMIC_DIR.exists():
        for zettel in ATOMIC_DIR.glob("*.md"):
            rel_zettel = zettel.relative_to(BASE_DIR)
            content = zettel.read_text(encoding="utf-8")
            
            if "uid:" not in content:
                print(f"[MISSING UID] Atomic zettel '{rel_zettel}' is missing 'uid:' in frontmatter.")
                issues_found += 1
            
            lines = content.splitlines()
            if len(lines) > 250:
                print(f"[BLOATED ZETTEL] Atomic zettel '{rel_zettel}' has {len(lines)} lines (> 250 limit). Consider splitting.")
                issues_found += 1
                
            z_stem = zettel.stem
            z_slug = z_stem.split('-', 1)[1] if '-' in z_stem else z_stem
            other_text = ""
            for other_fp in WIKI_DIR.rglob("*.md"):
                if other_fp != zettel:
                    other_text += other_fp.read_text(encoding="utf-8") + "\n"
            if z_stem not in other_text and z_slug not in other_text:
                print(f"[UNLINKED ZETTEL] Atomic zettel '{rel_zettel}' is not linked from any MOC, concept, or index page.")
                issues_found += 1

    sources_raw = list(SOURCES_DIR.rglob("*.md"))
    sources_wiki = list((WIKI_DIR / "sources").glob("*.md"))
    sources_wiki_stems = {s.stem for s in sources_wiki}
    
    for raw in sources_raw:
        if raw.parent.name == "assets":
            continue
        if raw.stem not in sources_wiki_stems:
            rel_raw = raw.relative_to(BASE_DIR)
            print(f"[UNINDEXED SOURCE] Raw source '{rel_raw}' has no corresponding summary in 'wiki/sources/'.")
            issues_found += 1

    if INDEX_FILE.exists():
        index_text = INDEX_FILE.read_text(encoding="utf-8")
        for filepath in WIKI_DIR.rglob("*.md"):
            if filepath.parent == ATOMIC_DIR or filepath.stem in ["index", "log"]:
                continue
            if filepath.stem not in index_text and slugify(filepath.stem) not in slugify(index_text):
                rel_path = filepath.relative_to(BASE_DIR)
                print(f"[ORPHAN PAGE] Page '{rel_path}' is not referenced in wiki/index.md")
                issues_found += 1

    print(f"\nLint complete. Total issues found: {issues_found}\n")

# --- Main CLI ---
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "new-zettel":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py new-zettel \"Concept Title\"")
            sys.exit(1)
        new_zettel(sys.argv[2])
    elif cmd == "query":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py query \"<question>\"")
            sys.exit(1)
        query_wiki_llm(sys.argv[2])
    elif cmd == "ai-summarize":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py ai-summarize <source_file_path>")
            sys.exit(1)
        ai_summarize_source(sys.argv[2])
    elif cmd == "ai-lint":
        ai_lint_wiki()
    elif cmd == "ingest-youtube":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py ingest-youtube <URL or VideoID>")
            sys.exit(1)
        ingest_youtube(sys.argv[2])
    elif cmd == "ingest-web":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py ingest-web <URL>")
            sys.exit(1)
        ingest_web(sys.argv[2])
    elif cmd == "ingest-pdf":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py ingest-pdf <PDF_PATH>")
            sys.exit(1)
        ingest_pdf(sys.argv[2])
    elif cmd == "ingest-arxiv":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py ingest-arxiv <ID or URL>")
            sys.exit(1)
        ingest_arxiv(sys.argv[2])
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/wiki.py search \"<query>\"")
            sys.exit(1)
        search_wiki(sys.argv[2])
    elif cmd == "stats":
        graph_stats()
    elif cmd == "auto-link":
        auto_link_suggestions()
    elif cmd == "lint":
        lint_wiki()
    elif cmd == "log":
        if len(sys.argv) < 4:
            print("Usage: python3 tools/wiki.py log <ACTION> <SUMMARY>")
            sys.exit(1)
        append_to_log(sys.argv[2], sys.argv[3])
    else:
        print(f"Unknown command '{cmd}'. Available commands: new-zettel, query, ai-summarize, ai-lint, ingest-youtube, ingest-web, ingest-pdf, ingest-arxiv, search, stats, auto-link, lint, log")
        sys.exit(1)

if __name__ == "__main__":
    main()
