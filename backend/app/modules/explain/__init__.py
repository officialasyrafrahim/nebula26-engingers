"""Deterministic explainability helpers.

The package is deliberately model-free. :mod:`app.modules.explain.query` turns a
small closed query grammar into answers built only from persisted schedule
evidence. It never reaches an external service and never performs data egress.
"""

from app.modules.explain.query import (
    AccessEvidence,
    ContractEvidence,
    OccupancyEvidence,
    ParsedQuery,
    QueryContext,
    QueryResult,
    QuerySyntaxError,
    answer_query,
    parse_query,
)

__all__ = [
    "AccessEvidence",
    "ContractEvidence",
    "OccupancyEvidence",
    "ParsedQuery",
    "QueryContext",
    "QueryResult",
    "QuerySyntaxError",
    "answer_query",
    "parse_query",
]
