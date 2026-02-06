from typing import List, Dict, Any, Tuple
from .model import Teacher, Room, Discipline, Lesson, TimeSlot

class DataValidator:
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.errors = []
        self.warnings = []

    def validate(self) -> Tuple[bool, List[str], List[str]]:
        self._check_teachers()
        self._check_rooms()
        self._check_disciplines()
        self._check_lessons()
        return len(self.errors) == 0, self.errors, self.warnings

    def _check_teachers(self):
        teachers = self.data['teachers']
        ids = [t.teacher_id for t in teachers]
        if len(ids) != len(set(ids)):
            self.errors.append("Duplicate teacher IDs found.")

    def _check_rooms(self):
        rooms = self.data['rooms']
        ids = [r.room_id for r in rooms]
        if len(ids) != len(set(ids)):
            self.errors.append("Duplicate room IDs found.")

    def _check_disciplines(self):
        disciplines = self.data['disciplines']
        teacher_ids = {t.teacher_id for t in self.data['teachers']}
        
        for d in disciplines:
            if d.lecturer_id not in teacher_ids:
                self.errors.append(f"Lecturer ID {d.lecturer_id} for discipline {d.discipline_id} not found.")
            for tid in d.practice_teacher_ids:
                if tid not in teacher_ids:
                    self.errors.append(f"Practice teacher ID {tid} for discipline {d.discipline_id} not found.")
            for tid in d.lab_teacher_ids:
                if tid not in teacher_ids:
                    self.errors.append(f"Lab teacher ID {tid} for discipline {d.discipline_id} not found.")

    def _check_lessons(self):
        lessons = self.data['lessons']
        discipline_ids = {d.discipline_id for d in self.data['disciplines']}
        
        for l in lessons:
            if l.discipline_id not in discipline_ids:
                self.errors.append(f"Discipline ID {l.discipline_id} for lesson {l.lesson_number} ({l.lesson_type}) not found.")
