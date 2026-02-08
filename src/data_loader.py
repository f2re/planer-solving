import json
import pandas as pd
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional
import numpy as np

@dataclass
class Lesson:
    group: str
    subject: str
    lesson_type_code: str  # e.g., Л/Т.01
    room: str
    week: int
    day_of_week: str  # Пн, Вт, ...
    pair_num: int     # 1, 2, 3, 4
    teacher: str
    date_day: int
    month: str
    semester_info: str = ""
    year_info: str = ""

class DataLoader:
    def __init__(self, teachers_config_path: str):
        with open(teachers_config_path, 'r', encoding='utf-8') as f:
            self.teachers_config = json.load(f)
        
        # Group teachers by surname to handle same-surname cases
        self.teachers_by_surname = {}
        for t in self.teachers_config:
            full_name_parts = t['full_name'].split()
            surname = full_name_parts[0].lower()
            if surname not in self.teachers_by_surname:
                self.teachers_by_surname[surname] = []
            
            # Prepare precise pattern (surname + initials)
            precise_patterns = []
            if len(full_name_parts) >= 3:
                i1 = full_name_parts[1][0]
                i2 = full_name_parts[2][0]
                # Pattern for "Surname I.I." or "I.I. Surname"
                precise_patterns.append(rf"{surname}\s+{i1}\.?\s*{i2}\.?")
                precise_patterns.append(rf"{i1}\.?\s*{i2}\.?\s+{surname}")
            
            self.teachers_by_surname[surname].append({
                'short_name': t['short_name'],
                'surname': surname,
                'precise_pattern': re.compile("|".join(precise_patterns), re.IGNORECASE) if precise_patterns else None
            })

    def _extract_teachers(self, text: str) -> List[str]:
        found = []
        text_lower = text.lower()
        
        for surname, variations in self.teachers_by_surname.items():
            # 1. Check if surname exists in text at all
            if re.search(rf"\b{surname}\b", text_lower):
                # 2. Try precise match for each variation
                matched_variations = []
                for v in variations:
                    if v['precise_pattern'] and v['precise_pattern'].search(text):
                        matched_variations.append(v['short_name'])
                
                if matched_variations:
                    # Found specific teacher(s) with initials
                    found.extend(matched_variations)
                elif len(variations) == 1:
                    # Only one teacher with this surname in config, 
                    # and no initials found in text for anyone with this surname.
                    # Assume it's this one (handles "Иванов, доц")
                    found.append(variations[0]['short_name'])
                else:
                    # Multiple teachers with same surname, but no matching initials found in text
                    # Ambiguous - don't match any to avoid wrong assignment
                    pass
                    
        return found

    def _find_structure(self, df):
        # Look for "week" row
        weeks_row_idx = None
        week_start_col = None
        
        # Scan first 20 rows
        for r in range(min(20, len(df))):
            # Check for text marker in first few columns
            row_vals = [str(x).lower().strip() for x in df.iloc[r, :5] if pd.notna(x)]
            if any(('уч.недели' in x or 'уч. недели' in x) for x in row_vals):
                weeks_row_idx = r
                # Find where numbers start
                for c in range(2, df.shape[1]):
                    val = df.iloc[r, c]
                    # Check for integer 1 (start of weeks)
                    if (pd.notna(val) and isinstance(val, (int, float)) and int(val) == 1):
                        week_start_col = c
                        break
                if week_start_col is not None:
                    break
        
        if weeks_row_idx is None:
            # Fallback: look for 1, 2, 3 sequence
            for r in range(min(20, len(df))):
                for c in range(1, 10):
                    try:
                        v1 = df.iloc[r, c]
                        v2 = df.iloc[r, c+1]
                        if (pd.notna(v1) and isinstance(v1, (int, float)) and int(v1) == 1 and 
                            pd.notna(v2) and isinstance(v2, (int, float)) and int(v2) == 2):
                            weeks_row_idx = r
                            week_start_col = c
                            break
                    except IndexError:
                        continue
                if weeks_row_idx is not None:
                    break
                    
        return weeks_row_idx, week_start_col

    def load_group_schedule(self, file_path: str, group_name: Optional[str] = None) -> List[Lesson]:
        file_path = Path(file_path)
        if group_name is None: group_name = file_path.stem
        
        # Load the whole sheet
        df = pd.read_excel(file_path, header=None)
        
        # 0. Extract Semester and Year info (try first few rows)
        semester_text = ""
        year_text = ""
        for r in range(3):
            val = str(df.iloc[r, 0]).strip() if pd.notna(df.iloc[r, 0]) else ""
            if "семестр" in val.lower():
                semester_text = val
            if "год" in val.lower():
                year_text = val

        # 1. Parse Calendar (Weeks and Months)
        weeks_row_idx, week_start_col = self._find_structure(df)
        
        if weeks_row_idx is None or week_start_col is None:
            raise ValueError("Could not find schedule structure (weeks row)")

        weeks = {}
        for col in range(week_start_col, df.shape[1]):
            val = df.iloc[weeks_row_idx, col]
            if pd.notna(val) and isinstance(val, (int, float)):
                weeks[col] = int(val)
        
        # Months are typically 1 row below weeks
        months_row_idx = weeks_row_idx + 1
        months_row = df.iloc[months_row_idx, week_start_col:].ffill()
        months = {week_start_col + i: val for i, val in enumerate(months_row)}
        
        # 2. Parse Teacher Mapping from the bottom
        # Look for "Обозн" anywhere in column 0
        mapping_start_idx = df[df[0] == 'Обозн'].index
        teacher_mapping = {}
        if not mapping_start_idx.empty:
            idx = mapping_start_idx[0] + 3 # Skip header rows
            while idx < len(df) and pd.notna(df.iloc[idx, 0]):
                abbr = str(df.iloc[idx, 0]).strip()
                lecturer_text = str(df.iloc[idx, 9]) if pd.notna(df.iloc[idx, 9]) else ''
                others_text = str(df.iloc[idx, 13]) if pd.notna(df.iloc[idx, 13]) else ''
                
                teacher_mapping[abbr] = {
                    'Л': self._extract_teachers(lecturer_text),
                    'П': self._extract_teachers(others_text),
                    'С': self._extract_teachers(others_text),
                    'У': self._extract_teachers(others_text),
                    'ЛР': self._extract_teachers(others_text),
                    'ЗО': self._extract_teachers(others_text),
                    'Экз': self._extract_teachers(others_text),
                }
                idx += 1

        # 3. Parse Schedule Grid
        lessons = []
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
        
        # Grid typically starts 3 rows below weeks row (weeks, months, dates, GRID)
        grid_start_row = weeks_row_idx + 3
        
        for day_idx, day in enumerate(days):
            base_row = grid_start_row + day_idx * 13
            
            # Ensure we don't go out of bounds
            if base_row >= len(df):
                break

            day_dates = {}
            # Date row for this day is usually 1 row above grid block
            date_row = base_row - 1
            for col_idx in weeks.keys():
                date_val = df.iloc[date_row, col_idx]
                # Handle Excel dates (int or datetime)
                if pd.notna(date_val):
                     # If it's a datetime object, extract day
                    if hasattr(date_val, 'day'):
                        day_dates[col_idx] = date_val.day
                    else:
                        try:
                            day_dates[col_idx] = int(date_val)
                        except:
                            pass

            for pair_idx in range(1, 5): # 4 pairs per day
                pair_row = base_row + (pair_idx - 1) * 3
                
                if pair_row + 2 >= len(df): continue

                for col_idx, week_num in weeks.items():
                    code = df.iloc[pair_row, col_idx]
                    subj_abbr = df.iloc[pair_row + 1, col_idx]
                    room = df.iloc[pair_row + 2, col_idx]
                    
                    if pd.notna(code) and pd.notna(subj_abbr):
                        code = str(code).strip()
                        subj_abbr = str(subj_abbr).strip()
                        room = str(room).strip() if pd.notna(room) else ''
                        
                        # Determine teacher
                        lesson_type = 'Л' if code.startswith('Л/') else 'П'
                        if '/' in code:
                            lesson_type_part = code.split('/')[0]
                            if lesson_type_part in teacher_mapping.get(subj_abbr, {}):
                                lesson_type = lesson_type_part

                        potential_teachers = teacher_mapping.get(subj_abbr, {}).get(lesson_type, [])
                        
                        assigned_teacher = potential_teachers[0] if potential_teachers else 'Unknown'
                        
                        lessons.append(Lesson(
                            group=group_name,
                            subject=subj_abbr,
                            lesson_type_code=code,
                            room=room,
                            week=week_num,
                            day_of_week=day,
                            pair_num=pair_idx,
                            teacher=assigned_teacher,
                            date_day=day_dates.get(col_idx, 0),
                            month=months.get(col_idx, 'Unknown'),
                            semester_info=semester_text,
                            year_info=year_text
                        ))
            
        return lessons

if __name__ == '__main__':
    import os
    base_path = '~/planner-solving'
    loader = DataLoader(os.path.join(base_path, 'teachers.json'))
    sample_file = os.path.join(base_path, 'obrazec/522.xlsx')
    if os.path.exists(sample_file):
        lessons = loader.load_group_schedule(sample_file)
        print(f'Loaded {len(lessons)} lessons from {sample_file}')
        for l in lessons[:5]:
            print(l)