from pathlib import Path


ROOT = Path(__file__).parents[1] / "web" / "frontend" / "assets"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_schedule_draft_is_saved_server_side_and_restored_after_reload():
    draft = read("schedule-draft.js")
    planner = read("planner-app.js")
    assert "planner-analysis-session-v2" in draft
    assert "axios.put(`/api/analysis/${id}/draft`" in draft
    assert "axios.get(`/api/analysis/${stored.session_id}`" in draft
    assert "period_overrides" in draft
    assert "calendar_overrides" in draft
    assert "layouts" in draft
    assert "keepalive: true" in draft
    assert "beforeunload" in draft
    assert "rememberSession(schedule.sessionId.value" in draft
    assert "restoreDraft" in planner
    assert "reactiveWorkspace.refreshWorkspace(restored.workspace_id" in planner


def test_draft_wraps_streaming_interaction_instead_of_shadowing_it():
    draft = read("schedule-draft.js")
    planner = read("planner-app.js")
    interaction_create = planner.index("const interaction = createInteractionState")
    draft_create = planner.index("const scheduleDraft = createScheduleDraftState")
    interaction_spread = planner.index("...interaction")
    draft_spread = planner.index("...scheduleDraft")
    assert interaction_create < draft_create
    assert interaction_spread < draft_spread
    assert "interaction\n            );" in planner or "interaction\r\n            );" in planner
    assert "interaction?.handleFileInput || schedule.handleFileInput" in draft
    assert "interaction?.handleDrop || schedule.handleDrop" in draft
    assert "interaction?.resetWorkflow || schedule.resetWorkflow" in draft
    assert "interaction?.rematchTemplates" in draft
    assert "interaction?.clearRangeSelection" in draft


def test_all_unreadable_files_still_open_a_recoverable_session():
    draft = read("schedule-draft.js")
    generation = read("schedule-diagnostic-generation.js")
    planner = read("planner-app.js")
    assert "exposeUnparsedSession" in draft
    assert "if (schedule.step.value === 1) schedule.step.value = 2" in draft
    assert "Восстановлен сеанс с неразобранными файлами" in draft
    assert "Замените нужный файл кнопкой «Выбрать другой»" in draft
    assert "!file.analysis || file.enabled" in generation
    assert "const canGenerate = computed(() => recoverableFiles.value.length > 0)" in generation
    assert "enabled: file.analysis ? Boolean(file.enabled) : true" in generation
    assert "Диагностический результат готов" in generation
    assert "createScheduleDiagnosticGenerationState" in planner
    assert "...scheduleDiagnosticGeneration" in planner
    assert planner.index("...scheduleDraft") < planner.index("...scheduleDiagnosticGeneration")


def test_result_can_return_to_the_problem_file_without_deleting_session():
    draft = read("schedule-draft.js")
    markup = read("session-draft-markup.js")
    css = read("session-draft.css")
    assert "returnToCorrections" in draft
    assert "openResultFile" in draft
    assert "schedule.step.value = 2" in draft
    assert "await schedule.validateCurrent()" in draft
    assert "Вернуться к файлам и правкам" in markup
    assert "Открыть и исправить" in markup
    assert "resultCorrections" in markup
    assert "resultProblemFiles" in markup
    assert "result.warnings?.length" in markup
    assert "Предупреждения результата" in markup
    assert ".result-corrections-panel" in css
    assert ".analysis-draft-status" in css
    assert ".result-warning-list" in css


def test_result_discloses_every_input_file_omitted_from_backend_details():
    coverage = read("schedule-result-coverage.js")
    markup = read("session-draft-markup.js")
    planner = read("planner-app.js")
    css = read("session-draft.css")
    assert "resultExcludedFiles" in coverage
    assert "!includedIds.has" in coverage
    assert "!file.analysis || !file.enabled" in coverage
    assert "createScheduleResultCoverageState" in planner
    assert "...scheduleResultCoverage" in planner
    assert "resultExcludedFiles.length" in markup
    assert "Не вошли в текущий результат" in markup
    assert "Откройте, включите или замените" in markup
    assert ".result-coverage-section" in css
    assert ".result-problem-item.excluded" in css


def test_one_file_can_be_replaced_without_resetting_the_session():
    draft = read("schedule-draft.js")
    markup = read("session-draft-markup.js")
    css = read("session-draft.css")
    assert "/files/${fileId}/replace" in draft
    assert "startFileReplacement" in draft
    assert "replaceAnalysisFile" in draft
    assert "Остальные файлы, ручные даты и разметки сохранены" in draft
    assert "analysis-file-replacement" in markup
    assert "Выбрать другой" in markup
    assert "replace-session-file" in markup
    assert ".replace-session-file" in css


def test_teacher_mapping_action_opens_the_relevant_sheet_area():
    draft = read("schedule-draft.js")
    assert "action?.type === 'open_teacher_mapping'" in draft
    assert "interaction?.setSelectionMode?.('legend')" in draft
    assert "schedule.previewRegion.value = 'legend'" in draft
    assert "Проверьте столбцы лектора" in draft


def test_diagnostic_generation_flushes_completed_result_to_the_draft():
    generation = read("schedule-diagnostic-generation.js")
    assert "await schedule.validateAll();" in generation
    assert "await scheduleDraft.flushDraft({ quiet: false })" in generation
    assert "allow_partial: true" in generation
    assert "layout: file.analysis" in generation


def test_bootstrap_loads_new_draft_styles_and_markup_before_mount():
    app = read("app.js")
    planner = read("planner-app.js")
    assert "/assets/session-draft.css" in app
    assert "installSessionDraftMarkup();" in planner
    assert planner.index("installSessionDraftMarkup();") < planner.index("createApp({")
