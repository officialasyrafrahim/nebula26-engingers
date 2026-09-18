"""Rail Access Optimisation runs module.

Owns the upload/run API, the scenario job queue and the persistence service that
turns validated solver output into stored submission rows.
"""

from app.modules.runs.queue import JobQueue, get_queue

__all__ = ["JobQueue", "get_queue"]
