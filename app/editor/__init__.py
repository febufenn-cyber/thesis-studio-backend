"""Structured, deterministic Phase 2 editor primitives."""

# Importing the package installs the safe command wrapper before services import
# ``apply_command`` from the implementation module.
from app.editor import engine as _engine  # noqa: F401,E402
