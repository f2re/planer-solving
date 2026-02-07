import json
import os
from src.data_loader import DataLoader
from src.transformer import transform_to_teacher_grid
from src.exporter import export_to_excel

def main():
    base_path = '/home/YaremenkoIA/planner-solving'
    input_file = os.path.join(base_path, 'obrazec/522.xlsx')
    teachers_config_path = os.path.join(base_path, 'teachers.json')
    output_file = os.path.join(base_path, 'output/result.xlsx')
    
    if not os.path.exists('output'):
        os.makedirs('output')
        
    print(f'Loading teachers config from {teachers_config_path}...')
    with open(teachers_config_path, 'r', encoding='utf-8') as f:
        teachers_config = json.load(f)
        
    print(f'Loading schedule from {input_file}...')
    loader = DataLoader(teachers_config_path)
    lessons = loader.load_group_schedule(input_file)
    print(f'Total lessons loaded: {len(lessons)}')
    
    # Filter out Unknown teachers for now as we only want those in config
    lessons_filtered = [l for l in lessons if l.teacher != 'Unknown']
    print(f'Lessons with matched teachers: {len(lessons_filtered)}')
    
    print('Transforming data...')
    transformed_data = transform_to_teacher_grid(lessons_filtered, teachers_config)
    
    print(f'Exporting to {output_file}...')
    export_to_excel(transformed_data, teachers_config, output_file)
    print('Done!')

if __name__ == '__main__':
    main()
