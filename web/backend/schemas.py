from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class FileUploadDetail(BaseModel):
    filename: str
    status: str
    message: str
    file_id: Optional[str] = None
    lesson_count: Optional[int] = None


class ScheduleUploadResponse(BaseModel):
    filename: Optional[str] = None
    weekly_filename: Optional[str] = None
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
