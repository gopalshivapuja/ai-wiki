---
uid: '20260810091600'
title: Attention Is All You Need
class: source
type: pdf
created: '2026-08-10'
updated: '2026-08-10'
---

# Attention Is All You Need

**Authors:** Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser, Illia Polosukhin  
**Affiliation:** Google Brain, Google Research, University of Toronto  
**Ingested:** 2026-08-10  

---

## Abstract

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.

---

## Key Technical Architecture

1. **Encoder and Decoder Stacks**: The encoder is composed of a stack of $N=6$ identical layers. Each layer has two sub-layers: Multi-Head Self-Attention and Position-wise Fully Connected Feed-Forward Network.
2. **Scaled Dot-Product Attention**:
   $$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$
3. **Multi-Head Attention**: Allows the model to jointly attend to information from different representation subspaces at different positions.
4. **Positional Encoding**: Added to input embeddings to inject sequence order without recurrence.
