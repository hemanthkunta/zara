"""
ZARA Semantic Vector Memory: Zero-dependency embedded vector store using SQLite and TF-IDF / N-gram cosine embeddings.
Provides dense semantic similarity retrieval across all past experiences, lessons, and task episodes.
"""
import sqlite3
import math
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Iterator
from contextlib import contextmanager
from config.settings import MEMORY_DIR

DB_PATH = MEMORY_DIR / "vectors.db"

class SemanticVectorStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self, commit: bool = False) -> Iterator[sqlite3.Connection]:
        """Context manager that guarantees the connection is properly closed and committed/rolled back."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            yield conn
            if commit:
                conn.commit()
        except Exception:
            if commit:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS embeddings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        doc_id TEXT UNIQUE,
                        content TEXT NOT NULL,
                        metadata TEXT,
                        vector_json TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            finally:
                cursor.close()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Tokenize text into lowercase words and character 3-grams for semantic fuzzy matching."""
        words = re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text.lower())
        tokens = list(words)
        # Add subword 3-grams for semantic typo-tolerance
        for w in words:
            if len(w) >= 4:
                tokens.extend([w[i:i+3] for i in range(len(w) - 2)])
        return tokens

    def _compute_vector(self, text: str) -> Dict[str, float]:
        """Compute normalized term-frequency vector."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        tf: Dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0.0) + 1.0

        # L2 normalize
        magnitude = math.sqrt(sum(val * val for val in tf.values()))
        if magnitude == 0:
            return {}

        return {k: v / magnitude for k, v in tf.items()}

    @staticmethod
    def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
        """Compute cosine similarity between two sparse vectors."""
        if not vec_a or not vec_b:
            return 0.0
        # Iterate over smaller dict
        smaller, larger = (vec_a, vec_b) if len(vec_a) < len(vec_b) else (vec_b, vec_a)
        dot_product = sum(weight * larger.get(term, 0.0) for term, weight in smaller.items())
        return dot_product

    def upsert_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Embed and store document in SQLite vector database."""
        vector = self._compute_vector(content)
        vec_json = json.dumps(vector)
        meta_json = json.dumps(metadata or {})

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO embeddings (doc_id, content, metadata, vector_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        content=excluded.content,
                        metadata=excluded.metadata,
                        vector_json=excluded.vector_json
                """, (doc_id, content, meta_json, vec_json))
            finally:
                cursor.close()

    def upsert_documents(self, documents: List[Tuple[str, str, Optional[Dict[str, Any]]]]) -> None:
        """Batch embed and store multiple documents in a single transaction and connection."""
        if not documents:
            return
        rows = []
        for doc_id, content, metadata in documents:
            vector = self._compute_vector(content)
            vec_json = json.dumps(vector)
            meta_json = json.dumps(metadata or {})
            rows.append((doc_id, content, meta_json, vec_json))

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany("""
                    INSERT INTO embeddings (doc_id, content, metadata, vector_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        content=excluded.content,
                        metadata=excluded.metadata,
                        vector_json=excluded.vector_json
                """, rows)
            finally:
                cursor.close()

    def search_semantic(self, query: str, limit: int = 5, min_score: float = 0.05) -> List[Dict[str, Any]]:
        """Dense semantic search across stored documents."""
        query_vec = self._compute_vector(query)
        if not query_vec:
            return []

        scored_results = []
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT doc_id, content, metadata, vector_json FROM embeddings")
                rows = cursor.fetchall()
            finally:
                cursor.close()

        for doc_id, content, meta_json, vec_json in rows:
            try:
                doc_vec = json.loads(vec_json)
                score = self._cosine_similarity(query_vec, doc_vec)
                if score >= min_score:
                    metadata = json.loads(meta_json) if meta_json else {}
                    scored_results.append({
                        "doc_id": doc_id,
                        "content": content,
                        "metadata": metadata,
                        "similarity_score": round(score, 4)
                    })
            except Exception:
                continue

        scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored_results[:limit]

    def close(self) -> None:
        """Explicit cleanup of any vector store resources."""
        pass
