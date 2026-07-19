import pytest
from src.data_loader import Lesson
from src.transformer import transform_to_teacher_grid

def test_transform_to_teacher_grid_basic():
    teachers_config = [
        {"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович", "rank": "доцент", "position": "к.т.н."},
        {"short_name": "Петров П.П.", "full_name": "Петров Петр Петрович", "rank": "профессор", "position": "д.т.н."}
    ]
    
    lessons = [
        Lesson(
            group="522", subject="Математика", lesson_type_code="Л/Т.01", 
            room="101", week=1, day_of_week="Пн", pair_num=1, 
            teacher="Иванов И.И.", date_day=2, month="Сентябрь"
        ),
        Lesson(
            group="522", subject="Физика", lesson_type_code="П/Т.02", 
            room="102", week=1, day_of_week="Вт", pair_num=2, 
            teacher="Петров П.П.", date_day=3, month="Сентябрь"
        ),
        Lesson(
            group="523", subject="Математика", lesson_type_code="Л/Т.01", 
            room="101", week=1, day_of_week="Пн", pair_num=1, 
            teacher="Иванов И.И.", date_day=2, month="Сентябрь"
        )
    ]
    
    result = transform_to_teacher_grid(lessons, teachers_config)
    
    assert "grid" in result
    assert "dates" in result
    assert "teachers" in result
    
    # Check dates
    assert ("Сентябрь", 2) in result["dates"]
    assert ("Сентябрь", 3) in result["dates"]
    assert len(result["dates"]) == 2
    
    # Check grid content
    grid = result["grid"]
    key_ivanov = ("Иванов И.И.", 1, "Сентябрь", 2)
    assert key_ivanov in grid
    assert "522" in grid[key_ivanov]["groups"]
    assert "523" in grid[key_ivanov]["groups"]
    
    key_petrov = ("Петров П.П.", 2, "Сентябрь", 3)
    assert key_petrov in grid
    assert grid[key_petrov]["groups"] == ["522"]
    
    # Check that it filtered out Unknown (though none here)
    assert len(result["teachers"]) == 2
    assert "Иванов И.И." in result["teachers"]

def test_transform_date_sorting():
    teachers_config = []
    lessons = [
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 5, "Октябрь"),
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 1, "Сентябрь"),
        Lesson("G", "S", "L", "R", 1, "D", 1, "T1", 10, "Сентябрь"),
    ]
    
    result = transform_to_teacher_grid(lessons, teachers_config)
    dates = result["dates"]
    
    assert dates[0] == ("Сентябрь", 1)
    assert dates[1] == ("Сентябрь", 10)
    assert dates[2] == ("Октябрь", 5)
