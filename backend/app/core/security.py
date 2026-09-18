"""Development authentication stub and role enforcement."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app.domain.enums import UserRole


@dataclass
class CurrentUser:
    """Authenticated actor and role."""

    id: str
    role: UserRole


# TODO(SEC-01): replace dev header auth with OIDC/RBAC.
def get_current_user(
    x_user_id: str = Header(default="dev-user"),
    x_user_role: str = Header(default="PLANNER"),
) -> CurrentUser:
    """Resolve the current user from development headers."""
    try:
        role = UserRole(x_user_role)
    except ValueError:
        raise HTTPException(status_code=403, detail="unknown role") from None
    return CurrentUser(id=x_user_id, role=role)


def require_role(*roles: UserRole) -> Callable[[CurrentUser], CurrentUser]:
    """Build a dependency enforcing membership in the given roles."""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dependency
