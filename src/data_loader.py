import json
import pandas as pd
import re
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Set
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Lesson:
    """Represents a single lesson in the schedule."""
    group: str
    subject: str
    lesson_type_code: str  # e.g., Л/Т.01, П/Т.02
    room: str
    week: int
    day_of_week: str      # Пн, Вт, Ср, Чт, Пт, Сб
    pair_num: int        # 1, 2, 3, 4
    teacher: str         # Full name or abbreviation from config
    date_day: int        # Day of month
    month: str           # Month name
    semester_info: str = ""
    year_info: str = ""

class DataLoader:
    """
    Loads schedule data from Excel files and manages teacher assignments.
    Implements smart teacher distribution including Round-Robin and occupancy tracking.
    """
    def __init__(self, teachers_config_path: str):
        """
        Initializes the DataLoader with teacher configurations.
        
        Args:
            teachers_config_path: Path to the JSON file containing teacher information.
        """
        try:
            with open(teachers_config_path, 'r', encoding='utf-8') as f:
                self.teachers_config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load teachers config from {teachers_config_path}: {e}")
            self.teachers_config = []
        
        # Global state for smart teacher distribution
        # Maps (week, day, pair, teacher) -> subject_abbreviation
        self.occupancy: Dict[tuple, str] = {}  
        
        # List of conflict warnings to show to the user
        self.warnings: List[str] = []
        
        # Maps (subject_abbreviation, lesson_type) -> last_teacher_index (for Round-Robin)
        self.subject_counters: Dict[tuple, int] = {}  
        
        # Index teachers for efficient lookup
        self.teachers_by_surname = {}
        for t in self.teachers_config:
            full_name_parts = t['full_name'].split()
            if not full_name_parts:
                continue
                
            surname = full_name_parts[0].lower()
            if surname not in self.teachers_by_surname:
                self.teachers_by_surname[surname] = []
            
            # Prepare precise patterns (surname + initials)
            precise_patterns = []
            if len(full_name_parts) >= 3:
                s = full_name_parts[0]
                i1 = full_name_parts[1][0]
                i2 = full_name_parts[2][0]
                # Patterns like "Ivanov I.I.", "I.I. Ivanov", "Ivanov I. I."
                patterns = [
                    rf"{s}\s+{i1}\.?\s*{i2}\.?",
                    rf"{i1}\.?\s*{i2}\.?\s+{s}",
                    rf"{s}\s+{i1}\.?{i2}\.?",
                ]
                precise_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
            
            self.teachers_by_surname[surname].append({
                'short_name': t['short_name'],
                'full_name': t['full_name'],
                'surname': surname,
                'patterns': precise_patterns
            })

    def _assign_teacher(self, week: int, day: str, pair: int, subj_abbr: str, 
                        lesson_type: str, potential_teachers: List[str]) -> str:
        """
        Assigns a teacher based on Round-Robin distribution and availability.
        
        Args:
            week: Week number.
            day: Day of week (Пн, Вт, ...).
            pair: Pair number (1-4).
            subj_abbr: Subject abbreviation.
            lesson_type: Lesson type (Л, П, etc.).
            potential_teachers: List of teachers available for this subject and type.
            
        Returns:
            The name of the assigned teacher or "Unknown".
        """
        if not potential_teachers:
            return "Unknown"
        
        # Remove duplicates while preserving order
        unique_potential = []
        seen = set()
        for t in potential_teachers:
            if t not in seen:
                unique_potential.append(t)
                seen.add(t)
        
        # 1. Check for existing assignment (Combined Lectures)
        # If any of the potential teachers is already teaching THIS subject at THIS time,
        # it's likely a combined lecture. Return that teacher.
        for teacher in unique_potential:
            occupancy_key = (week, day, pair, teacher)
            if self.occupancy.get(occupancy_key) == subj_abbr:
                return teacher
        
        # 2. Round-Robin with conflict avoidance
        # Try to find a teacher who is not busy at this time.
        counter_key = (subj_abbr, lesson_type)
        start_idx = self.subject_counters.get(counter_key, 0)
        num_teachers = len(unique_potential)
        
        for i in range(num_teachers):
            idx = (start_idx + i) % num_teachers
            teacher = unique_potential[idx]
            
            occupancy_key = (week, day, pair, teacher)
            if occupancy_key not in self.occupancy:
                # Teacher is available. Mark as occupied and update Round-Robin counter.
                self.occupancy[occupancy_key] = subj_abbr
                self.subject_counters[counter_key] = (idx + 1) % num_teachers
                return teacher
        
        # 3. Fallback: If all potential teachers are busy with OTHER subjects
        # We assign the next one in Round-Robin order anyway, which indicates a conflict.
        chosen_idx = start_idx % num_teachers
        teacher = unique_potential[chosen_idx]
        
        # Update counter to maintain distribution balance even when conflicts occur
        self.subject_counters[counter_key] = (chosen_idx + 1) % num_teachers
        
        conflict_msg = (f"Конфликт: {teacher} уже занят на {self.occupancy[occupancy_key]} "
                       f"(Неделя {week}, {day}, {pair} пара). "
                       f"Добавлено второе занятие: {subj_abbr} ({lesson_type}).")
        self.warnings.append(conflict_msg)
        logger.warning(conflict_msg)
        
        return teacher

    def _extract_teachers(self, text: str) -> List[str]:
        """
        Extracts teacher names from a text string based on the configuration.
        """
        if not text or pd.isna(text):
            return []
            
        found = []
        text_lower = text.lower()
        
        # Search for each surname in the config
        for surname, variations in self.teachers_by_surname.items():
            if re.search(rf"\b{surname}\b", text_lower):
                # Try to find a specific variation with initials
                matched_variations = []
                for v in variations:
                    if any(p.search(text) for p in v['patterns']):
                        matched_variations.append(v['short_name'])
                
                if matched_variations:
                    found.extend(matched_variations)
                elif len(variations) == 1:
                    # Surname found and there's only one teacher with this surname in config
                    found.append(variations[0]['short_name'])
                else:
                    # Ambiguous case: multiple teachers with same surname but no initials matched
                    pass
                    
        return found

    def _find_structure(self, df: pd.DataFrame):
        """
        Locates the weeks row and the column where the schedule grid begins.
        """
        weeks_row_idx = None
        week_start_col = None
        
        # Scan first 20 rows for "уч.недели" or "уч. недели"
        for r in range(min(20, len(df))):
            row_vals = [str(x).lower().strip() for x in df.iloc[r, :5] if pd.notna(x)]
            if any(('уч.недели' in x or 'уч. недели' in x) for x in row_vals):
                weeks_row_idx = r
                # Find the column where numeric week numbers start (1, 2, 3...)
                for c in range(2, df.shape[1]):
                    val = df.iloc[r, c]
                    if pd.notna(val) and isinstance(val, (int, float)) and int(val) == 1:
                        week_start_col = c
                        break
                if week_start_col is not None:
                    break
        
        # Fallback: look for a sequence of 1, 2, 3 in a row
        if weeks_row_idx is None:
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
                    except (IndexError, KeyError):
                        continue
                if weeks_row_idx is not None:
                    break
                    
        return weeks_row_idx, week_start_col

    def load_group_schedule(self, file_path: str, group_name: Optional[str] = None) -> List[Lesson]:
        """
        Parses an Excel file for a specific group's schedule.
        """
        file_path = Path(file_path)
        if group_name is None:
            group_name = file_path.stem
        
        logger.info(f"Loading schedule from {file_path} for group {group_name}")
        
        try:
            df = pd.read_excel(file_path, header=None)
        except Exception as e:
            logger.error(f"Error reading Excel file {file_path}: {e}")
            return []
        
        # 1. Metadata: Semester and Year
        semester_text = ""
        year_text = ""
        for r in range(3):
            val = str(df.iloc[r, 0]).strip() if pd.notna(df.iloc[r, 0]) else ""
            if "семестр" in val.lower():
                semester_text = val
            if "год" in val.lower():
                year_text = val

        # 2. Schedule Grid Structure
        weeks_row_idx, week_start_col = self._find_structure(df)
        if weeks_row_idx is None or week_start_col is None:
            logger.error(f"Could not find schedule structure in {file_path}")
            return []

        # Map column index to week number
        weeks_map = {}
        for col in range(week_start_col, df.shape[1]):
            val = df.iloc[weeks_row_idx, col]
            if pd.notna(val) and isinstance(val, (int, float)):
                weeks_map[col] = int(val)
        
        # Map column index to month name (usually row below weeks)
        months_row_idx = weeks_row_idx + 1
        
        # Normalize and ffill months
        current_month = "Unknown"
        months_map = {}
        
        # Month name dictionary for normalization
        month_names_ru = {
            'янв': 'Январь', 'фев': 'Февраль', 'мар': 'Март', 'апр': 'Апрель', 
            'май': 'Май', 'июн': 'Июнь', 'июл': 'Июль', 'авг': 'Август',
            'сен': 'Сентябрь', 'окт': 'Октябрь', 'ноя': 'Ноябрь', 'дек': 'Декабрь'
        }

        # Scan the entire row to handle merged cells starting before week_start_col
        months_row_full = df.iloc[months_row_idx, :]
        for col_idx, val in enumerate(months_row_full):
            if pd.notna(val):
                val_str = str(val).strip().lower()
                # Try to match starting prefix
                found = False
                for prefix, full_name in month_names_ru.items():
                    if val_str.startswith(prefix):
                        current_month = full_name
                        found = True
                        break
                if not found:
                    # Fallback to original but capitalized
                    current_month = val_str.capitalize()
            
            if col_idx >= week_start_col:
                months_map[col_idx] = current_month
        
        # 3. Teacher Mapping from the legend (usually at the bottom)
        teacher_mapping = {}
        # Search for 'Обозн' marker
        mapping_start_idx_list = df[df[0] == 'Обозн'].index
        if not mapping_start_idx_list.empty:
            header_idx = mapping_start_idx_list[0]
            header_row = df.iloc[header_idx, :]
            
            # Find columns for Lecturer and Others
            lecturer_col = 9  # Default
            others_col = 13   # Default
            
            for c_idx, val in enumerate(header_row):
                if pd.notna(val):
                    val_str = str(val).lower()
                    if 'лектор' in val_str:
                        lecturer_col = c_idx
                    elif 'другие' in val_str:
                        others_col = c_idx
            
            idx = header_idx + 3 # Skip header lines
            while idx < len(df) and pd.notna(df.iloc[idx, 0]):
                abbr = str(df.iloc[idx, 0]).strip()
                lecturer_text = str(df.iloc[idx, lecturer_col]) if pd.notna(df.iloc[idx, lecturer_col]) else ''
                others_text = str(df.iloc[idx, others_col]) if pd.notna(df.iloc[idx, others_col]) else ''
                
                # Expand mapping for all lesson types
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

        # 4. Parse Lessons from the grid
        lessons = []
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
        grid_start_row = weeks_row_idx + 3
        
        for day_idx, day_name in enumerate(days):
            base_row = grid_start_row + day_idx * 13 # Each day has 13 rows in the template
            
            if base_row >= len(df):
                break

            # Dates for this day
            day_dates = {}
            date_row = base_row - 1
            if date_row < len(df):
                for col_idx in weeks_map.keys():
                    date_val = df.iloc[date_row, col_idx]
                    if pd.notna(date_val):
                        if hasattr(date_val, 'day'):
                            day_dates[col_idx] = date_val.day
                        else:
                            # Try to extract number from string (e.g., "02.09" -> 2)
                            date_str = str(date_val).strip()
                            match = re.search(r'(\d+)', date_str)
                            if match:
                                day_dates[col_idx] = int(match.group(1))
                            else:
                                try:
                                    day_dates[col_idx] = int(float(date_val))
                                except:
                                    pass

            # Process each of the 4 pairs
            for pair_idx in range(1, 5):
                pair_row = base_row + (pair_idx - 1) * 3
                if pair_row + 2 >= len(df):
                    continue

                for col_idx, week_num in weeks_map.items():
                    code = df.iloc[pair_row, col_idx]
                    subj_abbr = df.iloc[pair_row + 1, col_idx]
                    room = df.iloc[pair_row + 2, col_idx]
                    
                    if pd.notna(code) and pd.notna(subj_abbr):
                        code = str(code).strip()
                        subj_abbr = str(subj_abbr).strip()
                        room = str(room).strip() if pd.notna(room) else ''
                        
                        # Identify lesson type from code (e.g., "Л/Т.01" -> "Л")
                        lesson_type = 'Л' if code.startswith('Л/') else 'П'
                        if '/' in code:
                            type_candidate = code.split('/')[0]
                            if type_candidate in teacher_mapping.get(subj_abbr, {}):
                                lesson_type = type_candidate

                        potential_teachers = teacher_mapping.get(subj_abbr, {}).get(lesson_type, [])
                        
                        # Apply smart distribution
                        assigned_teacher = self._assign_teacher(
                            week=week_num,
                            day=day_name,
                            pair=pair_idx,
                            subj_abbr=subj_abbr,
                            lesson_type=lesson_type,
                            potential_teachers=potential_teachers
                        )
                        
                        lessons.append(Lesson(
                            group=group_name,
                            subject=subj_abbr,
                            lesson_type_code=code,
                            room=room,
                            week=week_num,
                            day_of_week=day_name,
                            pair_num=pair_idx,
                            teacher=assigned_teacher,
                            date_day=day_dates.get(col_idx, 0),
                            month=months_map.get(col_idx, 'Unknown'),
                            semester_info=semester_text,
                            year_info=year_text
                        ))
            
        logger.info(f"Successfully loaded {len(lessons)} lessons for group {group_name}")
        return lessons

if __name__ == '__main__':
    # Simple test run
    import os
    base_dir = '/home/YaremenkoIA/planner-solving'
    cfg_path = os.path.join(base_dir, 'teachers.json')
    if os.path.exists(cfg_path):
        loader = DataLoader(cfg_path)
        test_file = os.path.join(base_dir, 'obrazec/522.xlsx')
        if os.path.exists(test_file):
            results = loader.load_group_schedule(test_file)
            print(f"Extracted {len(results)} lessons.")
            if results:
                print(f"Sample lesson: {results[0]}")
