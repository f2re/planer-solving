from dataclasses import dataclass, field
from datetime import date, time
from typing import List, Optional, Set

@dataclass(frozen=True)
class Teacher:
    teacher_id: int
    last_name: str
    first_name: str
    middle_name: str
    position: str
    max_hours_per_week: int
    seniority: int

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name} {self.middle_name}"

@dataclass(frozen=True)
class TeacherUnavailability:
    teacher_id: int
    start_date: Optional[date]
    end_date: Optional[date]
    reason: str
    unavailable_days: List[str] = field(default_factory=list)

@dataclass(frozen=True)
class Discipline:
    discipline_id: int
    discipline_name: str
    group_name: str
    group_size: int
    semester: int
    lecture_hours: int
    practice_hours: int
    lab_hours: int
    lecturer_id: int
    practice_teacher_ids: List[int] = field(default_factory=list)
    lab_teacher_ids: List[int] = field(default_factory=list)

@dataclass(frozen=True)
class Lesson:
    discipline_id: int
    lesson_type: str  # lecture, practice, lab
    lesson_number: int
    topic: str
    duration_minutes: int
    required_room_type: str
    min_capacity: int

@dataclass(frozen=True)
class Room:
    room_id: int
    room_name: str
    building: str
    room_type: str
    capacity: int
    equipment: List[str] = field(default_factory=list)

@dataclass(frozen=True)
class TimeSlot:
    slot_id: int
    day_of_week: str
    start_time: time
    end_time: time
    duration_minutes: int
    slot_number: int

@dataclass(frozen=True)
class CalendarEntry:
    date: date
    is_holiday: bool
    is_working_day: bool
    description: str

@dataclass
class ScheduleAssignment:
    week_number: int
    assignment_date: date
    day_of_week: str
    start_time: time
    end_time: time
    slot_number: int
    discipline_name: str
    lesson_type: str
    topic: str
    group_name: str
    teacher_name: str
    room_name: str
    building: str
    lesson_id: str  # For internal tracking
