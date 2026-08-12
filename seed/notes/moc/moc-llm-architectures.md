---
uid: '20260810091300'
title: 'Map of Content: LLM Architectures & Mechanics'
class: note
type: moc
created: '2026-08-10'
updated: '2026-08-10'
tags:
- moc
- map-of-content
- architecture
- zettelkasten
- transformer
---

# Map of Content: LLM Architectures & Mechanics

This **Map of Content (MOC)** aggregates all atomic Zettel notes, foundational concept overviews, and landmark papers related to neural network architectures, attention mechanisms, and model adaptations.

---

## 1. Core Attention Mechanisms (Atomic Zettels)
- [[scaled-dot-product-attention|Scaled Dot-Product Attention]] — Q/K/V pairwise similarity computation and $\frac{1}{\sqrt{d_k}}$ scaling factor.
- [[multi-head-attention|Multi-Head Attention]] — Parallel linear projections across distinct representation subspaces.

## 2. High-Level Concept Overviews
- [[transformer-architecture]] — Encoder-decoder, decoder-only, and positional encoding paradigms.
- [[fine-tuning-and-alignment]] — SFT, LoRA/QLoRA PEFT adaptation, RLHF, and DPO alignment.

## 3. Parameter-Efficient Adaptation (Atomic Zettels)
- [[lora-low-rank-adaptation|LoRA Low-Rank Adaptation]] — Low-Rank matrix decomposition ($W_0 + BA$) for memory-efficient tuning.

## 4. Key Entities & Landmark Papers
- [[Attention Is All You Need|Attention Is All You Need]] — Landmark 2017 paper by Vaswani et al. introducing Transformers.
- [[openai]] — Pioneer of decoder-only GPT architecture.
- [[meta-ai]] — Creators of LLaMA open-weights family & PyTorch.
- [[hugging-face]] — Ecosystem host for `transformers` and `peft` libraries.

---

## Architectural Dependency Graph
```mermaid
flowchart TD
    Paper["[[Attention Is All You Need|Attention Is All You Need]]"] --> ScaledAttn["[[scaled-dot-product-attention|Scaled Dot-Product Attention]]"]
    ScaledAttn --> MultiHeadAttn["[[multi-head-attention|Multi-Head Attention]]"]
    MultiHeadAttn --> Transformer["[[transformer-architecture]]"]
    Transformer --> LoRA["[[lora-low-rank-adaptation|LoRA Low-Rank Adaptation]]"]
    LoRA --> PEFT["[[fine-tuning-and-alignment]]"]
```
