---
uid: '20260810091200'
title: 'Map of Content: Agentic Systems & Workflows'
class: note
type: moc
created: '2026-08-10'
updated: '2026-08-10'
tags:
- moc
- map-of-content
- ai-agents
- react
- workflows
- zettelkasten
---

# Map of Content: Agentic Systems & Workflows

This **Map of Content (MOC)** aggregates all atomic Zettel notes, system concept pages, and engineering guides related to autonomous AI agents, tool integration, and control loop patterns.

---

## 1. Core Agentic Patterns (Atomic Zettels)
- [[react-agent-loop|ReAct Agent Loop]] — Interleaved Thought-Action-Observation environment control loop.
- [[evaluator-optimizer-pattern|Evaluator-Optimizer Pattern]] — Generator-Critic feedback loop for iterative output critique and refinement.

## 2. High-Level Concept Overviews
- [[ai-agents-and-tools]] — ReAct loops, tool registries, short-term vs long-term memory, multi-agent coordination.
- [[retrieval-augmented-generation]] — Knowledge retrieval paradigms (vector RAG versus a persistent curated wiki).

## 3. Structural Overviews & Guides
- [[building-effective-agents-anthropic|Building Effective Agents]] — Anthropic's authoritative guide on composable agent workflows vs autonomous loops.
- [[state-of-ai-engineering]] — Comparative analysis of agent frameworks and frontier model capabilities.

## 4. Key Entities
- [[anthropic]] — Creator of Claude 3.5 Sonnet & Model Context Protocol (MCP).
- [[openai]] — Creator of GPT-4o & Function Calling standards.

---

## Agent Architecture Map
```mermaid
flowchart LR
    Guide["Building Effective Agents"] --> Overview["Ai Agents And Tools"]
    Overview --> ReAct["React Agent Loop"]
    Overview --> EvalOpt["Evaluator Optimizer Pattern"]
    ReAct --> WikiStore["Retrieval-Augmented Generation / curated wiki"]
```
