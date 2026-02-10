import os
import json
from src.data_loader import DataLoader
from src.transformer import transform_to_teacher_grid
from src.exporter import export_to_excel

# Load config
with open('teachers.json', 'r', encoding='utf-8') as f:
    teachers_config = json.load(f)

loader = DataLoader('teachers.json')
all_lessons = []

obrazec_dir = 'obrazec'
files = [f for f in os.listdir(obrazec_dir) if f.endswith('.xlsx') and not f.startswith('~') and not f.startswith('_')]

for filename in files:
    path = os.path.join(obrazec_dir, filename)
    lessons = loader.load_group_schedule(path)
    all_lessons.extend(lessons)

print(f"Total lessons loaded: {len(all_lessons)}")

transformed = transform_to_teacher_grid(all_lessons, teachers_config)
output_path = 'teacher_schedules.xlsx'
export_to_excel(transformed, teachers_config, output_path)
print(f"Exported to {output_path}")
