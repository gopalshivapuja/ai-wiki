---
uid: '20260810090100'
title: AI Agents and Tools
class: note
type: concept
created: '2026-08-10'
updated: '2026-08-10'
tags:
- concept
- ai-agents
- tool-use
- react-loop
- multi-agent
- autonomy
---

# AI Agents and Tools

**AI Agents** are systems where a Large Language Model ([[transformer-architecture]]) autonomously navigates complex multi-step tasks by reasoning, executing tool calls (APIs, code execution, web search, database queries), observing results, and dynamically adjusting its strategy until completion.

---

## 1. Core Agent Frameworks & Patterns

As documented in [[Building Effective Agents|Building Effective Agents]], agentic systems generally fall into two broad categories:

### A. Agentic Workflows (Deterministic)
- **Prompt Chaining**: Breakdown of tasks into fixed step-by-step LLM calls.
- **Routing**: Classifying inputs to delegate to specialized sub-prompts.
- **Parallelization**: Running parallel LLM calls (e.g. section-by-section analysis) and aggregating results.

### B. Autonomous Agents (Dynamic Loops)
- **ReAct Loop (Reason + Act)**: The model outputs a thought, chooses a tool action, receives observation data, and iterates.
- **Orchestrator-Workers**: A lead coordinator agent delegates sub-tasks to specialized sub-agents.
- **Evaluator-Optimizer**: A generator model creates outputs which a critic model reviews and refines iteratively.

---

## 2. Key Components of an Agent

1. **Model Backbone**: High-reasoning LLMs like Claude 3.5 Sonnet ([[anthropic]]), GPT-4o ([[openai]]), or open-weights LLaMA 3 ([[meta-ai]]).
2. **Tool Registry**: Functions exposed via JSON schema schemas (e.g., `web_search`, `execute_python`, `view_file`, `ingest_youtube`).
3. **Memory & Context**:
   - *Short-Term Memory*: In-context conversation history & tool responses.
   - *Long-Term Memory*: Knowledge bases like this [[retrieval-augmented-generation|LLM Wiki]].
4. **Environment & Safety Controls**: User approvals, sandbox execution, rate limits, data loss prevention.

---

## Related Knowledge
- [[Building Effective Agents|Building Effective Agents]]
- [[retrieval-augmented-generation]]
- [[state-of-ai-engineering]]
- [[anthropic]]
- [[openai]]
