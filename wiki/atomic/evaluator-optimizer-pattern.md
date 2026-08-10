---
uid: "20260810100400"
title: "Evaluator-Optimizer Pattern"
type: zettel
created: 2026-08-10
updated: 2026-08-10
tags: [zettel, atomic, agent-patterns, critique, reflection, refinement]
aliases:
  - "20260810100400-evaluator-optimizer-pattern"
sources:
  - "sources/web/building-effective-agents-anthropic.md"
---

# Evaluator-Optimizer Pattern

**UID:** `20260810100400`  
**Created:** 2026-08-10  

---

## Core Principle

The **Evaluator-Optimizer Pattern** is a two-role LLM workflow where one model (the *Optimizer/Generator*) produces a candidate output, and a separate model pass (the *Evaluator/Critic*) critiques the output against concrete criteria to drive iterative refinement.

### Workflow Sequence
```
[Generator] Candidate Output ---> [Evaluator] Pass / Fail + Feedback
      ^                                  | (If Fail)
      └──────────────────────────────────┘
```

### Primary Applications
- **Code Generation & Verification**: Generating code, running unit tests, and passing test failure logs back to fix bugs.
- **Translation & Writing**: Reviewing tone, accuracy, and style constraints.
- **Complex Reasoning**: Verifying mathematical step-by-step proofs before final presentation.

---

## Related Knowledge & Links

- [[react-agent-loop|ReAct Agent Loop]] — Dynamic environment interaction loop.
- [[ai-agents-and-tools]] — Overview of workflow patterns.
- [[building-effective-agents-anthropic]] — Source document introducing Evaluator-Optimizer feedback design.
- [[moc-agentic-patterns]] — Map of Content for agent workflows.
