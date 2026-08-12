---
uid: '20260810091000'
title: 'Source Summary: Attention Is All You Need'
class: note
type: literature
created: '2026-08-10'
updated: '2026-08-10'
tags:
- source-summary
- paper
- transformer
- attention
- deep-learning
---

# Source Summary: Attention Is All You Need

**Original Source:** [[Attention Is All You Need|Attention Is All You Need PDF]]  
**Authors:** Vaswani et al. (Google Brain / Research)  
**Key Topics:** [[transformer-architecture]], Multi-Head Attention, Scaled Dot-Product Attention, Positional Encoding  

---

## Key Takeaways

1. **Elimination of Recurrence**: Dispensed with RNNs/LSTMs in favor of pure self-attention mechanisms, enabling massive parallelization during GPU training.
2. **Scaled Dot-Product Attention**:
   $$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$
   The scaling factor $\frac{1}{\sqrt{d_k}}$ prevents vanishing gradients in softmax for large vector dimensions.
3. **Multi-Head Attention**: Splitting queries, keys, and values into $h$ subspaces allows the model to attend simultaneously to different positions and semantic relationships.
4. **Foundation of Modern LLMs**: Laid the groundwork for modern generative AI models including GPT-4 ([[openai]]), Claude ([[anthropic]]), LLaMA ([[meta-ai]]), and BERT.

---

## Linked Concepts & Entities
- [[transformer-architecture]] — the concept note this paper established.
- [[openai]] — took this architecture and scaled it.
- [[meta-ai]] — released open-weights implementations of it.
- [[ai-learning-roadmap]] — where this paper sits in the study order.
- [[scaled-dot-product-attention]] — the paper's core operation, as its own note.
- [[multi-head-attention]] — the paper's parallel-subspace refinement, as its own note.
