import collections
from typing import List, Dict, Any, Tuple
from ortools.sat.python import cp_model

class ConstraintManager:
    def __init__(self, model: cp_model.CpModel, variables: Dict[str, Any], data: Dict[str, Any]):
        self.model = model
        self.variables = variables
        self.data = data
        self.objective_terms = []
        
        # Precompute day and week mappings
        self.valid_slots = self.data['valid_global_slots']
        self.day_to_slots = collections.defaultdict(list)
        self.week_to_slots = collections.defaultdict(list)
        self.slot_to_day = {}
        self.slot_to_week = {}
        self.day_to_week = {}
        
        curr_day_idx = -1
        curr_date = None
        for i, (date_obj, _) in enumerate(self.valid_slots):
            if date_obj != curr_date:
                curr_day_idx += 1
                curr_date = date_obj
                week_key = date_obj.isocalendar()[:2]
                self.day_to_week[curr_day_idx] = week_key
                
            self.day_to_slots[curr_day_idx].append(i)
            self.slot_to_day[i] = curr_day_idx
            
            week_key = date_obj.isocalendar()[:2]
            self.week_to_slots[week_key].append(i)
            self.slot_to_week[i] = week_key
            
        self.num_days = curr_day_idx + 1
        self.weeks = sorted(self.week_to_slots.keys())

    def add_hard_constraints(self):
        self._add_resource_no_overlap_constraints()
        self._add_day_integrity_constraints()
        self._add_teacher_availability_constraints()
        self._add_teacher_load_constraints()

    def add_soft_constraints(self, config: Dict[str, Any]):
        soft_cfg = config.get("soft_constraints", {})
        
        if soft_cfg.get("avoid_late_slots", {}).get("enabled"):
            weight = soft_cfg["avoid_late_slots"]["weight"]
            for l_idx, vars in self.variables['lessons'].items():
                # Prefer earlier slots: minimize global start
                self.objective_terms.append(vars['start'] * (-weight))

        if soft_cfg.get("minimize_student_gaps", {}).get("enabled"):
            self._add_minimize_gaps_constraints(
                "group", 
                soft_cfg["minimize_student_gaps"]["weight"]
            )

        if soft_cfg.get("minimize_teacher_gaps", {}).get("enabled"):
            self._add_minimize_gaps_constraints(
                "teacher", 
                soft_cfg["minimize_teacher_gaps"]["weight"]
            )

        if soft_cfg.get("balance_workload", {}).get("enabled"):
            self._add_balance_workload_constraints(
                soft_cfg["balance_workload"]["weight"]
            )

        if soft_cfg.get("group_consecutive_lessons", {}).get("enabled"):
            self._add_consecutive_lessons_constraints(
                soft_cfg["group_consecutive_lessons"]["weight"]
            )

        if soft_cfg.get("minimize_building_transitions", {}).get("enabled"):
            self._add_building_transition_constraints(
                soft_cfg["minimize_building_transitions"]["weight"]
            )

        if soft_cfg.get("teacher_seniority_priority", {}).get("enabled"):
            self._add_seniority_priority_constraints(
                soft_cfg["teacher_seniority_priority"]["weight"]
            )
        
        if self.objective_terms:
            self.model.Maximize(sum(self.objective_terms))

    def _add_resource_no_overlap_constraints(self):
        room_intervals = collections.defaultdict(list)
        teacher_intervals = collections.defaultdict(list)
        group_intervals = collections.defaultdict(list)
        
        for l_idx, vars in self.variables['lessons'].items():
            start, duration, end = vars['start'], vars['duration'], vars['end']
            discipline = vars['discipline']
            
            vars['room_bools'] = {}
            for r_idx in vars['compatible_rooms']:
                presence = self.model.NewBoolVar(f'l{l_idx}_r{r_idx}')
                self.model.Add(vars['room'] == r_idx).OnlyEnforceIf(presence)
                self.model.Add(vars['room'] != r_idx).OnlyEnforceIf(presence.Not())
                vars['room_bools'][r_idx] = presence
                room_intervals[r_idx].append(self.model.NewOptionalIntervalVar(start, duration, end, presence, f'l{l_idx}_r{r_idx}_int'))
                
            vars['teacher_bools'] = {}
            for t_idx in vars['compatible_teachers']:
                presence = self.model.NewBoolVar(f'l{l_idx}_t{t_idx}')
                self.model.Add(vars['teacher'] == t_idx).OnlyEnforceIf(presence)
                self.model.Add(vars['teacher'] != t_idx).OnlyEnforceIf(presence.Not())
                vars['teacher_bools'][t_idx] = presence
                teacher_intervals[t_idx].append(self.model.NewOptionalIntervalVar(start, duration, end, presence, f'l{l_idx}_t{t_idx}_int'))
                
            group_intervals[discipline.group_name].append(vars['interval'])

        for intervals in room_intervals.values(): self.model.AddNoOverlap(intervals)
        for intervals in teacher_intervals.values(): self.model.AddNoOverlap(intervals)
        for intervals in group_intervals.values(): self.model.AddNoOverlap(intervals)

    def _add_day_integrity_constraints(self):
        for l_idx, vars in self.variables['lessons'].items():
            start, end = vars['start'], vars['end']
            day_bools = []
            for d_idx in range(self.num_days):
                d_slots = self.day_to_slots[d_idx]
                in_day = self.model.NewBoolVar(f'l{l_idx}_d{d_idx}')
                self.model.Add(start >= min(d_slots)).OnlyEnforceIf(in_day)
                self.model.Add(end <= max(d_slots) + 1).OnlyEnforceIf(in_day)
                day_bools.append(in_day)
            self.model.AddExactlyOne(day_bools)
            vars['day_bools'] = day_bools

    def _add_teacher_availability_constraints(self):
        valid_slots = self.data['valid_global_slots']
        for unav in self.data['teacher_unavailability']:
            t_idx = self.data['teacher_to_idx'].get(unav.teacher_id)
            if t_idx is None: continue
            
            for i, (date_obj, slot_obj) in enumerate(valid_slots):
                is_unavail = False
                if unav.start_date and unav.end_date:
                    if unav.start_date <= date_obj <= unav.end_date:
                        is_unavail = True
                if unav.unavailable_days:
                    if date_obj.strftime('%A') in unav.unavailable_days:
                        is_unavail = True
                
                if is_unavail:
                    for l_idx, vars in self.variables['lessons'].items():
                        if t_idx in vars['teacher_bools']:
                            presence = vars['teacher_bools'][t_idx]
                            b1 = self.model.NewBoolVar(f'l{l_idx}_t{t_idx}_i{i}_b1')
                            b2 = self.model.NewBoolVar(f'l{l_idx}_t{t_idx}_i{i}_b2')
                            self.model.Add(i < vars['start']).OnlyEnforceIf(b1)
                            self.model.Add(i >= vars['end']).OnlyEnforceIf(b2)
                            self.model.Add(b1 + b2 >= 1).OnlyEnforceIf(presence)

    def _add_teacher_load_constraints(self):
        for t_idx, teacher in enumerate(self.data['teachers']):
            max_slots = (teacher.max_hours_per_week * 60) // 90
            for w_key in self.weeks:
                weekly_lessons = []
                days_in_week = [d for d, wk in self.day_to_week.items() if wk == w_key]
                for l_idx, vars in self.variables['lessons'].items():
                    if t_idx in vars['teacher_bools']:
                        in_week = self.model.NewBoolVar(f'l{l_idx}_w{w_key}')
                        self.model.Add(in_week == sum(vars['day_bools'][d] for d in days_in_week))
                        
                        presence_in_week = self.model.NewBoolVar(f'l{l_idx}_t{t_idx}_w{w_key}')
                        self.model.AddMultiplicationEquality(presence_in_week, [in_week, vars['teacher_bools'][t_idx]])
                        weekly_lessons.append(presence_in_week * vars['duration'])
                
                if weekly_lessons:
                    self.model.Add(sum(weekly_lessons) <= max_slots)

    def _add_minimize_gaps_constraints(self, entity_type: str, weight: int):
        entities = []
        if entity_type == "group":
            entities = sorted(list(set(v['discipline'].group_name for v in self.variables['lessons'].values())))
        else:
            entities = range(len(self.data['teachers']))

        for entity in entities:
            for d_idx in range(self.num_days):
                relevant_lessons = []
                for l_idx, vars in self.variables['lessons'].items():
                    is_relevant = False
                    if entity_type == "group":
                        if vars['discipline'].group_name == entity:
                            is_relevant = True
                    else:
                        if entity in vars['teacher_bools']:
                            is_relevant = True
                    
                    if is_relevant:
                        presence = vars['day_bools'][d_idx]
                        if entity_type == "teacher":
                            p2 = self.model.NewBoolVar(f'l{l_idx}_t{entity}_d{d_idx}')
                            self.model.AddMultiplicationEquality(p2, [presence, vars['teacher_bools'][entity]])
                            presence = p2
                        relevant_lessons.append((l_idx, vars, presence))
                
                if not relevant_lessons: continue
                
                day_start = min(self.day_to_slots[d_idx])
                day_end = max(self.day_to_slots[d_idx]) + 1
                M = day_end - day_start
                
                first = self.model.NewIntVar(day_start, day_end, f'{entity_type}_{entity}_d{d_idx}_first')
                last = self.model.NewIntVar(day_start, day_end, f'{entity_type}_{entity}_d{d_idx}_last')
                
                for l_idx, vars, presence in relevant_lessons:
                    self.model.Add(first <= vars['start'] + M * (1 - presence))
                    self.model.Add(last >= vars['end'] - M * (1 - presence))
                
                any_lesson = self.model.NewBoolVar(f'{entity_type}_{entity}_d{d_idx}_any')
                self.model.Add(any_lesson == (sum(p for _, _, p in relevant_lessons) >= 1))
                
                total_duration = self.model.NewIntVar(0, M, f'{entity_type}_{entity}_d{d_idx}_dur')
                self.model.Add(total_duration == sum(p * v['duration'] for _, v, p in relevant_lessons))
                
                span = self.model.NewIntVar(0, M, f'{entity_type}_{entity}_d{d_idx}_span')
                self.model.Add(span >= last - first).OnlyEnforceIf(any_lesson)
                self.model.Add(span == 0).OnlyEnforceIf(any_lesson.Not())
                
                gap = self.model.NewIntVar(0, M, f'{entity_type}_{entity}_d{d_idx}_gap')
                self.model.Add(gap == span - total_duration).OnlyEnforceIf(any_lesson)
                self.model.Add(gap == 0).OnlyEnforceIf(any_lesson.Not())
                
                self.objective_terms.append(gap * (-weight))

    def _add_balance_workload_constraints(self, weight: int):
        groups = sorted(list(set(v['discipline'].group_name for v in self.variables['lessons'].values())))
        for group in groups:
            max_daily_slots = self.model.NewIntVar(0, 10, f'max_daily_slots_{group}')
            for d_idx in range(self.num_days):
                daily_slots = sum(v['duration'] * v['day_bools'][d_idx] 
                                  for v in self.variables['lessons'].values() 
                                  if v['discipline'].group_name == group)
                self.model.Add(max_daily_slots >= daily_slots)
            self.objective_terms.append(max_daily_slots * (-weight))

    def _add_consecutive_lessons_constraints(self, weight: int):
        # Rely on gap minimization for now, as it pushes lessons together.
        pass

    def _add_building_transition_constraints(self, weight: int):
        buildings = sorted(list(set(r.building for r in self.data['rooms'])))
        building_to_idx = {b: i for i, b in enumerate(buildings)}
        room_to_building = [0] * len(self.data['rooms'])
        for r_idx, room in enumerate(self.data['rooms']):
            room_to_building[r_idx] = building_to_idx[room.building]
            
        for l_idx, vars in self.variables['lessons'].items():
            b_var = self.model.NewIntVar(0, len(buildings) - 1, f'l{l_idx}_building')
            self.model.AddElement(vars['room'], room_to_building, b_var)
            vars['building_var'] = b_var

        for t_idx in range(len(self.data['teachers'])):
            for d_idx in range(self.num_days):
                teacher_day_lessons = []
                for l_idx, vars in self.variables['lessons'].items():
                    if t_idx in vars['teacher_bools']:
                        p = self.model.NewBoolVar(f'l{l_idx}_t{t_idx}_d{d_idx}_b')
                        self.model.AddMultiplicationEquality(p, [vars['day_bools'][d_idx], vars['teacher_bools'][t_idx]])
                        teacher_day_lessons.append((vars['building_var'], p))
                
                if len(teacher_day_lessons) < 2: continue
                
                for i in range(len(teacher_day_lessons)):
                    for j in range(i + 1, len(teacher_day_lessons)):
                        b1, p1 = teacher_day_lessons[i]
                        b2, p2 = teacher_day_lessons[j]
                        both_present = self.model.NewBoolVar(f't{t_idx}_d{d_idx}_l{i}_l{j}_both')
                        self.model.AddMultiplicationEquality(both_present, [p1, p2])
                        
                        diff_building = self.model.NewBoolVar(f't{t_idx}_d{d_idx}_l{i}_l{j}_diff')
                        self.model.Add(b1 != b2).OnlyEnforceIf(diff_building)
                        self.model.Add(b1 == b2).OnlyEnforceIf(diff_building.Not())
                        
                        penalty = self.model.NewBoolVar(f't{t_idx}_d{d_idx}_l{i}_l{j}_penalty')
                        self.model.AddMultiplicationEquality(penalty, [both_present, diff_building])
                        self.objective_terms.append(penalty * (-weight))

    def _add_seniority_priority_constraints(self, weight: int):
        for l_idx, vars in self.variables['lessons'].items():
            for t_idx, t_bool in vars['teacher_bools'].items():
                teacher = self.data['teachers'][t_idx]
                seniority = teacher.seniority
                # Reward earlier slots for senior teachers. 
                # Use a bool product to only apply when teacher is assigned.
                # seniority * weight * (max_slots - start)
                # But start is global. 
                # simpler: penalty = seniority * weight * start
                term = self.model.NewIntVar(0, 1000000, f'l{l_idx}_t{t_idx}_seniority')
                self.model.AddMultiplicationEquality(term, [t_bool, vars['start']])
                self.objective_terms.append(term * (-weight * seniority))