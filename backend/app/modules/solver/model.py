"""Lazy OR-Tools CP-SAT access.

The rail solver depends on the native OR-Tools runtime, which is an optional
``solver`` extra. Importing it at module import time would make the whole
backend fail to start on hosts that do not ship the native libraries, so the
import is deferred until a solve is actually requested. Callers that need to
probe availability (for example to skip tests) should use
:func:`cp_sat_available` rather than catching the exception.
"""

from __future__ import annotations

from types import ModuleType

DEFAULT_SEED = 42
DEFAULT_TIME_LIMIT_SECONDS = 30.0
DEFAULT_HORIZON_EXTENSION_WEEKS = 6

_INSTALL_HINT = (
    "OR-Tools CP-SAT is unavailable. Install the optional solver extra "
    "(pip install '.[solver]') and ensure the native libraries are on the loader "
    "path (on NixOS this may require LD_LIBRARY_PATH to include the gcc and zlib "
    "runtime libraries)."
)


class OrToolsUnavailableError(RuntimeError):
    """Raised when the native OR-Tools CP-SAT runtime cannot be imported."""


_cp_model: ModuleType | None = None
_import_error: Exception | None = None


def load_cp_model() -> ModuleType:
    """Return the ``cp_model`` module, importing it on first use.

    The original import failure is preserved as ``__cause__`` so operators can
    see whether a missing library or a missing package caused the problem.
    """

    global _cp_model, _import_error
    if _cp_model is not None:
        return _cp_model
    if _import_error is not None:
        raise OrToolsUnavailableError(f"{_INSTALL_HINT} ({_import_error})") from _import_error
    try:
        from ortools.sat.python import cp_model
    except Exception as exc:  # native loader failures are not always ImportError
        _import_error = exc
        raise OrToolsUnavailableError(f"{_INSTALL_HINT} ({exc})") from exc
    _cp_model = cp_model
    return cp_model


def cp_sat_available() -> bool:
    """Return whether the native CP-SAT runtime can be imported."""

    try:
        load_cp_model()
    except OrToolsUnavailableError:
        return False
    return True


__all__ = [
    "DEFAULT_HORIZON_EXTENSION_WEEKS",
    "DEFAULT_SEED",
    "DEFAULT_TIME_LIMIT_SECONDS",
    "OrToolsUnavailableError",
    "cp_sat_available",
    "load_cp_model",
]
