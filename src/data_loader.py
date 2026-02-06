import pandas as pd
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from .model import (
    Teacher, TeacherUnavailability, Discipline, Lesson,
    Room, TimeSlot, CalendarEntry
)

class DataLoader:
    def __init__(self, input_dir: str):
        self.input_dir = input_dir

    def _to_int(self, val: Any) -> int:
        """Safe conversion to int, handling '1.0' from pandas."""
        if pd.isna(val):
            return 0
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0

    def _to_optional_int(self, val: Any) -> Optional[int]:
        """Safe conversion to optional int."""
        if pd.isna(val):
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    def load_teachers(self) -> List[Teacher]:
        df = pd.read_csv(os.path.join(self.input_dir, 'teachers.csv'))
        return [
            Teacher(
                teacher_id=self._to_int(row['teacher_id']),
                last_name=row['last_name'],
                first_name=row['first_name'],
                middle_name=row['middle_name'],
                position=row['position'],
                max_hours_per_week=self._to_int(row['max_hours_per_week']),
                seniority=self._to_int(row['seniority'])
            ) for _, row in df.iterrows()
        ]

    def load_teacher_unavailability(self) -> List[TeacherUnavailability]:
        file_path = os.path.join(self.input_dir, 'teacher_unavailability.csv')
        if not os.path.exists(file_path):
            return []
        df = pd.read_csv(file_path)
        
        def parse_date(val):
            if pd.isna(val) or val == '':
                return None
            try:
                return datetime.strptime(str(val), '%Y-%m-%d').date()
            except ValueError:
                return None

        def parse_days(val):
            if pd.isna(val) or val == '':
                return []
            return [d.strip() for d in str(val).split(';') if d.strip()]

        return [
            TeacherUnavailability(
                teacher_id=self._to_int(row['teacher_id']),
                start_date=parse_date(row['start_date']),
                end_date=parse_date(row['end_date']),
                reason=row['reason'],
                unavailable_days=parse_days(row.get('unavailable_days', ''))
            ) for _, row in df.iterrows()
        ]

    def load_disciplines(self) -> List[Discipline]:
        df = pd.read_csv(os.path.join(self.input_dir, 'disciplines.csv'))
        
        def parse_ids(val):
            if pd.isna(val) or str(val).strip() == '':
                return []
            # IDs might be like "3.0; 4.0" or just "3;4"
            try:
                return [int(float(x.strip())) for x in str(val).split(';') if x.strip()]
            except (ValueError, TypeError):
                return []

        return [
            Discipline(
                discipline_id=self._to_int(row['discipline_id']),
                discipline_name=row['discipline_name'],
                group_name=row['group_name'],
                group_size=self._to_int(row['group_size']),
                semester=self._to_int(row['semester']),
                lecture_hours=self._to_int(row['lecture_hours']),
                practice_hours=self._to_int(row['practice_hours']),
                lab_hours=self._to_int(row['lab_hours']),
                lecturer_id=self._to_int(row['lecturer_id']),
                practice_teacher_ids=parse_ids(row['practice_teacher_ids']),
                lab_teacher_ids=parse_ids(row['lab_teacher_ids'])
            ) for _, row in df.iterrows()
        ]

    def load_thematic_plans(self) -> List[Lesson]:
        df = pd.read_csv(os.path.join(self.input_dir, 'thematic_plans.csv'))
        return [
            Lesson(
                discipline_id=self._to_int(row['discipline_id']),
                lesson_type=row['lesson_type'],
                lesson_number=self._to_int(row['lesson_number']),
                topic=row['topic'],
                duration_minutes=self._to_int(row['duration_minutes']),
                required_room_type=row['required_room_type'],
                min_capacity=self._to_int(row['min_capacity'])
            ) for _, row in df.iterrows()
        ]

    def load_rooms(self) -> List[Room]:
        df = pd.read_csv(os.path.join(self.input_dir, 'rooms.csv'))
        
        def parse_equipment(val):
            if pd.isna(val) or val == '':
                return []
            return [e.strip() for e in str(val).split(';') if e.strip()]

        return [
            Room(
                room_id=self._to_int(row['room_id']),
                room_name=row['room_name'],
                building=row['building'],
                room_type=row['room_type'],
                capacity=self._to_int(row['capacity']),
                equipment=parse_equipment(row.get('equipment', ''))
            ) for _, row in df.iterrows()
        ]

    def load_timeslots(self) -> List[TimeSlot]:
        df = pd.read_csv(os.path.join(self.input_dir, 'timeslots.csv'))
        return [
            TimeSlot(
                slot_id=self._to_int(row['slot_id']),
                day_of_week=row['day_of_week'],
                start_time=datetime.strptime(str(row['start_time']), '%H:%M').time(),
                end_time=datetime.strptime(str(row['end_time']), '%H:%M').time(),
                duration_minutes=self._to_int(row['duration_minutes']),
                slot_number=self._to_int(row['slot_number'])
            ) for _, row in df.iterrows()
        ]

    def load_calendar(self) -> List[CalendarEntry]:
        df = pd.read_csv(os.path.join(self.input_dir, 'calendar.csv'))
        return [
            CalendarEntry(
                date=datetime.strptime(str(row['date']), '%Y-%m-%d').date(),
                is_holiday=bool(row['is_holiday']),
                is_working_day=bool(row['is_working_day']),
                description=row['description']
            ) for _, row in df.iterrows()
        ]

    def load_all(self) -> Dict[str, Any]:
        return {
            'teachers': self.load_teachers(),
            'teacher_unavailability': self.load_teacher_unavailability(),
            'disciplines': self.load_disciplines(),
            'lessons': self.load_thematic_plans(),
            'rooms': self.load_rooms(),
            'timeslots': self.load_timeslots(),
            'calendar': self.load_calendar()
        }