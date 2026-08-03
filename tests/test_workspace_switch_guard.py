from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "web" / "frontend" / "assets" / "planner-app.js"


def test_active_session_workspace_switch_is_explicit_and_reversible() -> None:
    source = APPLICATION.read_text(encoding="utf-8")

    assert "Переключить пространство" in source
    assert "Исходные файлы, группы, ручная разметка и календарные правки сохранятся" in source
    assert "workspace.activeWorkspaceId.value = previousId" in source
    assert "await window.__plannerSessionDraft?.flush?.()" in source


def test_workspace_switch_preserves_operator_layouts() -> None:
    source = APPLICATION.read_text(encoding="utf-8")

    assert "const layoutSnapshot = Object.fromEntries" in source
    assert "await interaction.rematchTemplates({ quiet: true })" in source
    assert "schedule.layouts[fileId] = layout" in source
    assert "schedule.invalidateAll()" in source
    assert "if (schedule.currentFile.value?.analysis) await schedule.loadPreview()" in source
    assert "Файлы и ручная разметка сохранены" in source
