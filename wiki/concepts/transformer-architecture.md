---
title: "Transformer Architecture"
type: concept
created: 2026-08-10
updated: 2026-08-10
tags: [concept, architecture, deep-learning, attention, transformer]
sources:
  - "sources/pdfs/attention-is-all-you-need-paper.md"
---

# Transformer Architecture

The **Transformer** is the foundational deep learning neural network architecture powering virtually all modern Large Language Models (LLMs), vision transformers, and multimodal models. Introduced in 2017 by Vaswani et al. in [[attention-is-all-you-need-paper|Attention Is All You Need]], it replaced recurrent neural networks (RNNs) by relying entirely on self-attention mechanisms.

---

## 1. Core Components

### Scaled Dot-Product Attention
Attention allows tokens in a sequence to compute pairwise similarity scores against all other tokens:

$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$

Where:
- $Q$ (Query): What the current token is looking for.
- $K$ (Key): What features each token possesses.
- $V$ (Value): The actual information payload transferred.
- $\sqrt{d_k}$: Scaling factor to stabilize softmax gradients.

### Multi-Head Attention (MHA)
Instead of performing a single attention function, Queries, Keys, and Values are linearly projected $h$ times into lower-dimensional subspaces, allowing the network to attend to multiple semantic aspects (e.g., syntax, coreference, sentiment) simultaneously.

### Positional Encodings
Because transformers contain no sequence recurrence or convolution, order information is injected by adding sinusoidal or learned positional encodings to token embeddings (and modern variants like RoPE — Rotary Position Embedding).

---

## 2. Encoder-Decoder Variants

1. **Decoder-Only (Autoregressive)**: Used by GPT-4 ([[openai]]), Claude ([[anthropic]]), and LLaMA ([[meta-ai]]). Uses causal masking to predict the next token.
2. **Encoder-Only**: Used by BERT and RoBERTa for embedding generation, classification, and retrieval in [[retrieval-augmented-generation]].
3. **Encoder-Decoder**: Original architecture (T5, Whisper) suitable for sequence-to-sequence translation and summarization.

---

## Related Knowledge
- [[retrieval-augmented-generation]]
- [[fine-tuning-and-alignment]]
- [[attention-is-all-you-need-paper]]
- [[openai]]
- [[meta-ai]]
