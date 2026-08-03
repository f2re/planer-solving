from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.workspace_domain import default_semester_settings


def _default_start_date() -> date:
    return date.fromisoformat(default_semester_settings()["schedule_start_date"])


def _default_end_date() -> date:
    return date.fromisoformat(default_semester_settings()["schedule_end_date"])


class Teacher(BaseModel):
    id: int
    short_name: str
    full_name: str
    position: Optional[str] = None
    rank: Optional[str] = None
    academic_degree: Optional[str] = None


class TeacherCreate(BaseModel):
    short_name: str
    full_name: str
    position: Optional[str] = None
    rank: Optional[str] = None
    academic_degree: Optional[str] = None


class TeacherUpdate(BaseModel):
    short_name: Optional[str] = None
    full_name: Optional[str] = None
    position: Optional[str] = None
    rank: Optional[str] = None
    academic_degree: Optional[str] = None


class WorkspaceSettings(BaseModel):
    schedule_start_date: date = Field(default_factory=_default_start_date)
    schedule_end_date: date = Field(default_factory=_default_end_date)


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    color: str
    description: str = ""
    teacher_count: int = 0
    template_count: int = 0
    is_default: bool = False
    created_at: str = ""
    updated_at: str = ""
    settings: WorkspaceSettings = Field(default_factory=WorkspaceSettings)


class WorkspaceCreate(BaseModel):
    name: str
    color: str = "#315EFB"
    description: str = ""
    settings: Optional[WorkspaceSettings] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    settings: Optional[WorkspaceSettings] = None


class WorkspaceDuplicateRequest(BaseModel):
    name: Optional[str] = None


class LayoutTemplate(BaseModel):
    id: str
    name: str
    description: str = ""
    layout: Dict[str, Any]
    composite: List[Dict[str, Any]] = Field(default_factory=list)
    fingerprint: Dict[str, Any] = Field(default_factory=dict)
    current_revision: int = 1
    success_count: int = 0
    warning_count: int = 0
    failure_count: int = 0
    total_lessons: int = 0
    avg_quality: float = 0
    last_used_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    layout: Dict[str, Any]
    composite: List[Dict[str, Any]] = Field(default_factory=list)
    fingerprint: Dict[str, Any] = Field(default_factory=dict)
    comment: str = "Создан шаблон"


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    layout: Optional[Dict[str, Any]] = None
    composite: Optional[List[Dict[str, Any]]] = None
    fingerprint: Optional[Dict[str, Any]] = None
    comment: Optional[str] = None


class ImportResult(BaseModel):
    added: int = 0
    skipped: int = 0
    total: int = 0


class FileUploadDetail(BaseModel):
    filename: str
    status: str
    message: str
    file_id: Optional[str] = None
    lesson_count: Optional[int] = None
    used: bool = True
    warning_count: int = 0
    action_count: int = 0


class ScheduleUploadResponse(BaseModel):
    filename: Optional[str] = None
    weekly_filename: Optional[str] = None
    run_id: Optional[str] = None
    status: str
    message: str
    details: List[FileUploadDetail] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    reports: List[Dict[str, Any]] = Field(default_factory=list)
    corrections: List[Dict[str, Any]] = Field(default_factory=list)


class AnalysisFile(BaseModel):
    file_id: str
    filename: str
    group_name: str
    status: str
    message: str = ""
    analysis: Optional[Dict[str, Any]] = None


class AnalyzeResponse(BaseModel):
    session_id: str
    files: List[AnalysisFile] = Field(default_factory=list)


class AnalysisDraftFileState(BaseModel):
    file_id: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    group_name: str = Field(default="", max_length=240)


class AnalysisDraftRequest(BaseModel):
    """Small operator-owned state persisted next to uploaded source files."""

    version: int = Field(default=1, ge=1, le=10)
    workspace_id: Optional[str] = Field(default=None, max_length=120)
    selected_file_id: Optional[str] = Field(default=None, max_length=80)
    step: int = Field(default=2, ge=1, le=3)
    files: List[AnalysisDraftFileState] = Field(default_factory=list, max_length=500)
    layouts: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    period_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    calendar_overrides: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None


class ValidateLayoutRequest(BaseModel):
    file_id: str
    group_name: str
    layout: Dict[str, Any]
    workspace_id: Optional[str] = None
    period_overrides: Dict[str, Any] = Field(default_factory=dict)


class ValidateLayoutResponse(BaseModel):
    status: str
    report: Dict[str, Any]


class GenerateFileSpec(BaseModel):
    file_id: str
    group_name: str
    layout: Dict[str, Any]
    enabled: bool = True
    period_overrides: Dict[str, Any] = Field(default_factory=dict)


class GenerateScheduleRequest(BaseModel):
    files: List[GenerateFileSpec] = Field(default_factory=list)
    workspace_id: Optional[str] = None
    calendar_overrides: Dict[str, Any] = Field(default_factory=dict)
    allow_partial: bool = True
