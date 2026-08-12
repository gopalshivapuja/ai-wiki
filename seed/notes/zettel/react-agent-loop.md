---
uid: '20260810100300'
title: ReAct Agent Loop
class: note
type: zettel
created: '2026-08-10'
updated: '2026-08-10'
tags:
- zettel
- atomic
- react
- ai-agents
- reasoning
- tool-use
---

# ReAct Agent Loop

**UID:** `20260810100300`  
**Created:** 2026-08-10  

---

## Core Principle

The **ReAct (Reason + Act)** pattern is an iterative execution loop where an LLM alternates between explicit verbal reasoning (**Thought**), tool invocation (**Action**), and environment feedback retrieval (**Observation**).

### Execution Flow
```
User Prompt -> [ Thought -> Action -> Observation ] (Loop) -> Final Answer
```

1. **Thought**: The model generates a natural language step explaining its reasoning and next intent.
2. **Action**: The model outputs a formatted tool call (JSON/XML).
3. **Observation**: The system executes the tool and feeds the result back into the prompt context.

This interleaved loop allows the agent to recover from intermediate errors, refine search terms dynamically, and handle complex open-ended tasks.

---

## Related Knowledge & Links

- [[evaluator-optimizer-pattern|Evaluator-Optimizer Pattern]] — Secondary agent pattern focusing on quality refinement loops.
- [[ai-agents-and-tools]] — Comprehensive overview of agentic patterns.
- [[Building Effective Agents|Building Effective Agents]] — Engineering best practices for ReAct implementation.
- [[moc-agentic-patterns]] — Map of Content for agent architectures.
