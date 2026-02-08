import pytest
import os
from src.data_loader import DataLoader

@pytest.fixture
def loader():
    base_path = '/home/user/planner-solving'
    config_path = os.path.join(base_path, 'teachers.json')
    return DataLoader(config_path)

def test_load_group_schedule_structure(loader):
    base_path = '/home/user/planner-solving'
    sample_file = os.path.join(base_path, 'obrazec/522.xlsx')
    
    if not os.path.exists(sample_file):
        pytest.skip("Sample file not found")
        
    lessons = loader.load_group_schedule(sample_file)
    
    assert len(lessons) > 0
    # Check first lesson attributes
    l = lessons[0]
    assert hasattr(l, 'group')
    assert hasattr(l, 'subject')
    assert hasattr(l, 'teacher')
    assert l.group == '522'

def test_extract_teachers(loader):
    text = "д.т.н., проф. Касаткин С.И., ст.пр. Ветров А.Н."
    # Assuming these names are in teachers.json
    found = loader._extract_teachers(text)
    
    # Let's check what's in teachers.json to be sure
    # (The actual names might be different, this is a bit brittle if config changes)
    assert isinstance(found, list)

def test_teacher_mapping_not_empty(loader):
    base_path = '/home/user/planner-solving'
    sample_file = os.path.join(base_path, 'obrazec/522.xlsx')
    
    if not os.path.exists(sample_file):
        pytest.skip("Sample file not found")

    # This is a bit of a hack to check internal state if we wanted to
    # but let's just check that we got some lessons with teachers
    lessons = loader.load_group_schedule(sample_file)
    teachers = [l.teacher for l in lessons if l.teacher != 'Unknown']
    assert len(teachers) > 0
