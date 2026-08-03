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
    created_at: str = ""
    updated_at: str = ""
    current_revision_id: Optional[str] = None
    revision_number: Optional[int] = None
    success_count: int = 0
    failure_count: int = 0
    last_used_at: Optional[str] = None


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    layout: Dict[str, Any]
    comment: str = ""


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    layout: Optional[Dict[str, Any]] = None
    comment: str = ""


class ImportResult(BaseModel):
    added: int = 0
    updated: int = 0
    merged: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0


class FileUploadDetail(BaseModel):
    filename: str
    status: str
    message: str
    file_id: Optional[str] = None
    lesson_count: Optional[int] = None


class ScheduleUploadResponse(BaseModel):
    filename: Optional[str] = None
    weekly_filename: Optional[str] = None
    run_id: Optional[str] = None
    status: str
    message: str
    details: List[FileUploadDetail] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    reports: List[Dict[str, Any]] = Field(default_factory=list)


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


class ValidateLayoutRequest(BaseModel):
    file_id: str
    group_name: str
    layout: Dict[str, Any]
    workspace_id: Optional[str] = None


class ValidateLayoutResponse(BaseModel):
    status: str
    report: Dict[str, Any]


class GenerateFileSpec(BaseModel):
    file_id: str
    group_name: str
    layout: Dict[str, Any]
    enabled: bool = True


class GenerateScheduleRequest(BaseModel):
    files: List[GenerateFileSpec] = Field(default_factory=list)
    workspace_id: Optional[str] = None
