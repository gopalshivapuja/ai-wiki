---
uid: "20260810100100"
title: "Scaled Dot-Product Attention"
type: zettel
created: 2026-08-10
updated: 2026-08-10
tags: [zettel, atomic, attention, math, transformer]
aliases:
  - "20260810100100-scaled-dot-product-attention"
sources:
  - "sources/pdfs/attention-is-all-you-need-paper.md"
---

# Scaled Dot-Product Attention

**UID:** `20260810100100`  
**Created:** 2026-08-10  

---

## Core Principle

**Scaled Dot-Product Attention** is the core mathematical operator of the [[transformer-architecture|Transformer Architecture]] that computes pairwise similarity weights between input token representations.

### Equation
$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$

### Key Mechanics
1. **Matrix Multiplication ($QK^T$)**: Computes raw dot-product similarity between Query matrix $Q$ and Key matrix $K$.
2. **Scaling Factor ($\frac{1}{\sqrt{d_k}}$)**: Prevents the dot product from growing excessively large in high dimensions ($d_k$), avoiding vanishing gradients in the softmax function.
3. **Softmax Normalization**: Converts raw scores into a valid probability distribution across tokens.
4. **Value Projection ($V$)**: Multiplies normalized attention weights by Value matrix $V$ to yield contextual token representations.

---

## Related Knowledge & Links

- [[multi-head-attention|Multi-Head Attention]] — Parallelizes scaled dot-product attention across multiple linear projections.
- [[transformer-architecture]] — Incorporates attention within encoder and decoder layers.
- [[moc-llm-architectures]] — Map of Content for transformer components.
