# -*- coding: utf-8 -*-
"""Tests for python/src/roar_sdk/token_store.py"""

import threading
import pytest

from roar_sdk.token_store import InMemoryTokenStore


# ---------------------------------------------------------------------------
# InMemoryTokenStore — basic behavior
# ---------------------------------------------------------------------------

class TestInMemoryTokenStore:
    def test_within_limit(self):
        """3 uses with max_uses=3 all succeed."""
        store = InMemoryTokenStore()
        token_id = "tok_abc"

        assert store.get_and_increment(token_id, 3) is True   # use 1
        assert store.get_and_increment(token_id, 3) is True   # use 2
        assert store.get_and_increment(token_id, 3) is True   # use 3
        assert store.get_count(token_id) == 3

    def test_exhausted(self):
        """4th use with max_uses=3 returns False."""
        store = InMemoryTokenStore()
        token_id = "tok_def"

        store.get_and_increment(token_id, 3)
        store.get_and_increment(token_id, 3)
        store.get_and_increment(token_id, 3)

        result = store.get_and_increment(token_id, 3)
        assert result is False
        # Count stays at 3 (not incremented when exhausted)
        assert store.get_count(token_id) == 3

    def test_unlimited(self):
        """max_uses=None never exhausts."""
        store = InMemoryTokenStore()
        token_id = "tok_ghi"

        for _ in range(100):
            result = store.get_and_increment(token_id, None)
            assert result is True
        assert store.get_count(token_id) == 100

    def test_zero_count_initial(self):
        """get_count returns 0 for an unknown token."""
        store = InMemoryTokenStore()
        assert store.get_count("tok_unknown") == 0

    def test_separate_tokens_independent(self):
        """Different token IDs are tracked independently."""
        store = InMemoryTokenStore()

        store.get_and_increment("tok_x", 2)
        store.get_and_increment("tok_x", 2)
        store.get_and_increment("tok_y", 2)

        assert store.get_count("tok_x") == 2
        assert store.get_count("tok_y") == 1

        # tok_x is exhausted, tok_y still has uses
        assert store.get_and_increment("tok_x", 2) is False
        assert store.get_and_increment("tok_y", 2) is True

    def test_concurrent_simulation(self):
        """10 threads all calling get_and_increment; verify total accepted == max_uses."""
        store = InMemoryTokenStore()
        token_id = "tok_concurrent"
        max_uses = 5
        num_threads = 10

        accepted = []
        lock = threading.Lock()

        def worker():
            result = store.get_and_increment(token_id, max_uses)
            with lock:
                accepted.append(result)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly max_uses threads should have been accepted
        assert sum(1 for r in accepted if r) == max_uses
        assert sum(1 for r in accepted if not r) == num_threads - max_uses
        # The count must equal max_uses (not incremented beyond limit)
        assert store.get_count(token_id) == max_uses

    def test_max_uses_one(self):
        """max_uses=1 allows exactly one use."""
        store = InMemoryTokenStore()
        assert store.get_and_increment("tok_once", 1) is True
        assert store.get_and_increment("tok_once", 1) is False
