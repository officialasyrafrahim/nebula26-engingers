"""Planning job queue abstraction.

ERD requirements: PLN-04, ARC-01.
"""

import threading
import uuid
from collections import deque
from functools import lru_cache
from typing import Protocol


class JobQueue(Protocol):
    """Transport contract for planning job identifiers."""

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


class RedisStreamQueue(JobQueue):
    """Redis Streams transport-only backend (not enabled in dev)."""

    # TODO(PLN-04): Redis Streams transport-only backend.
    def enqueue(self, job_id: uuid.UUID) -> None:
        raise NotImplementedError("TODO(PLN-04): Redis Streams queue not implemented")

    def dequeue(self, timeout: float | None = None) -> uuid.UUID | None:
        raise NotImplementedError("TODO(PLN-04): Redis Streams queue not implemented")


@lru_cache
def get_queue() -> JobQueue:
    """Return the process-wide job queue singleton."""
    return InMemoryJobQueue()
