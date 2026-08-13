---
title: "Transformer Architecture"
class: note
type: zettel
tags: ["zettel", "architecture"]
---

# Transformer Architecture

An architecture of stacked self-attention and feed-forward blocks. Its decisive property is
parallelism: every position is computed at once, so training scales with hardware rather than
with sequence length.

## Related

- [[attention-mechanism]] — the operation it is built from.
