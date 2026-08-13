"""Sentence embeddings, so "related" can be computed rather than only hand-written.

A Zettelkasten is an associative memory, but this one only ever had the associations that
distillation happened to write — 1.7% of its edges joined one idea to another. An embedding
gives every note a position in meaning-space, so two notes about the same thing find each
other whether or not anyone linked them, and a concept met in a second source converges on the
note that already covers it instead of forking a near-duplicate.

Small on purpose: bge-small is 384 dimensions and runs on ONNX runtime, so it fits in the
container without dragging in PyTorch. The model is baked into the image at build time; a
first boot that downloaded 90MB before serving traffic would be a poor trade.

Everything degrades to None when fastembed is absent, so tests, local development and any
deployment without the model keep working on lexical matching alone.
"""

from __future__ import annotations

import logging
import os
import struct
import threading

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
DIMENSIONS = 384
# How much of a note is embedded. The opening of a note carries its subject; the tail is
# usually link lists, which drag every note toward every other one.
EMBED_CHARS = 2_000

_model = None
_load_failed = False
_lock = threading.Lock()


def available() -> bool:
    return _get_model() is not None


def _get_model():
    """Load once, lazily, and never retry after a failure.

    Retrying per call would put a multi-second import in front of every ingest on a
    deployment that has no model.
    """
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from fastembed import TextEmbedding

            _model = TextEmbedding(model_name=MODEL_NAME)
            logger.info("Embedding model %s ready", MODEL_NAME)
        except Exception as exc:  # absence is a supported configuration
            _load_failed = True
            logger.info("Embeddings unavailable (%s); falling back to lexical matching", exc)
    return _model


def to_bytes(vector) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def from_bytes(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def embed_texts(texts: list[str]) -> list[bytes] | None:
    """Embed a batch. Returns None when no model is available."""
    model = _get_model()
    if model is None or not texts:
        return None
    try:
        vectors = list(model.embed([t[:EMBED_CHARS] for t in texts]))
    except Exception as exc:  # a failed embedding must not fail an ingest
        logger.warning("Embedding failed: %s", exc)
        return None
    return [to_bytes(v) for v in vectors]


def embed_one(text: str) -> bytes | None:
    got = embed_texts([text])
    return got[0] if got else None


def embed_document(title: str, body: str) -> bytes | None:
    """Embed a document the way it will be searched for.

    The title is repeated ahead of the body because it is the strongest single signal of what
    a note is about, and a two-sentence note would otherwise be dominated by its boilerplate.
    """
    return embed_one(f"{title}\n\n{title}\n\n{body or ''}")
