"""
Regression tests for ZARA's memory system verifying complete resource cleanup and zero SQLite connection leaks.
Tested with: python3 -W error::ResourceWarning -m unittest discover tests -v
"""
import unittest
import tempfile
import shutil
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from modules.memory import MemoryStore
from modules.vector_memory import SemanticVectorStore
from core.state import Reflection

class TestMemoryResourceCleanup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_mem_leak_test_")
        self.workspace = Path(self.temp_dir)
        self.mem_file = self.workspace / "memory" / "zara_log.md"
        self.mem_store = MemoryStore(self.mem_file)

    def tearDown(self):
        self.mem_store.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_repeated_search_lessons_no_leak(self):
        """Verify calling search_lessons() 100 times does not leak connections."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            for i in range(100):
                res = self.mem_store.search_lessons(f"query_{i} python test", limit=3)
                self.assertIsInstance(res, list)

    def test_repeated_search_semantic_no_leak(self):
        """Verify calling search_semantic() 100 times does not leak connections."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            for i in range(100):
                res = self.mem_store.search_semantic(f"fastapi web endpoints {i}", limit=3)
                self.assertIsInstance(res, list)

    def test_repeated_append_reflections_no_leak(self):
        """Verify appending 50 reflections sequentially commits and closes connections."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            for i in range(50):
                refl = Reflection(
                    task=f"Task number {i}",
                    tag="dev",
                    approach=f"Approach {i} with verified step",
                    result=f"Result {i} exit code 0",
                    lesson=f"Lesson {i} verified unit tests prevent regression"
                )
                self.mem_store.append_reflection(refl)

            # Verify semantic search retrieves the appended reflections
            results = self.mem_store.search_semantic("Task number 42", limit=1)
            self.assertGreater(len(results), 0)
            self.assertIn("Task number 42", results[0]["content"])

    def test_batch_upsert_and_sync_no_leak(self):
        """Verify batch upserting documents closes transactions and connections."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            db_path = self.workspace / "batch_vectors.db"
            vec_store = SemanticVectorStore(db_path)
            try:
                docs = [
                    (f"doc_{j}", f"Content of document {j} describing architecture", {"index": j})
                    for j in range(50)
                ]
                vec_store.upsert_documents(docs)
                found = vec_store.search_semantic("architecture", limit=5)
                self.assertGreater(len(found), 0)
            finally:
                vec_store.close()

    def test_exception_in_query_closes_connection(self):
        """Verify that errors or invalid SQL queries do not leave unclosed connections."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            db_path = self.workspace / "err_vectors.db"
            vec_store = SemanticVectorStore(db_path)
            try:
                # Deliberately cause a query error inside the connection context
                with self.assertRaises(Exception):
                    with vec_store._connection(commit=True) as conn:
                        conn.execute("INVALID SQL SYNTAX HERE")
            finally:
                vec_store.close()

    def test_concurrent_multithreaded_access_no_leak(self):
        """Verify concurrent multi-threaded read/write does not cross-contaminate or leak connections."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            def worker(worker_id: int):
                for k in range(10):
                    refl = Reflection(
                        task=f"Worker {worker_id} Task {k}",
                        tag="threading",
                        approach="Thread-safe operation",
                        result="Success",
                        lesson="Short-lived connections avoid concurrency locking"
                    )
                    self.mem_store.append_reflection(refl)
                    self.mem_store.search_semantic(f"Worker {worker_id}", limit=2)
                    self.mem_store.search_lessons("threading", limit=2)

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(worker, w) for w in range(4)]
                for f in futures:
                    f.result()

if __name__ == "__main__":
    unittest.main()
