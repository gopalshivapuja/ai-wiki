---
uid: '20260810091700'
title: Building Effective Agents
class: source
type: web
created: '2026-08-10'
updated: '2026-08-10'
url: https://www.anthropic.com/research/building-effective-agents
---

# Building Effective Agents

**Source URL:** [https://www.anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)  
**Author:** Anthropic Engineering  
**Ingested:** 2026-08-10  

---

## Executive Summary

Over the past year, Anthropic has worked with developers building agents across industries. The most successful implementations aren't using complex frameworks or specialized libraries. Instead, they're building with simple, composable patterns.

Key insights include:
- **Workflows vs. Agents**: Workflows orchestrate LLMs and tools through predefined code paths. Agents operate dynamically, choosing their own path and tool usage to accomplish open-ended goals.
- **When to use agents**: Use workflows for predictability and low latency; use agents when task complexity requires dynamic decision-making and iterative problem solving.
- **Core Design Patterns**:
  1. Prompt Chaining (sequential tasks)
  2. Routing (classifying inputs to specific handlers)
  3. Parallelization (sectioning tasks across multiple LLM calls)
  4. Orchestrator-Workers (central LLM delegating sub-tasks)
  5. Evaluator-Optimizer Loop (iterative feedback and refinement)
