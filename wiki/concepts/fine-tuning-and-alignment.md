---
title: "Fine-Tuning and Alignment"
type: concept
created: 2026-08-10
updated: 2026-08-10
tags: [concept, fine-tuning, lora, qlora, rlhf, dpo, alignment]
sources:
  - "sources/pdfs/attention-is-all-you-need-paper.md"
---

# Fine-Tuning and Alignment

**Fine-Tuning and Alignment** refer to the techniques used to adapt pre-trained base base models ([[transformer-architecture]]) to follow instructions safely, perform specific tasks, and align with human intent and preferences.

---

## 1. The Model Training Lifecycle

1. **Pre-Training**: Training a raw model on trillions of text tokens using next-token prediction. Result: Base Model.
2. **Supervised Fine-Tuning (SFT)**: Training on high-quality instruction-response pairs (e.g. 10k-100k samples). Result: Instruct Model.
3. **Alignment & Preference Optimization**: Aligning outputs with human preferences (Helpful, Honest, Harmless).
   - **RLHF (Reinforcement Learning from Human Feedback)**: Uses a Reward Model + PPO (Proximal Policy Optimization).
   - **DPO (Direct Preference Optimization)**: Directly optimizes model logits on pairwise preference data without a separate reward model.

---

## 2. Parameter-Efficient Fine-Tuning (PEFT)

Full fine-tuning updates billions of model parameters, requiring massive VRAM. PEFT methods enable efficient tuning on single GPUs:

- **LoRA (Low-Rank Adaptation)**: Freezes pre-trained model weights $W_0$ and injects trainable rank decomposition matrices $A$ and $B$:
  $$W = W_0 + \Delta W = W_0 + B \cdot A$$
- **QLoRA (Quantized LoRA)**: Quantizes base weights to 4-bit NormalFloat (NF4) while maintaining 16-bit LoRA adapter parameters, enabling 65B model fine-tuning on consumer hardware.

---

## Related Knowledge
- [[transformer-architecture]]
- [[openai]]
- [[anthropic]]
- [[hugging-face]]
- [[ai-learning-roadmap]]
