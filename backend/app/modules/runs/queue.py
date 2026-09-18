"""Scenario job queue abstraction.

The queue is transport only: the database is the authority for job state. Two
backends are provided and selected by ``RAO_QUEUE_BACKEND``:

* ``memory`` (default) - a thread-safe in-process deque for dev and tests;
* ``redis`` - a Redis list using ``RPUSH``/``BLPOP`` for a dedicated worker.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings


class JobQueue(Protocol):
    """Transport contract for scenario job identifiers."""

    def enqueue(self, job_id: uuid.UUID) -> None: ...

    def dequeue(self, timeout: float | None = None) -> uuid.UUID | None: ...


class InMemoryJobQueue:
    """Thread-safe in-memory job queue for dev and tests."""

    def __init__(self) -> None:
        self._items: deque[uuid.UUID] = deque()
        self._condition = threading.Condition()

    def enqueue(self, job_id: uuid.UUID) -> None:
        with self._condition:
            self._items.append(job_id)
            self._condition.notify()

    def dequeue(self, timeout: float | None = None) -> uuid.UUID | None:
        with self._condition:
            if not self._items:
                self._condition.wait(timeout)
            if self._items:
                return self._items.popleft()
            return None


class RedisJobQueue:
    """Redis list transport using ``RPUSH`` to enqueue and ``BLPOP`` to claim."""

    def __init__(self, url: str, name: str) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - depends on host install
            raise RuntimeError(
                "RAO_QUEUE_BACKEND=redis requires the 'redis' package"
            ) from exc
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._name = name

    def enqueue(self, job_id: uuid.UUID) -> None:
        self._client.rpush(self._name, str(job_id))

    def dequeue(self, timeout: float | None = None) -> uuid.UUID | None:
        block = 0 if timeout is None else max(1, int(timeout))
        item = self._client.blpop(self._name, timeout=block)
        if item is None:
            return None
        _, value = item
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError):
            return None


@lru_cache
def get_queue() -> JobQueue:
    """Return the process-wide job queue selected by settings."""

    settings = get_settings()
    if settings.queue_backend == "redis":
        return RedisJobQueue(settings.redis_url, settings.queue_name)
    return InMemoryJobQueue()


__all__ = ["InMemoryJobQueue", "JobQueue", "RedisJobQueue", "get_queue"]
