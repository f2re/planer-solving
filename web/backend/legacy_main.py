import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.data_loader import DataLoader
from src.exporter import export_to_excel
from src.schedule_analyzer import ScheduleAnalyzer, ScheduleLayout
from src.transformer import transform_to_teacher_grid
from src.weekly_exporter import generate_weekly_semester_schedule
from web.backend.schemas import (
    AnalysisFile,
    AnalyzeResponse,
    FileUploadDetail,
    GenerateScheduleRequest,
    ScheduleUploadResponse,
    Teacher,
    TeacherCreate,
    TeacherUpdate,
    ValidateLayoutRequest,
    ValidateLayoutResponse,
)

app = FastAPI(
    title="Planner Solving",
    description="Operator-assisted parsing of heterogeneous Excel schedules",
)

BASE_DIR = Path(__file__).resolve().parents[2]
TEACHERS_JSON = BASE_DIR / "teachers.json"
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
SESSION_ROOT = INPUT_DIR / "analysis_sessions"
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
SESSION_MAX_AGE_SECONDS = 24 * 60 * 60

for directory in (INPUT_DIR, OUTPUT_DIR, SESSION_ROOT):
    directory.mkdir(parents=True, exist_ok=True)


def _model_dict(model: Any, *, exclude_unset: bool = False) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def _atomic_json_write(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def load_teachers() -> List[dict]:
    if not TEACHERS_JSON.exists():
        return []
    with TEACHERS_JSON.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []


def save_teachers(teachers: List[dict]) -> None:
    _atomic_json_write(TEACHERS_JSON, teachers)


def _cleanup_old_sessions() -> None:
    threshold = time.time() - SESSION_MAX_AGE_SECONDS
    for candidate in SESSION_ROOT.iterdir():
        if not candidate.is_dir():
            continue
        try:
            if candidate.stat().st_mtime < threshold:
                shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue


def _safe_session_dir(session_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        raise HTTPException(status_code=404, detail="Сеанс анализа не найден.")
    path = (SESSION_ROOT / session_id).resolve()
    if path.parent != SESSION_ROOT.resolve():
        raise HTTPException(status_code=404, detail="Сеанс анализа не найден.")
    return path


def _load_manifest(session_id: str) -> Dict[str, Any]:
    session_dir = _safe_session_dir(session_id)
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Сеанс анализа не найден или истёк.")
    try:
        with manifest_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Повреждён файл сеанса: {exc}") from exc


def _manifest_file(manifest: Dict[str, Any], file_id: str) -> Dict[str, Any]:
    for item in manifest.get("files", []):
        if item.get("file_id") == file_id:
            return item
    raise HTTPException(status_code=404, detail="Файл в сеансе не найден.")


def _stored_path(session_id: str, file_item: Dict[str, Any]) -> Path:
    session_dir = _safe_session_dir(session_id)
    path = (session_dir / file_item["stored_name"]).resolve()
    if path.parent != session_dir.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail="Загруженный файл не найден.")
    return path


@app.get("/api/teachers", response_model=List[Teacher])
def get_teachers() -> List[dict]:
    return load_teachers()


@app.post("/api/teachers", response_model=Teacher)
def create_teacher(teacher: TeacherCreate) -> dict:
    teachers = load_teachers()
    new_id = max((item.get("id", 0) for item in teachers), default=0) + 1
    new_teacher = _model_dict(teacher)
    new_teacher["id"] = new_id
    teachers.append(new_teacher)
    save_teachers(teachers)
    return new_teacher


@app.put("/api/teachers/{teacher_id}", response_model=Teacher)
def update_teacher(teacher_id: int, teacher_update: TeacherUpdate) -> dict:
    teachers = load_teachers()
    for index, teacher in enumerate(teachers):
        if teacher.get("id") == teacher_id:
            teachers[index].update(_model_dict(teacher_update, exclude_unset=True))
            save_teachers(teachers)
            return teachers[index]
    raise HTTPException(status_code=404, detail="Преподаватель не найден.")


@app.delete("/api/teachers/{teacher_id}")
def delete_teacher(teacher_id: int) -> Dict[str, str]:
    teachers = load_teachers()
    updated = [teacher for teacher in teachers if teacher.get("id") != teacher_id]
    if len(updated) == len(teachers):
        raise HTTPException(status_code=404, detail="Преподаватель не найден.")
    save_teachers(updated)
    return {"status": "success"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_schedules(files: List[UploadFile] = File(...)) -> AnalyzeResponse:
    _cleanup_old_sessions()
    session_id = str(uuid.uuid4())
    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    analyzer = ScheduleAnalyzer()
    response_files: List[AnalysisFile] = []
    manifest_files: List[Dict[str, Any]] = []

    for upload in files:
        original_name = Path(upload.filename or "schedule.xlsx").name
        extension = Path(original_name).suffix.lower()
        file_id = str(uuid.uuid4())
        group_name = Path(original_name).stem
        item: Dict[str, Any] = {
            "file_id": file_id,
            "filename": original_name,
            "group_name": group_name,
            "stored_name": "",
            "status": "error",
            "message": "",
            "analysis": None,
        }

        if extension not in {".xlsx", ".xlsm"}:
            item["message"] = (
                "Поддерживаются .xlsx и .xlsm. Старый формат .xls необходимо "
                "один раз сохранить как .xlsx."
            )
            manifest_files.append(item)
            response_files.append(AnalysisFile(**{key: item[key] for key in (
                "file_id", "filename", "group_name", "status", "message", "analysis"
            )}))
            continue

        payload = await upload.read()
        if not payload:
            item["message"] = "Файл пуст."
            manifest_files.append(item)
            response_files.append(AnalysisFile(**{key: item[key] for key in (
                "file_id", "filename", "group_name", "status", "message", "analysis"
            )}))
            continue
        if len(payload) > MAX_UPLOAD_SIZE:
            item["message"] = "Размер файла превышает 50 МБ."
            manifest_files.append(item)
            response_files.append(AnalysisFile(**{key: item[key] for key in (
                "file_id", "filename", "group_name", "status", "message", "analysis"
            )}))
            continue

        stored_name = f"{file_id}{extension}"
        stored_path = session_dir / stored_name
        stored_path.write_bytes(payload)
        item["stored_name"] = stored_name

        try:
            analysis = analyzer.analyze(str(stored_path)).to_dict()
            item["analysis"] = analysis
            item["status"] = "success" if analysis["confidence"] >= 0.55 else "warning"
            item["message"] = (
                "Структура определена автоматически."
                if item["status"] == "success"
                else "Структура определена с низкой уверенностью; требуется ручная проверка."
            )
        except Exception as exc:
            item["status"] = "error"
            item["message"] = f"Не удалось проанализировать книгу: {exc}"

        manifest_files.append(item)
        response_files.append(AnalysisFile(**{key: item[key] for key in (
            "file_id", "filename", "group_name", "status", "message", "analysis"
        )}))

    manifest = {
        "session_id": session_id,
        "created_at": time.time(),
        "files": manifest_files,
    }
    _atomic_json_write(session_dir / "manifest.json", manifest)
    return AnalyzeResponse(session_id=session_id, files=response_files)


@app.get("/api/analysis/{session_id}/files/{file_id}/preview")
def preview_schedule(
    session_id: str,
    file_id: str,
    region: str = Query("schedule"),
    row_start: Optional[int] = Query(None, ge=1),
    row_end: Optional[int] = Query(None, ge=1),
    col_start: Optional[int] = Query(None, ge=1),
    col_end: Optional[int] = Query(None, ge=1),
    sheet_name: Optional[str] = Query(None),
) -> Dict[str, Any]:
    if region not in {"schedule", "legend", "custom"}:
        raise HTTPException(status_code=400, detail="Неизвестная область предпросмотра.")
    manifest = _load_manifest(session_id)
    item = _manifest_file(manifest, file_id)
    if not item.get("analysis"):
        raise HTTPException(status_code=400, detail="Для файла нет результатов анализа.")
    analysis = item["analysis"]
    defaults = analysis["legend_preview"] if region == "legend" else analysis["schedule_preview"]
    row_start = row_start or defaults["row_start"]
    row_end = row_end or defaults["row_end"]
    col_start = col_start or defaults["col_start"]
    col_end = col_end or defaults["col_end"]
    if row_end < row_start or col_end < col_start:
        raise HTTPException(status_code=400, detail="Неверно задан диапазон предпросмотра.")

    analyzer = ScheduleAnalyzer()
    try:
        return analyzer.preview(
            str(_stored_path(session_id, item)),
            sheet_name or analysis["selected_sheet"],
            row_start,
            row_end,
            col_start,
            col_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/analysis/{session_id}/validate",
    response_model=ValidateLayoutResponse,
)
def validate_layout(
    session_id: str,
    request: ValidateLayoutRequest,
) -> ValidateLayoutResponse:
    manifest = _load_manifest(session_id)
    item = _manifest_file(manifest, request.file_id)
    layout = ScheduleLayout.from_dict(request.layout)
    loader = DataLoader(str(TEACHERS_JSON))
    loader.load_group_schedule(
        str(_stored_path(session_id, item)),
        group_name=request.group_name,
        layout=layout,
    )
    report = loader.last_report
    status = "error" if report.get("errors") else (
        "warning" if report.get("warnings") else "success"
    )
    return ValidateLayoutResponse(status=status, report=report)


def _generate_from_session(
    session_id: str,
    request: GenerateScheduleRequest,
) -> ScheduleUploadResponse:
    manifest = _load_manifest(session_id)
    enabled_specs = [spec for spec in request.files if spec.enabled]
    if not enabled_specs:
        return ScheduleUploadResponse(
            status="error",
            message="Не выбран ни один файл для обработки.",
        )

    loader = DataLoader(str(TEACHERS_JSON))
    all_lessons = []
    details: List[FileUploadDetail] = []
    reports: List[Dict[str, Any]] = []

    for spec in enabled_specs:
        item = _manifest_file(manifest, spec.file_id)
        try:
            layout = ScheduleLayout.from_dict(spec.layout)
            lessons = loader.load_group_schedule(
                str(_stored_path(session_id, item)),
                group_name=spec.group_name,
                layout=layout,
            )
            report = dict(loader.last_report)
            reports.append(report)
            if report.get("errors"):
                status = "error"
                message = "; ".join(report["errors"])
            elif report.get("warnings"):
                status = "warning"
                message = f"Найдено занятий: {len(lessons)}. Требуется проверить предупреждения."
            else:
                status = "success"
                message = f"Найдено занятий: {len(lessons)}."
            if lessons:
                all_lessons.extend(lessons)
            details.append(
                FileUploadDetail(
                    file_id=spec.file_id,
                    filename=item["filename"],
                    status=status,
                    message=message,
                    lesson_count=len(lessons),
                )
            )
        except Exception as exc:
            details.append(
                FileUploadDetail(
                    file_id=spec.file_id,
                    filename=item["filename"],
                    status="error",
                    message=str(exc),
                    lesson_count=0,
                )
            )

    if not all_lessons:
        return ScheduleUploadResponse(
            status="error",
            message="После проверки разметки не найдено ни одного занятия.",
            details=details,
            reports=reports,
            warnings=list(loader.warnings),
        )

    teachers_config = load_teachers()
    config_path = BASE_DIR / "config.json"
    global_config: Dict[str, Any] = {}
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as file:
                global_config = json.load(file)
        except (OSError, json.JSONDecodeError):
            global_config = {}

    start_date = global_config.get("schedule_start_date", "2026-02-10")
    end_date = global_config.get("schedule_end_date", "2026-06-30")
    filtered_lessons = [lesson for lesson in all_lessons if lesson.teacher != "Unknown"]
    if not filtered_lessons:
        return ScheduleUploadResponse(
            status="error",
            message=(
                "Занятия найдены, но ни для одного не определён преподаватель. "
                "Проверьте координаты блока дисциплин, источник преподавателя и базу сотрудников."
            ),
            details=details,
            reports=reports,
            warnings=list(loader.warnings),
        )
    transformed = transform_to_teacher_grid(
        filtered_lessons,
        teachers_config,
        start_date_str=start_date,
        end_date_str=end_date,
    )

    output_id = str(uuid.uuid4())
    output_filename = f"schedule_{output_id}.xlsx"
    output_path = OUTPUT_DIR / output_filename
    export_to_excel(transformed, teachers_config, str(output_path))

    warnings = list(loader.warnings)
    weekly_filename: Optional[str] = None
    template_path = BASE_DIR / "obrazec" / "Недельное.xlsx"
    if template_path.exists():
        weekly_filename = f"weekly_schedule_{output_id}.xlsx"
        weekly_path = OUTPUT_DIR / weekly_filename
        try:
            generate_weekly_semester_schedule(
                teachers_config=teachers_config,
                lessons=all_lessons,
                template_path=str(template_path),
                output_path=str(weekly_path),
                start_date_str=start_date,
                end_date_str=end_date,
            )
        except Exception as exc:
            weekly_filename = None
            warnings.append(f"Недельный файл не сформирован: {exc}")
    else:
        warnings.append(
            "Недельный файл не сформирован: отсутствует шаблон obrazec/Недельное.xlsx."
        )

    has_errors = any(detail.status == "error" for detail in details)
    has_warnings = any(detail.status == "warning" for detail in details) or bool(warnings)
    status = "warning" if has_errors or has_warnings else "success"
    return ScheduleUploadResponse(
        filename=output_filename,
        weekly_filename=weekly_filename,
        status=status,
        message=(
            "Расписание сформировано, но часть файлов требует внимания."
            if status == "warning"
            else "Расписание сформировано."
        ),
        details=details,
        warnings=warnings,
        reports=reports,
    )


@app.post(
    "/api/analysis/{session_id}/generate",
    response_model=ScheduleUploadResponse,
)
def generate_schedule(
    session_id: str,
    request: GenerateScheduleRequest,
) -> ScheduleUploadResponse:
    return _generate_from_session(session_id, request)


@app.delete("/api/analysis/{session_id}")
def delete_analysis_session(session_id: str) -> Dict[str, str]:
    session_dir = _safe_session_dir(session_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Сеанс анализа не найден.")
    shutil.rmtree(session_dir, ignore_errors=True)
    return {"status": "success"}


@app.post("/api/upload", response_model=ScheduleUploadResponse)
async def upload_schedule_compatibility(
    files: List[UploadFile] = File(...),
) -> ScheduleUploadResponse:
    """Automatic compatibility path for old clients."""
    analysis = await analyze_schedules(files)
    specs = []
    for item in analysis.files:
        if item.analysis and item.status != "error":
            specs.append(
                {
                    "file_id": item.file_id,
                    "group_name": item.group_name,
                    "layout": item.analysis["layout"],
                    "enabled": True,
                }
            )
    request = GenerateScheduleRequest(files=specs)
    return _generate_from_session(analysis.session_id, request)


@app.get("/api/download/{filename}")
def download_file(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    file_path = (OUTPUT_DIR / safe_name).resolve()
    if file_path.parent != OUTPUT_DIR.resolve() or not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден.")
    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


app.mount(
    "/",
    StaticFiles(directory=str(BASE_DIR / "web" / "frontend"), html=True),
    name="frontend",
)
