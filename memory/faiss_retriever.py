"""FAISS-based semantic retrieval for long-term agent memory.

Embeds facts, document snippets, and conversation summaries for
similarity search when resolving references like 'that email' or 'the contract'.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class FAISSRetriever:
    """Manage a FAISS flat-IP index + a parallel metadata list."""

    def __init__(self, cfg: dict):
        self._index_path = Path(cfg.get("faiss_index_path", "data/faiss.index"))
        self._meta_path = self._index_path.with_suffix(".meta.json")
        self._dim: int = cfg.get("embedding_dim", 384)
        self._embed_model_name: str = cfg.get("embedding_model", "all-MiniLM-L6-v2")

        self._index = None
        self._metadata: list[dict] = []
        self._embedder = None

        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_or_create()

    # ---- Lazy-load embedding model --------------------------------------- #

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self._embed_model_name)
                logger.info("Loaded embedding model: %s", self._embed_model_name)
            except ImportError:
                logger.warning("sentence-transformers not installed; embeddings disabled.")
        return self._embedder

    def _embed(self, texts: list[str]) -> np.ndarray:
        embedder = self._get_embedder()
        if embedder is None:
            return np.zeros((len(texts), self._dim), dtype="float32")
        return embedder.encode(texts, normalize_embeddings=True).astype("float32")

    # ---- Index management ------------------------------------------------ #

    def _load_or_create(self):
        try:
            import faiss
        except ImportError:
            logger.warning("faiss-cpu not installed; FAISS retriever disabled.")
            return

        if self._index_path.exists() and self._meta_path.exists():
            self._index = faiss.read_index(str(self._index_path))
            self._metadata = json.loads(self._meta_path.read_text())
            logger.info("FAISS index loaded: %d vectors", self._index.ntotal)
        else:
            self._index = faiss.IndexFlatIP(self._dim)
            self._metadata = []

    def _save(self):
        if self._index is None:
            return
        import faiss
        faiss.write_index(self._index, str(self._index_path))
        self._meta_path.write_text(json.dumps(self._metadata, indent=2))

    # ---- Public API ------------------------------------------------------ #

    def add(self, text: str, source: str = "", extra: dict | None = None) -> str:
        """Embed and store a text snippet. Returns an ID string."""
        if self._index is None:
            return ""
        vec = self._embed([text])
        idx = self._index.ntotal
        self._index.add(vec)
        entry_id = f"vec_{idx}"
        self._metadata.append({
            "id": entry_id,
            "text": text[:500],  # store truncated text for display
            "source": source,
            **(extra or {}),
        })
        self._save()
        return entry_id

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return the top-k most similar stored entries."""
        if self._index is None or self._index.ntotal == 0:
            return []
        vec = self._embed([query])
        scores, indices = self._index.search(vec, min(top_k, self._index.ntotal))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            entry = dict(self._metadata[idx])
            entry["score"] = float(score)
            results.append(entry)
        return results

    @property
    def size(self) -> int:
        return self._index.ntotal if self._index else 0
