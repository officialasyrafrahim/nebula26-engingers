"""Authoritative audit trail writer."""

from typing import Any

from sqlalchemy.orm import Session

from app.domain.models import AuditLog


# TODO(AUD-01): PostgreSQL is authoritative audit store.
def record_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: Any | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """Append an audit row to the session; the caller commits."""
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
    )
    session.add(entry)
    return entry
