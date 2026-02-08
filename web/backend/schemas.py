from pydantic import BaseModel
from typing import List, Optional, Dict

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

class ScheduleUploadResponse(BaseModel):
    filename: Optional[str] = None
    status: str
    message: str
    details: List[FileUploadDetail]