"""Reconcile processing runs interrupted by failures or service restarts."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from src.security import iso_now

logger = logging.getLogger(__name__)
INSTALL_MARK = "_planner_processing_recovery_installed"


def _report(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def fail_running_runs(
    repository: Any,
    *,
    session_id: str | None = None,
    reason: str,
) -> int:
    """Atomically mark stale `running` rows as failed with a recovery note."""

    transaction = getattr(repository, "_transaction", None)
    if not callable(transaction):
        return 0
    stamp = iso_now()
    with transaction() as connection:
        if session_id:
            rows = connection.execute(
                "SELECT id, report_json FROM processing_runs WHERE status = 'running' AND session_id = ?",
                (session_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, report_json FROM processing_runs WHERE status = 'running'",
            ).fetchall()
        for row in rows:
            report = _report(row["report_json"])
            report["interruption"] = {
                "code": "processing_interrupted",
                "message": reason,
                "state_preserved": True,
                "resolution": "Повторите запуск из активного сеанса или истории после устранения причины.",
                "recorded_at": stamp,
            }
            connection.execute(
                """
                UPDATE processing_runs
                SET status = 'failed', error_count = CASE WHEN error_count < 1 THEN 1 ELSE error_count END,
                    report_json = ?, completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (json.dumps(report, ensure_ascii=False, separators=(",", ":")), stamp, row["id"]),
            )
        return len(rows)


def install_processing_recovery(repository: Any) -> None:
    """Recover stale rows and guard every new run for the same session."""

    if getattr(repository, INSTALL_MARK, False):
        return
    try:
        count = fail_running_runs(
            repository,
            reason=(
                "Предыдущий процесс был прерван перезапуском службы или завершился до записи результата. "
                "Исходники и черновик не удалены."
            ),
        )
        if count:
            logger.warning("Marked %s interrupted processing runs as failed", count)
    except Exception:
        logger.exception("Cannot reconcile interrupted processing runs during startup")

    original = getattr(repository, "start_processing_run", None)
    if not callable(original):
        setattr(repository, INSTALL_MARK, True)
        return

    def guarded_start_processing_run(*, workspace_id, session_id, actor, source_count):
        try:
            fail_running_runs(
                repository,
                session_id=str(session_id),
                reason=(
                    "Запуск не был завершён. Перед повторной обработкой он закрыт как неуспешный; "
                    "новый запуск использует тот же сохранённый сеанс."
                ),
            )
        except Exception:
            logger.exception("Cannot close previous run for session %s", session_id)
        return original(
            workspace_id=workspace_id,
            session_id=session_id,
            actor=actor,
            source_count=source_count,
        )

    setattr(repository, "start_processing_run", guarded_start_processing_run)
    setattr(repository, INSTALL_MARK, True)
