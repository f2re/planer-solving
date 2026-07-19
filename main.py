import json
import os
from src.data_loader import DataLoader
from src.weekly_exporter import generate_weekly_semester_schedule

def main():
    # Use absolute path if possible, but relative to CWD is safer for this environment
    base_path = os.getcwd()
    input_dir = os.path.join(base_path, 'obrazec')
    teachers_config_path = os.path.join(base_path, 'teachers.json')
    config_path = os.path.join(base_path, 'config.json')
    output_file = os.path.join(base_path, 'output/сводное_расписание.xlsx')
    
    if not os.path.exists('output'):
        os.makedirs('output')
        
    print(f'Loading configurations...')
    with open(teachers_config_path, 'r', encoding='utf-8') as f:
        teachers_config = json.load(f)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    print(f'Loading schedules from {input_dir}...')
    loader = DataLoader(teachers_config_path)
    all_lessons = []
    
    files = [f for f in os.listdir(input_dir) 
             if f.endswith('.xlsx') and not f.startswith('~') 
             and not f.startswith('_') and f != 'Недельное.xlsx']

    for filename in files:
        path = os.path.join(input_dir, filename)
        lessons = loader.load_group_schedule(path)
        all_lessons.extend(lessons)
        
    print(f'Total lessons loaded: {len(all_lessons)}')
    
    print(f'Exporting to weekly format: {output_file}...')
    generate_weekly_semester_schedule(
        teachers_config=teachers_config,
        lessons=all_lessons,
        template_path='obrazec/Недельное.xlsx',
        output_path=output_file,
        start_date_str=config.get('schedule_start_date', '2026-02-10'),
        end_date_str=config.get('schedule_end_date', '2026-06-30')
    )
    print('Done!')

if __name__ == '__main__':
    main()
