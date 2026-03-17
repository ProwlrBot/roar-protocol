# -*- coding: utf-8 -*-
"""Tests for python/src/roar_sdk/token_store.py"""

import threading
from unittest.mock import MagicMock, patch
import pytest

from roar_sdk.token_store import InMemoryTokenStore, RedisTokenStore


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


# ---------------------------------------------------------------------------
# RedisTokenStore
# ---------------------------------------------------------------------------

class TestRedisTokenStore:
    def test_importerror_when_redis_missing(self):
        """Calling a method raises ImportError with a helpful message when redis is not installed."""
        store = RedisTokenStore()  # __init__ must not import redis
        with patch.dict("sys.modules", {"redis": None}):
            # Force _client to None so _get_client re-runs the import path
            store._client = None
            with pytest.raises(ImportError, match="pip install roar-sdk\\[redis\\]"):
                store.get_and_increment("tok_nored", 1)

    def test_instantiation_does_not_require_redis(self):
        """RedisTokenStore() must instantiate without importing redis."""
        # If redis is absent this should still succeed because __init__ is lazy
        with patch.dict("sys.modules", {"redis": None}):
            store = RedisTokenStore(
                redis_url="redis://localhost:6379/0",
                key_prefix="test:",
            )
            assert store._redis_url == "redis://localhost:6379/0"
            assert store._prefix == "test:"
            assert store._client is None

    def test_get_and_increment_within_limit(self):
        """With a mocked redis client, get_and_increment returns True within limit."""
        redis = pytest.importorskip("redis")

        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [1, True]  # [INCR result, EXPIRE result]
        mock_client.pipeline.return_value = mock_pipe

        store = RedisTokenStore(key_prefix="test:")
        store._client = mock_client  # inject mock

        result = store.get_and_increment("tok_r1", 5)
        assert result is True
        mock_pipe.incr.assert_called_once_with("test:tok_r1")
        mock_pipe.expire.assert_called_once_with("test:tok_r1", 86400)

    def test_get_and_increment_exhausted(self):
        """Returns False when new_count > max_uses."""
        pytest.importorskip("redis")

        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [4, True]  # count=4 > max_uses=3
        mock_client.pipeline.return_value = mock_pipe

        store = RedisTokenStore(key_prefix="test:")
        store._client = mock_client

        result = store.get_and_increment("tok_r2", 3)
        assert result is False

    def test_get_and_increment_unlimited(self):
        """max_uses=None always returns True."""
        pytest.importorskip("redis")

        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [999, True]
        mock_client.pipeline.return_value = mock_pipe

        store = RedisTokenStore(key_prefix="test:")
        store._client = mock_client

        result = store.get_and_increment("tok_r3", None)
        assert result is True

    def test_get_count_returns_zero_for_missing_key(self):
        """get_count returns 0 when Redis returns None."""
        pytest.importorskip("redis")

        mock_client = MagicMock()
        mock_client.get.return_value = None

        store = RedisTokenStore(key_prefix="test:")
        store._client = mock_client

        assert store.get_count("tok_unknown") == 0

    def test_get_count_returns_parsed_int(self):
        """get_count returns the integer value stored in Redis."""
        pytest.importorskip("redis")

        mock_client = MagicMock()
        mock_client.get.return_value = "7"

        store = RedisTokenStore(key_prefix="test:")
        store._client = mock_client

        assert store.get_count("tok_r4") == 7
        mock_client.get.assert_called_once_with("test:tok_r4")
