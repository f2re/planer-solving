import collections
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from ortools.sat.python import cp_model
from .model import (
    Teacher, TeacherUnavailability, Discipline, Lesson,
    Room, TimeSlot, CalendarEntry, ScheduleAssignment
)
from .constraints import ConstraintManager

class ScheduleSolver:
    def __init__(self, data: Dict[str, Any], config: Dict[str, Any]):
        self.data = data
        self.config = config
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        
        if 'solver_time_limit_seconds' in config:
            self.solver.parameters.max_time_in_seconds = config['solver_time_limit_seconds']
        
        self.variables = {}
        self.working_dates: List[CalendarEntry] = []
        self.all_slots: List[TimeSlot] = []
        self.lessons: List[Lesson] = []
        self.rooms: List[Room] = []
        self.teachers: List[Teacher] = []
        self.disciplines: Dict[int, Discipline] = {}
        
        self.room_to_idx: Dict[int, int] = {}
        self.teacher_to_idx: Dict[int, int] = {}
        
        self._preprocess_data()
        
    def _preprocess_data(self):
        calendar = self.data['calendar']
        self.working_dates = sorted(
            [entry for entry in calendar if entry.is_working_day and not entry.is_holiday],
            key=lambda x: x.date
        )
        self.all_slots = self.data['timeslots']
        self.lessons = self.data['lessons']
        self.rooms = self.data['rooms']
        self.teachers = self.data['teachers']
        self.disciplines = {d.discipline_id: d for d in self.data['disciplines']}
        
        self.room_to_idx = {r.room_id: i for i, r in enumerate(self.rooms)}
        self.teacher_to_idx = {t.teacher_id: i for i, t in enumerate(self.teachers)}

    def build_model(self):
        self.valid_global_slots = [] 
        for date_entry in self.working_dates:
            day_name = date_entry.date.strftime('%A')
            day_slots = sorted([s for s in self.all_slots if s.day_of_week == day_name], key=lambda s: s.slot_number)
            for slot in day_slots:
                self.valid_global_slots.append((date_entry.date, slot))
                
        self.num_global_slots = len(self.valid_global_slots)
        
        self.variables['lessons'] = {}
        for l_idx, lesson in enumerate(self.lessons):
            discipline = self.disciplines.get(lesson.discipline_id)
            if not discipline: continue
            
            duration_slots = (lesson.duration_minutes + 89) // 90
            if duration_slots < 1: duration_slots = 1
            
            start_var = self.model.NewIntVar(0, self.num_global_slots - duration_slots, f'start_{l_idx}')
            
            # Compatible Rooms
            comp_rooms = [r for r in self.rooms if r.capacity >= discipline.group_size and r.room_type == lesson.required_room_type]
            if not comp_rooms: comp_rooms = self.rooms 
            comp_room_indices = [self.room_to_idx[r.room_id] for r in comp_rooms]
            room_var = self.model.NewIntVarFromDomain(cp_model.Domain.FromValues(comp_room_indices), f'room_{l_idx}')
            
            # Compatible Teachers
            if lesson.lesson_type == 'lecture':
                allowed = [discipline.lecturer_id]
            elif lesson.lesson_type == 'practice':
                allowed = discipline.practice_teacher_ids
            elif lesson.lesson_type == 'lab':
                allowed = discipline.lab_teacher_ids
            else:
                allowed = [discipline.lecturer_id]
            
            valid_t_indices = [self.teacher_to_idx[tid] for tid in allowed if tid in self.teacher_to_idx]
            if not valid_t_indices: valid_t_indices = list(self.teacher_to_idx.values())
            teacher_var = self.model.NewIntVarFromDomain(cp_model.Domain.FromValues(valid_t_indices), f'teacher_{l_idx}')
            
            end_var = self.model.NewIntVar(0, self.num_global_slots, f'end_{l_idx}')
            interval_var = self.model.NewIntervalVar(start_var, duration_slots, end_var, f'interval_{l_idx}')
            
            self.variables['lessons'][l_idx] = {
                'start': start_var, 'end': end_var, 'room': room_var, 'teacher': teacher_var,
                'interval': interval_var, 'duration': duration_slots,
                'lesson': lesson, 'discipline': discipline,
                'compatible_rooms': comp_room_indices, 'compatible_teachers': valid_t_indices
            }

        self.constraints = ConstraintManager(self.model, self.variables, {
            'num_global_slots': self.num_global_slots,
            'valid_global_slots': self.valid_global_slots,
            'teacher_to_idx': self.teacher_to_idx,
            'room_to_idx': self.room_to_idx,
            'teacher_unavailability': self.data['teacher_unavailability'],
            'teachers': self.teachers,
            'rooms': self.rooms
        })
        self.constraints.add_hard_constraints()
        self.constraints.add_soft_constraints(self.config)

    def solve(self) -> List[ScheduleAssignment]:
        self.build_model()
        status = self.solver.Solve(self.model)
        
        self.config['stats'] = {
            'status': self.solver.StatusName(status),
            'objective_value': self.solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0,
            'solve_time': self.solver.WallTime(),
            'warnings': []
        }
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._extract_solution()
        return []

    def _extract_solution(self) -> List[ScheduleAssignment]:
        assignments = []
        for l_idx, vars in self.variables['lessons'].items():
            start_val = self.solver.Value(vars['start'])
            duration = vars['duration']
            room_idx = self.solver.Value(vars['room'])
            teacher_idx = self.solver.Value(vars['teacher'])
            
            date_obj, start_slot_obj = self.valid_global_slots[start_val]
            _, end_slot_obj = self.valid_global_slots[start_val + duration - 1]
            
            room = self.rooms[room_idx]
            teacher = self.teachers[teacher_idx]
            lesson = vars['lesson']
            discipline = vars['discipline']
            
            assignments.append(ScheduleAssignment(
                week_number=date_obj.isocalendar()[1],
                assignment_date=date_obj,
                day_of_week=start_slot_obj.day_of_week,
                start_time=start_slot_obj.start_time,
                end_time=end_slot_obj.end_time,
                slot_number=start_slot_obj.slot_number,
                discipline_name=discipline.discipline_name,
                lesson_type=lesson.lesson_type,
                topic=lesson.topic,
                group_name=discipline.group_name,
                teacher_name=teacher.full_name,
                room_name=room.room_name,
                building=room.building,
                lesson_id=f"{discipline.discipline_id}_{lesson.lesson_type}_{lesson.lesson_number}"
            ))
        return assignments
