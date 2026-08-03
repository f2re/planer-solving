"""Synchronize template revision metadata after repository-level bulk operations."""
from __future__ import annotations

from .operations_store import OperationsStore


def ensure_template_revisions(operations: OperationsStore) -> None:
    """Create revision #1 for templates inserted outside revision-aware services.

    Workspace import and duplication are intentionally implemented by the core
    repository. This helper completes the operation in the operational layer and
    refreshes compatibility mirrors in the same serialized write section.
    """

    with operations.transaction() as connection:
        operations._bootstrap_template_revisions(connection)
        operations._write_mirrors(connection)
