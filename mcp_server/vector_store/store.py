from __future__ import annotations

import logging
import math
import re
import pickle
from collections import Counter
from pathlib import Path

import numpy as np
import faiss
from mcp_server.dataset.products import PRODUCTS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

# Get the project root (2 levels up from this file)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

INDEX_DIR            = ROOT_DIR / "mcp_server" / "indexes"
FAISS_INDEX_PATH     = INDEX_DIR / "faiss.index"
BM25_PATH            = INDEX_DIR / "bm25.pkl"
CORPUS_PATH          = INDEX_DIR / "corpus.pkl"
EMBEDDING_MODEL_PATH = ROOT_DIR / "mcp_server" / "models" / "sentence-transformers_all-MiniLM-L6-v2"

# ─────────────────────────────────────────────────────────────────────────────
# BM25
# ─────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class BM25:
    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.tokenized = [_tokenize(doc) for doc in corpus]
        self.n = len(self.tokenized)
        self.avg_dl = sum(len(d) for d in self.tokenized) / max(self.n, 1)
        self.df: dict[str, int] = {}
        for doc in self.tokenized:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1

    def get_scores(self, query: str) -> list[float]:
        tokens = _tokenize(query)
        scores = []
        for idx, doc in enumerate(self.tokenized):
            dl = len(doc)
            tf_map = Counter(doc)
            score = 0.0
            for term in tokens:
                if term not in self.df:
                    continue
                idf = math.log((self.n - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
                tf = tf_map.get(term, 0)
                score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avg_dl))
            scores.append(score)
        return scores


# ─────────────────────────────────────────────────────────────────────────────
# Vector Store
# ─────────────────────────────────────────────────────────────────────────────

class VectorStore:
    def __init__(self):
        self._model = None
        self._faiss_index: faiss.Index | None = None
        self._bm25: BM25 | None = None
        self._corpus: list[str] = []

    # ── internal ──────────────────────────────────────────────────────────────

    def _load_model(self) -> None:
        from sentence_transformers import SentenceTransformer
        if EMBEDDING_MODEL_PATH.exists():
            logger.info("Loading embedding model from %s...", EMBEDDING_MODEL_PATH)
            self._model = SentenceTransformer(str(EMBEDDING_MODEL_PATH))
        else:
            logger.info("Loading embedding model...")
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._model.save(str(EMBEDDING_MODEL_PATH))
            logger.info("Model saved to %s", EMBEDDING_MODEL_PATH)

    def _is_built(self) -> bool:
        return FAISS_INDEX_PATH.exists() and BM25_PATH.exists() and CORPUS_PATH.exists()

    def _build(self) -> None:
        INDEX_DIR.mkdir(exist_ok=True)
        self._load_model()

        self._corpus = [f"{p['name']}. {p['description']}" for p in PRODUCTS]

        # Embeddings
        logger.info("Encoding %d products...", len(self._corpus))
        embeddings = self._model.encode(
            self._corpus, convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")

        # FAISS index (inner product = cosine on normalised vectors)
        dim = embeddings.shape[1]
        self._faiss_index = faiss.IndexFlatIP(dim)
        self._faiss_index.add(embeddings)

        # BM25
        self._bm25 = BM25(self._corpus)

        # Persist
        faiss.write_index(self._faiss_index, str(FAISS_INDEX_PATH))
        with open(BM25_PATH,  "wb") as f: pickle.dump(self._bm25,   f)
        with open(CORPUS_PATH,"wb") as f: pickle.dump(self._corpus,  f)

        logger.info("Index built and saved to %s", INDEX_DIR)

    def _load(self) -> None:
        logger.info("Loading index from %s", INDEX_DIR)
        self._load_model()
        self._faiss_index = faiss.read_index(str(FAISS_INDEX_PATH))
        with open(BM25_PATH,  "rb") as f: self._bm25   = pickle.load(f)
        with open(CORPUS_PATH,"rb") as f: self._corpus  = pickle.load(f)
        logger.info("Index loaded from %s", INDEX_DIR)

    def _ensure_ready(self) -> None:
        """Load from disk if exists, build from scratch if not."""
        if self._faiss_index is not None:
            return   # already in memory
        if self._is_built():
            self._load()
        else:
            logger.info("No saved index found — building...")
            self._build()

    # ── public ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 3,
        alpha: float = 0.6,
        sim_threshold: float = 0.25,
    ) -> list[dict]:
        
        import time

        start = time.perf_counter()

        self._ensure_ready()

        end = time.perf_counter()

        logger.info(f"Ensure Ready time: {end - start:.4f} seconds")

        # Semantic scores via FAISS
        q_emb = self._model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")
        semantic_scores_raw, indices = self._faiss_index.search(q_emb, len(self._corpus))
        
        # Map back to original order (FAISS returns sorted)
        semantic_scores = np.zeros(len(self._corpus))
        for rank, idx in enumerate(indices[0]):
            semantic_scores[idx] = float(semantic_scores_raw[0][rank])

        # BM25 scores normalised to [0, 1]
        bm25_raw = np.array(self._bm25.get_scores(query))
        bm25_scores = bm25_raw / (bm25_raw.max() or 1.0)

        # Hybrid
        hybrid = alpha * semantic_scores + (1 - alpha) * bm25_scores

        # Rank and filter
        results = []
        for idx in np.argsort(hybrid)[::-1][:top_k]:
            score = float(hybrid[idx])
            if score < sim_threshold:
                break
            p = PRODUCTS[int(idx)]
            results.append({
                "id":          p["id"],
                "name":        p["name"],
                "description": p["description"],
                "score":       round(score, 4),
            })
        
        s_end = time.perf_counter()
        logger.info(f"Search Execution time: {s_end - start:.4f} seconds")
        return results


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + convenience function
# ─────────────────────────────────────────────────────────────────────────────

vector_store = VectorStore()

def hybrid_search(query: str, top_k: int = 3) -> list[dict]:
    logger.info(f"Initiating hybrid search...")
    return vector_store.search(query, top_k=top_k)