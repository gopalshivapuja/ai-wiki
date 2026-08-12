---
uid: '20260810090300'
title: Retrieval-Augmented Generation (RAG)
class: note
type: concept
created: '2026-08-10'
updated: '2026-08-10'
tags:
- concept
- rag
- embeddings
- vector-database
- llm-applications
---

# Retrieval-Augmented Generation (RAG)

**Retrieval-Augmented Generation (RAG)** is an architectural pattern that connects Large Language Models ([[transformer-architecture]]) to external knowledge bases. RAG retrieves relevant document passages at query time and passes them into the LLM context window to generate grounded, fact-based answers with citations.

---

## 1. Traditional RAG vs. LLM Wiki Pattern

| Aspect | Traditional RAG | LLM Wiki Pattern |
| :--- | :--- | :--- |
| **Knowledge Compilation** | Chunks raw documents & embeds them on-the-fly. | Incrementally synthesizes interlinked markdown files. |
| **Synthesis Accumulation** | None; rediscovers knowledge on every query. | Compounding; cross-references and syntheses persist. |
| **Context Assembly** | Top-K vector search similarity chunks. | Structured index browsing & synthesis pages. |
| **Maintenance** | Vector DB index updates. | LLM-driven updating of entity, concept, and index pages. |

---

## 2. Standard RAG Pipeline Components

1. **Document Ingestion & Chunking**: Splitting text into fixed-size or semantic chunks (e.g. 512 tokens with overlap).
2. **Embedding Generation**: Converting text chunks into dense vector representations (e.g., via OpenAI embeddings or Hugging Face sentence-transformers).
3. **Vector Database Retrieval**: Indexing vectors in DBs (Pinecone, Qdrant, Chroma, pgvector) using approximate nearest neighbor (ANN) search (HNSW, Cosine similarity).
4. **Reranking**: Using cross-encoders (Cohere Rerank, BGE-Reranker) to filter top-k chunks.
5. **Generation**: Injecting top chunks into the LLM prompt context window.

---

## Related Knowledge
- [[transformer-architecture]] — the context window RAG exists to work around.
- [[ai-agents-and-tools]] — retrieval is the most common tool an agent calls.
- [[state-of-ai-engineering]] — compares retrieval against a curated wiki.
- [[hugging-face]] — hosts the embedding and reranking models retrieval depends on.
