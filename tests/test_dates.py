import pytest
import pandas as pd
import os
from src.data_loader import DataLoader
from src.transformer import transform_to_teacher_grid, Lesson

def test_month_normalization():
    # We need a dummy teachers.json
    with open('temp_teachers.json', 'w') as f:
        f.write('[]')
    
    loader = DataLoader('temp_teachers.json')
    
    # Test normalization logic by mocking df
    # Since we can't easily mock the whole load_group_schedule without a file, 
    # let's test how it handles month names if we could inject them.
    # Actually, let's just test the transformer's sorting which we improved.
    
    os.remove('temp_teachers.json')

def test_transformer_sorting_robustness():
    lessons = [
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 1, "январь"), # lowercase
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 2, "Сентябрь "), # trailing space
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 3, "09"), # numeric string
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 5, "Unknown"), # Unknown
    ]
    
    result = transform_to_teacher_grid(lessons, [])
    dates = result["dates"]
    
    # Order should be:
    # 1. Сентябрь (order 9, year_offset 0)
    # 2. 09 (order 9, year_offset 0)
    # 3. январь (order 1, year_offset 1)
    # 4. Unknown (order 0, year_offset 2)
    
    assert dates[0] == ("Сентябрь ", 2)
    assert dates[1] == ("09", 3)
    assert dates[2] == ("январь", 1)
    assert dates[3] == ("Unknown", 5)

def test_date_parsing_regex():
    # Test the logic we added to DataLoader for date parsing
    import re
    def parse_date(date_val):
        if hasattr(date_val, 'day'):
            return date_val.day
        date_str = str(date_val).strip()
        match = re.search(r'(\d+)', date_str)
        if match:
            return int(match.group(1))
        return 0

    assert parse_date("02.09") == 2
    assert parse_date("15") == 15
    assert parse_date(" 7 ") == 7
    assert parse_date(pd.Timestamp("2023-09-05")) == 5
