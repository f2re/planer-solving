import json
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class Lesson:
    group: str
    subject: str
    lesson_type_code: str  # e.g., Л/Т.01
    room: str
    week: int
    day_of_week: str  # Пн, Вт, ...
    pair_num: int     # 1, 2, 3, 4 (where 1 is 9:00-10:35, etc.)
    teacher: str

class DataLoader:
    def __init__(self, teachers_config_path: str):
        with open(teachers_config_path, 'r', encoding='utf-8') as f:
            self.teachers_config = json.load(f)
        self.teacher_names = [t['short_name'] for t in self.teachers_config]
        
    def load_group_schedule(self, file_path: str) -> List[Lesson]:
        file_path = Path(file_path)
        group_name = file_path.stem
        
        # Load the whole sheet
        df = pd.read_excel(file_path, header=None)
        
        # 1. Parse Calendar (Weeks)
        # Row 4 (index 4) contains week numbers starting from col 3
        weeks = {}
        for col in range(3, df.shape[1]):
            val = df.iloc[4, col]
            if pd.notna(val) and isinstance(val, (int, float)):
                weeks[col] = int(val)
        
        # 2. Parse Teacher Mapping from the bottom
        # Look for "Обозн" in column 0 to find the start of the table
        mapping_start_idx = df[df[0] == "Обозн"].index
        teacher_mapping = {}
        if not mapping_start_idx.empty:
            idx = mapping_start_idx[0] + 3 # Skip header rows
            while idx < len(df) and pd.notna(df.iloc[idx, 0]):
                abbr = str(df.iloc[idx, 0]).strip()
                lecturer = str(df.iloc[idx, 9]) if pd.notna(df.iloc[idx, 9]) else ""
                others = str(df.iloc[idx, 13]) if pd.notna(df.iloc[idx, 13]) else ""
                
                teacher_mapping[abbr] = {
                    'Л': self._extract_teachers(lecturer),
                    'П': self._extract_teachers(others),
                    'С': self._extract_teachers(others),
                    'У': self._extract_teachers(others),
                    'ЛР': self._extract_teachers(others),
                    'ЗО': self._extract_teachers(others),
                    'Экз': self._extract_teachers(others),
                }
                idx += 1

        # 3. Parse Schedule Grid
        lessons = []
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
        # Monday starts at row 7. Each day has 4 pairs, each pair is 3 rows.
        # Day blocks are separated by a "Даты" row (like row 19)
        
        current_row = 7
        for day in days:
            # Check if this row is indeed a day start (has day name or we just follow the pattern)
            for pair_idx in range(1, 5): # 4 pairs per day
                for col_idx, week_num in weeks.items():
                    # Lesson data is in 3 rows
                    code = df.iloc[current_row, col_idx]
                    subj = df.iloc[current_row + 1, col_idx]
                    room = df.iloc[current_row + 2, col_idx]
                    
                    if pd.notna(code) and pd.notna(subj):
                        code = str(code).strip()
                        subj = str(subj).strip()
                        room = str(room).strip() if pd.notna(room) else ""
                        
                        # Determine teacher
                        lesson_type = 'Л' if code.startswith('Л/') else 'П'
                        potential_teachers = teacher_mapping.get(subj, {}).get(lesson_type, [])
                        
                        # If there's only one teacher from our config, use them.
                        # If multiple, it's ambiguous, but let's take the first one found in config for now.
                        assigned_teacher = "Unknown"
                        for pt in potential_teachers:
                            if pt in self.teacher_names:
                                assigned_teacher = pt
                                break
                        
                        lessons.append(Lesson(
                            group=group_name,
                            subject=subj,
                            lesson_type_code=code,
                            room=room,
                            week=week_num,
                            day_of_week=day,
                            pair_num=pair_idx,
                            teacher=assigned_teacher
                        ))
                current_row += 3
            current_row += 1 # Skip the "Даты" row
            
        return lessons

    def _extract_teachers(self, text: str) -> List[str]:
        # Simple extraction: look for names from the config in the text
        found = []
        for name in self.teacher_names:
            if name in text:
                found.append(name)
        return found

if __name__ == "__main__":
    # Test loading
    import os
    base_path = "/home/YaremenkoIA/planner-solving"
    loader = DataLoader(os.path.join(base_path, "teachers.json"))
    sample_file = os.path.join(base_path, "obrazec/522.xlsx")
    if os.path.exists(sample_file):
        lessons = loader.load_group_schedule(sample_file)
        print(f"Loaded {len(lessons)} lessons from {sample_file}")
        for l in lessons[:5]:
            print(l)
