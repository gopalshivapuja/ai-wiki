---
title: "Attention Mechanism"
class: note
type: zettel
tags: ["zettel", "attention"]
---

# Attention Mechanism

Attention lets a model weight every position in a sequence by relevance rather than relying on
a single compressed summary vector. Each position emits a query, every position offers a key
and a value, and the similarity between query and key becomes the weight.

## Related

- [[transformer-architecture]] — the architecture built on attention.

## Where this came from

- [[src-attention-is-all-you-need|Attention Is All You Need]] — the source this was distilled from.
