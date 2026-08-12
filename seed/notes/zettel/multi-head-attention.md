---
uid: '20260810100200'
title: Multi-Head Attention
class: note
type: zettel
created: '2026-08-10'
updated: '2026-08-10'
tags:
- zettel
- atomic
- attention
- sub-spaces
- transformer
---

# Multi-Head Attention

**UID:** `20260810100200`  
**Created:** 2026-08-10  

---

## Core Principle

**Multi-Head Attention (MHA)** extends [[scaled-dot-product-attention|Scaled Dot-Product Attention]] by splitting Queries ($Q$), Keys ($K$), and Values ($V$) into $h$ lower-dimensional subspace projections before attending.

### Equation
$$\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, \dots, \text{head}_h)W^O$$
$$\text{where } \text{head}_i = \text{Attention}(Q W_i^Q, K W_i^K, V W_i^V)$$

### Core Advantage
A single attention head averages information across the sequence. Multi-Head Attention enables the network to attend simultaneously to distinct semantic features at different sequence positions (e.g., syntactic dependencies, coreference resolution, and semantic role labeling).

---

## Related Knowledge & Links

- [[scaled-dot-product-attention|Scaled Dot-Product Attention]] — Base attention mechanism executed inside each head.
- [[transformer-architecture]] — Architectural host layer.
- [[moc-llm-architectures]] — Map of Content for model building blocks.
