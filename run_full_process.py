import os
import json
from src.data_loader import DataLoader
from src.weekly_exporter import generate_weekly_semester_schedule

def main():
    # 1. Load configurations
    if not os.path.exists('config.json'):
        print("Error: config.json not found")
        return
        
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    if not os.path.exists('teachers.json'):
        print("Error: teachers.json not found")
        return

    with open('teachers.json', 'r', encoding='utf-8') as f:
        teachers_config = json.load(f)

    # 2. Initialize loader
    loader = DataLoader('teachers.json')
    all_lessons = []

    # 3. Load all group schedules from obrazec/
    obrazec_dir = 'obrazec'
    if not os.path.exists(obrazec_dir):
        print(f"Error: {obrazec_dir} directory not found")
        return

    files = [f for f in os.listdir(obrazec_dir) 
             if f.endswith('.xlsx') and not f.startswith('~') 
             and not f.startswith('_') and f != 'Недельное.xlsx']

    for filename in files:
        path = os.path.join(obrazec_dir, filename)
        print(f"Loading {path}...")
        lessons = loader.load_group_schedule(path)
        all_lessons.extend(lessons)

    print(f"Total lessons loaded: {len(all_lessons)}")

    # 4. Ensure output directory exists
    if not os.path.exists('output'):
        os.makedirs('output')

    # 5. Generate the Weekly Semester Schedule
    output_path = 'output/semester_schedule_weekly.xlsx'
    print(f"Generating weekly schedule for semester: {output_path}")
    
    generate_weekly_semester_schedule(
        teachers_config=teachers_config,
        lessons=all_lessons,
        template_path='obrazec/Недельное.xlsx',
        output_path=output_path,
        start_date_str=config.get('schedule_start_date', '2026-02-10'),
        end_date_str=config.get('schedule_end_date', '2026-06-30')
    )

    print(f"Success! Weekly semester schedule exported to {output_path}")

if __name__ == "__main__":
    main()