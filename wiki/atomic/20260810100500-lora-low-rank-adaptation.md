---
uid: "20260810100500"
title: "LoRA (Low-Rank Adaptation)"
type: zettel
created: 2026-08-10
updated: 2026-08-10
tags: [zettel, atomic, fine-tuning, peft, lora, vram-efficiency]
sources:
  - "sources/pdfs/attention-is-all-you-need-paper.md"
---

# LoRA (Low-Rank Adaptation)

**UID:** `20260810100500`  
**Created:** 2026-08-10  

---

## Core Principle

**LoRA (Low-Rank Adaptation)** is a Parameter-Efficient Fine-Tuning (PEFT) method that freezes pre-trained neural network weights ($W_0 \in \mathbb{R}^{d \times k}$) and injects trainable rank decomposition matrices ($B \in \mathbb{R}^{d \times r}$ and $A \in \mathbb{R}^{r \times k}$) where rank $r \ll \min(d, k)$.

### Mathematical Formulation
$$W = W_0 + \Delta W = W_0 + \frac{\alpha}{r} (B \cdot A)$$

- **$W_0$**: Frozen pre-trained base model weight matrix.
- **$A \sim \mathcal{N}(0, \sigma^2)$, $B = 0$**: Matrix $A$ is initialized randomly, while $B$ is initialized to 0, ensuring $\Delta W = 0$ at start of training.
- **$\alpha$**: Constant scaling factor.

### Benefits
1. **99% Reduction in Trainable Parameters**: Reduces trainable weight count by 10,000x compared to full fine-tuning.
2. **Zero Inference Latency Penalty**: During deployment, $\Delta W = B \cdot A$ can be explicitly added back to $W_0$.
3. **Modular Adapter Switching**: Allows hot-swapping specialized task adapters on a single base model instance.

---

## Related Knowledge & Links

- `[[fine-tuning-and-alignment]]` — Overview of model adaptation techniques.
- `[[hugging-face]]` — Maintains the `peft` library implementing LoRA.
- `[[moc-llm-architectures]]` — Map of Content for model mechanics and fine-tuning.
