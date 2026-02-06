from src.data_loader import DataLoader
from src.validator import DataValidator
import os

def test_loading():
    input_dir = '/home/YaremenkoIA/planner-solving/input'
    loader = DataLoader(input_dir)
    data = loader.load_all()
    
    print(f"Loaded {len(data['teachers'])} teachers")
    print(f"Loaded {len(data['lessons'])} lessons")
    
    validator = DataValidator(data)
    success, errors, warnings = validator.validate()
    
    if success:
        print("Validation successful!")
    else:
        print("Validation failed:")
        for err in errors:
            print(f"  - {err}")
    
    for warn in warnings:
        print(f"Warning: {warn}")

if __name__ == "__main__":
    test_loading()
