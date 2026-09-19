"""Regression guard against package import cycles.

A circular import can hide behind pytest's collection order: whichever module
pytest imports first may set up the partially initialised package enough for the
cycle to resolve. The worker container imports modules in a different order, so
the cycle only appeared at runtime as a crash loop. Importing each entry point in
a fresh interpreter reproduces the production order and fails closed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

MODULES = [
    "app.main",
    "app.workers.rail_solver_worker",
    "app.modules.solver",
    "app.modules.solver.replan",
    "app.modules.solver.sandbox",
    "app.modules.validator",
    "app.modules.export",
    "app.modules.export.bundle",
    "app.modules.calendar",
    "app.modules.datamall",
    "app.modules.explain.query",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_cleanly_in_a_fresh_interpreter(module: str) -> None:
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=backend,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{module} failed to import:\n{result.stderr}"
