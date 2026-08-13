# Using the wiki from Claude (MCP)

The wiki ships an **MCP server** so a language model can search it, read notes, and follow
links — turning a private knowledge base into something Claude Code or Claude Desktop can
reason over directly.

It runs **on your machine** and talks to the deployed wiki over HTTP. There is no second copy
of your data, nothing is indexed anywhere else, and the hosted app is unchanged.

It is **read-only** by design. Letting an agent rewrite notes unsupervised is a much larger
decision than letting it read them, and this does not make it for you.

---

## 1. Install

```bash
cd /path/to/ai-wiki
pip install -e '.[mcp]'
```

The `[mcp]` extra installs the MCP SDK. It is an extra rather than a runtime dependency so the
container that serves the wiki never imports it.

## 2. Get a token

Every route is authenticated — the wiki is private.

```bash
curl -s -X POST https://your-app.up.railway.app/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"your-password"}' | python3 -m json.tool
```

Copy `access_token`. Tokens expire; if tools start returning `401`, get a new one.

## 3. Connect

### Claude Code

```bash
claude mcp add ai-wiki \
  --env WIKI_URL=https://your-app.up.railway.app \
  --env WIKI_TOKEN=paste-your-token-here \
  -- python -m wiki_mcp.server
```

Check it took:

```bash
claude mcp list
```

### Claude Desktop

Add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ai-wiki": {
      "command": "python",
      "args": ["-m", "wiki_mcp.server"],
      "env": {
        "WIKI_URL": "https://your-app.up.railway.app",
        "WIKI_TOKEN": "paste-your-token-here",
        "PYTHONPATH": "/path/to/ai-wiki/packages"
      }
    }
  }
}
```

Use the absolute path to a Python that has the `[mcp]` extra installed — a virtualenv's
`bin/python` is usually the right answer. Restart Claude Desktop afterwards.

---

## The tools

| Tool | Use it for |
|---|---|
| `wiki_overview` | What the wiki contains and how to traverse it. Call first when you don't know. |
| `list_maps` | The maps of content — curated entry points. |
| `search_wiki` | Full-text search across notes and sources. |
| `read_note` | One document's markdown, plus its links and backlinks. |
| `related_notes` | The neighbourhood around a document, 1–3 hops. |
| `ask_wiki` | An answer synthesised from the wiki, with citations. |

### How they fit together

The intended path mirrors how the wiki is built:

```
wiki_overview  →  list_maps  →  read_note(a map)  →  read_note(a concept)  →  related_notes
     what is here      where to start     the vocabulary        the idea         what surrounds it
```

`search_wiki` short-circuits that when you already know the words. `read_note` returns
`links` and `backlinks` alongside the body specifically so the next hop needs no extra search.

### Examples

**Find out what's here**

> Use wiki_overview and tell me what this wiki covers.

**Answer from your own notes**

> Search my wiki for what it says about prompt caching, then read the most relevant note.

**Follow the graph**

> Read the note on `transformer`, then use related_notes to show me what surrounds it, and
> summarise how those ideas connect.

**Use it as grounding for real work**

> Using only my wiki, draft a study plan for the CCAR-P exam. Start from
> `moc-claude-certification`, follow its links, and tell me which domains have thin coverage.

### What the output looks like

`read_note` returns:

```json
{
  "slug": "vanishing-gradient",
  "title": "Vanishing Gradient",
  "type": "zettel",
  "unreviewed": false,
  "body": "# Vanishing Gradient\n\nGradients shrink exponentially…",
  "links": [{ "slug": "relu-activation", "title": "ReLU Activation" }],
  "backlinks": [{ "slug": "moc-ai-masterclass", "title": "AI Master Class" }]
}
```

`unreviewed` is worth heeding: it marks a note written by a model and not yet checked by a
human.

---

## `llms.txt`

For anything that is not MCP — a RAG pipeline, a script, another agent framework — the same
map is available as plain text:

```bash
curl -H "Authorization: Bearer $WIKI_TOKEN" https://your-app.up.railway.app/api/llms.txt
```

It follows the [llms.txt](https://llmstxt.org) convention: what the wiki is, its counts, its
maps of content as entry points, the note types, and the traversal order. It requires the same
authentication as everything else — describing a private wiki's contents is still describing
its contents.

Useful companions for building your own retrieval:

| Endpoint | Returns |
|---|---|
| `GET /api/search?q=…` | Ranked full-text results with highlighted snippets |
| `GET /api/documents/{slug}` | Body, outgoing links (flagged if they resolve), backlinks |
| `GET /api/graph/{slug}?hops=1` | The neighbourhood around a document |
| `GET /api/related/{slug}` | Notes near it in meaning, computed from embeddings |
| `GET /api/export` | The whole wiki as a zip of markdown with frontmatter |

---

## Troubleshooting

**`Error: The wiki rejected the token (401)`** — the token expired or is wrong. Get a new one
(step 2) and update the env var. In Claude Code, `claude mcp remove ai-wiki` then re-add.

**`Error: Could not reach the wiki at …`** — check `WIKI_URL` has no trailing slash and no
`/api` suffix. The server appends `/api` itself.

**`ModuleNotFoundError: No module named 'mcp'`** — the `[mcp]` extra is not installed in the
Python being used. Run `pip install -e '.[mcp]'` with that interpreter, or point `command` at
the virtualenv's `bin/python`.

**Tools do not appear** — Claude Desktop needs a restart after a config change. For Claude
Code, `claude mcp list` shows whether the server is registered and reachable.

**`ModuleNotFoundError: No module named 'wiki_mcp'`** — set `PYTHONPATH` to the repo's
`packages/` directory, or install the project itself (`pip install -e .`).

---

## Why read-only

Every tool is a read. There is no `create_note`, no `edit_note`, no `delete_note`.

An agent with write access to a knowledge base can quietly degrade it — rewording a note it
misread, "fixing" a link that was deliberate, or filling the graph with plausible connections
nobody checked. Those failures are hard to notice and hard to reverse, and this wiki's value
is that its contents were curated.

If you do want an agent to add material, the honest path is the existing job queue: it
records what was added, snapshots a revision before every change, and tags machine-written
notes `unreviewed` so they can be reviewed as a batch.
