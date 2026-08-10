# 08 — Cursor Workflow Tips for Building This Wiki

Your knowledge base is maintained by an AI agent, which means the tool you drive that agent with is
part of the architecture. This is a practical guide to the Cursor features that map onto this specific
project. Keyboard shortcuts are given as `Cmd`/`Ctrl` pairs; they can shift between versions, so treat
them as hints rather than gospel.

---

## 1. `AGENTS.md` is already your best Cursor feature

You have accidentally done the single highest-leverage thing: written a schema document that any agent
reads before touching the repo. Cursor picks up `AGENTS.md` at the repo root automatically.

Two ways to make it work harder:

**Keep it honest.** An `AGENTS.md` that documents commands which no longer exist is worse than no
`AGENTS.md`, because the agent will confidently run the wrong thing. That is why FR-OPS-13 puts a CI
check on it — the schema and the CLI must agree, verified by a machine, not by hope.

**Split rules by scope with `.cursor/rules/`.** `AGENTS.md` applies everywhere, which means every token
of it is spent on every request. Path-scoped rules are cheaper and sharper:

```
.cursor/rules/
├── wiki-content.mdc     # globs: wiki/**/*.md      → link conventions, frontmatter schema
├── python-code.mdc      # globs: src/**/*.py       → typing, no bare except, test expectations
└── never-touch.mdc      # globs: sources/**        → immutable, read-only, do not edit
```

Each `.mdc` file carries frontmatter with `description`, `globs`, and `alwaysApply`. Rules whose globs
match the files in play get attached automatically. A `sources/` rule saying "these files are immutable
ground truth" is the kind of guardrail that turns an invariant into something an agent respects
reliably.

---

## 2. Match the mode to the job

Cursor has distinct modes and using the wrong one is the most common source of "the agent did something
I didn't want".

| Mode | Use it for | On this project |
| --- | --- | --- |
| **Plan** | Read-only exploration and design. Cannot edit files. | Exactly what you asked for in your message: "plan this out first". Plan mode enforces that with permissions rather than politeness. |
| **Agent** | Implementation with full tool access. | P0 onward, once a plan is agreed. |
| **Ask** | Questions about the codebase, no edits. | "How does link resolution work?" without risking a refactor. |
| **Debug** | Hypothesis-driven investigation with instrumentation. | When search returns nothing for a query you know should match. |

**The tip that matters:** when you want a plan, say so *and* use Plan mode. Asking an eager agent in
Agent mode to "just plan it" is like asking a Labrador to just *look* at the ball. Plan mode removes the
temptation structurally.

---

## 3. `@` references beat describing things

Every minute the agent spends searching for context is a minute of guessing. Point at things instead.

| Reference | What it pulls in | Use on this project |
| --- | --- | --- |
| `@filename` | One file | `@tools/wiki.py` when discussing the CLI |
| `@folder/` | A directory | `@wiki/atomic/` when discussing zettel conventions |
| `@Web` | Live web search | Checking which OpenRouter model slugs actually exist (see F-20) |
| `@Docs` | Indexed documentation for a library | FastAPI, HTMX, Typer, and Railway docs during P5–P7 |
| `@Git` / recent changes | Diffs and history | "Review my migration commit against the plan" |
| `@Definitions` | Symbol definitions | Tracing `slugify` usage during the P2 refactor |
| `@Past Chats` | Earlier conversations | Recovering a decision from a previous session |
| `@Terminal` | Recent terminal output | Pasting a failing test run without copy-paste |

`@Docs` is underused and perfect for this build. You can add a documentation URL once and then reference
it by name forever, which beats the agent inventing a plausible-looking FastAPI API from memory.

---

## 4. Cloud agents for the long, boring, parallel work

This plan has several phases that are large, mechanical, and independent — exactly what cloud agents are
for. They run on their own VM, on their own branch, and open a pull request.

Good candidates from `docs/04-implementation-roadmap.md`:

- **P1 migration** — mechanical, verifiable by a linter, perfect for review-as-a-PR.
- **P3 search index** — self-contained behind an interface.
- **P4 ingest hardening** — four independent ingest paths that can each be fixed and tested in isolation.

You can run several at once on separate branches. Two habits make this pleasant rather than chaotic:

1. **One phase per agent.** Overlapping file sets produce merge conflicts that cost more than the
   parallelism saved.
2. **Give each one its exit criterion verbatim.** "Done" is ambiguous; "`wiki lint --strict` exits 0 and
   the audit script reports 0 findings" is not.

Cloud agents also have a nice property for a knowledge base: **the agent can ingest sources while you do
something else.** Point one at a reading list, let it ingest and draft literature notes, then review the
pull request like a diff. That is the Karpathy loop with the grunt work moved off your machine.

---

## 5. Bugbot on the pull requests that matter

Ask for a Bugbot review on the pull requests where a subtle mistake is expensive:

- The **P1 migration** — 27 punctuation edits across 8 files is exactly where a stray character hides.
- The **P6 auth** work — session flags, CSRF, and rate limiting are easy to get subtly wrong.
- The **P4 SSRF guard** — blocklists have edge cases (IPv6-mapped IPv4, redirects, DNS rebinding) that
  reward a second reader.

It is not a substitute for the tests in this plan. It is a second reader who never gets bored on file 6
of 8, which is more than most humans can honestly claim.

---

## 6. Terminal `Cmd/Ctrl+K` for the commands you always half-remember

In Cursor's terminal, `Cmd/Ctrl+K` turns a description into a command. Useful during P7 when the exact
Railway invocation is on the tip of your tongue:

> "poll railway deployment status as json until it's not building"

This is also a safe way to learn a CLI: you see the command before it runs, so you learn the flags
instead of just getting the outcome.

---

## 7. Custom commands for the loops you repeat

Cursor supports custom slash commands as markdown files in `.cursor/commands/`. This project has obvious
candidates:

```
.cursor/commands/
├── ingest.md      # "Ingest <url>: run wiki ingest, review the literature note, propose MOC updates,
│                  #  update the index, append to log — then show me the diff before writing"
├── audit.md       # "Run wiki lint --strict and ai-lint, summarise findings by severity, propose fixes"
└── zettel.md      # "Extract atomic zettels from <source>: one idea each, link from a MOC with rationale"
```

Then `/ingest https://…` runs your whole documented workflow instead of you re-explaining it every time.
This is the same instinct as writing `AGENTS.md`, applied to repeated *actions* rather than standing
rules — and it is the natural home for the operations currently described in prose in `AGENTS.md` §4.

---

## 8. Checkpoints make ambitious refactors safe

Cursor checkpoints the workspace as the agent works, so you can restore to a previous state if a
refactor goes sideways. This matters most in P2, the big-bang library extraction — the phase where
"actually, let's back up three steps" is a realistic thing to want.

Belt and braces: work on a branch and commit at each green test run. Checkpoints are for the last ten
minutes; git is for the last ten days.

---

## 9. Keep the index clean with `.cursorignore`

Cursor indexes your codebase for semantic search. Two files control it: `.cursorignore` (excluded from
indexing *and* from agent access) and `.cursorindexingignore` (excluded from indexing only).

For this project, `sources/` is the interesting case. Raw sources are large, verbose, and mostly noise
for code questions — but they are genuinely useful when the agent is writing literature notes. The
pragmatic answer: leave them indexed for now, and if index quality degrades as the corpus grows, add
`sources/**` to `.cursorindexingignore` and let the wiki's own search handle content retrieval. That is
arguably the correct division of labour anyway: Cursor's index for *code*, your FTS5 index for
*knowledge*.

Definitely keep `.env` out. It is already git-ignored, which is the important half.

---

## 10. MCP: let the agent use your wiki as a native tool

FR-CLI-10 proposes an MCP server exposing `search`, `read`, `create`, `link`, and `lint`. This is the
payoff for building a clean core library in P2.

Right now, an agent working on your wiki has to shell out to a CLI and parse text. With an MCP server
configured in `.cursor/mcp.json`, `search_wiki` becomes a first-class tool the agent calls directly with
structured arguments and structured results. Concretely: instead of the agent guessing which notes
relate to a new source, it *queries your knowledge graph* and gets back slugs, types, and existing links.

That is the moment the wiki stops being a folder the agent edits and starts being a memory the agent
consults — which is the whole point of the LLM wiki pattern.

---

## 11. Model choice, briefly

A rough heuristic that holds up on a project like this:

- **Mechanical, well-specified work** (the P1 migration, adding lint rules from a written list) — a fast
  model is fine and the tests are your safety net.
- **Design and refactoring** (P2's module boundaries, the search ranking, the auth flow) — use a
  stronger reasoning model. These are the decisions you inherit for the life of the project.
- **Anything security-shaped** (auth, sanitisation, SSRF) — strongest model, plus Bugbot, plus tests.
  The cost difference is pennies; the cost of getting it wrong is your wiki being public.

---

## 12. The workflow this plan is designed for

```
1. Read something interesting.
2. `wiki ingest <url>` — or /ingest in Cursor, which does the whole documented loop.
3. Review the agent's literature note and proposed atomic zettels as a diff. You are the curator.
4. `wiki lint --strict` — the schema keeps itself honest.
5. Commit, push. CI checks your *content* like code. Railway deploys.
6. Search and read from any device, behind a login, with a graph that shows how it all connects.
7. Weekly: read the nightly health report and write the notes it says are missing.
```

Steps 3 and 7 are the only ones that need your brain. Everything else in this plan exists to make sure
they are the only ones that need your brain — which is precisely the argument `llm-wiki.md` makes about
why humans abandon wikis and LLMs do not.
