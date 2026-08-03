from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_editor_exit_keeps_local_changes_without_template_prompt() -> None:
    application = (ASSETS / "planner-app.js").read_text(encoding="utf-8")
    markup = (ASSETS / "editor-workspace-markup.js").read_text(encoding="utf-8")

    assert "const leaveSheetWorkspace = () =>" in application
    assert "window.__plannerSessionDraft?.flush?.()" in application
    assert "Глобальный шаблон не изменён" in application
    assert "leaveSheetWorkspace," in application

    assert "Изменения файла — в черновике" in markup
    assert "Разметка файла сохранена" in markup
    assert "Сохранить как шаблон" in markup
    assert "Сохранить глобальный шаблон?" in markup
    assert "Текущая разметка файла уже сохранена в серверном черновике" in markup
    assert "Сохранить рабочую разметку?" not in markup
    assert "Выйти без сохранения" not in markup


def test_template_action_remains_explicit() -> None:
    markup = (ASSETS / "editor-workspace-markup.js").read_text(encoding="utf-8")

    assert '@click="requestTemplateSave"' in markup
    assert "автоматического применения к будущим похожим книгам" in markup
    assert "Сохранить шаблон" in markup
