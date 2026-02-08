import os
import json
import shutil
import uuid
from typing import List
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from web.backend.schemas import Teacher, TeacherCreate, TeacherUpdate, ScheduleUploadResponse, FileUploadDetail
from src.data_loader import DataLoader
from src.transformer import transform_to_teacher_grid
from src.exporter import export_to_excel

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEACHERS_JSON = os.path.join(BASE_DIR, "teachers.json")
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Ensure directories exist
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_teachers() -> List[dict]:
    if not os.path.exists(TEACHERS_JSON):
        return []
    with open(TEACHERS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def save_teachers(teachers: List[dict]):
    with open(TEACHERS_JSON, "w", encoding="utf-8") as f:
        json.dump(teachers, f, ensure_ascii=False, indent=2)

@app.get("/api/teachers", response_model=List[Teacher])
def get_teachers():
    return load_teachers()

@app.post("/api/teachers", response_model=Teacher)
def create_teacher(teacher: TeacherCreate):
    teachers = load_teachers()
    new_id = max([t["id"] for t in teachers], default=0) + 1
    new_teacher = teacher.dict()
    new_teacher["id"] = new_id
    teachers.append(new_teacher)
    save_teachers(teachers)
    return new_teacher

@app.put("/api/teachers/{teacher_id}", response_model=Teacher)
def update_teacher(teacher_id: int, teacher_update: TeacherUpdate):
    teachers = load_teachers()
    for i, t in enumerate(teachers):
        if t["id"] == teacher_id:
            update_data = teacher_update.dict(exclude_unset=True)
            teachers[i].update(update_data)
            save_teachers(teachers)
            return teachers[i]
    raise HTTPException(status_code=404, detail="Teacher not found")

@app.delete("/api/teachers/{teacher_id}")
def delete_teacher(teacher_id: int):
    teachers = load_teachers()
    new_teachers = [t for t in teachers if t["id"] != teacher_id]
    if len(new_teachers) == len(teachers):
        raise HTTPException(status_code=404, detail="Teacher not found")
    save_teachers(new_teachers)
    return {"status": "success"}

@app.post("/api/upload", response_model=ScheduleUploadResponse)
async def upload_schedule(files: List[UploadFile] = File(...)):
    all_lessons = []
    file_id = str(uuid.uuid4())
    input_paths = []
    details = []
    
    try:
        for file in files:
            detail = FileUploadDetail(filename=file.filename, status="pending", message="")
            
            if not file.filename.endswith(('.xlsx', '.xls')):
                detail.status = "error"
                detail.message = f"Invalid file type: {file.filename}"
                details.append(detail)
                continue
            
            # Original group name (filename without extension)
            group_name = Path(file.filename).stem
            
            # Save uploaded file
            input_filename = f"{file_id}_{file.filename}"
            input_path = os.path.join(INPUT_DIR, input_filename)
            input_paths.append(input_path)
            
            try:
                with open(input_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                
                # Process schedule for this file
                loader = DataLoader(TEACHERS_JSON)
                lessons = loader.load_group_schedule(input_path, group_name=group_name)
                
                if lessons:
                    all_lessons.extend(lessons)
                    detail.status = "success"
                    detail.message = "OK"
                else:
                    detail.status = "warning"
                    detail.message = "No lessons found in file"
                    
            except Exception as e:
                print(f"Error processing {file.filename}: {e}")
                detail.status = "error"
                detail.message = str(e)
            
            details.append(detail)

        if not all_lessons:
             # If no lessons collected from any file, return error response
             return ScheduleUploadResponse(
                 filename=None, 
                 status="error", 
                 message="No lessons parsed from any uploaded files",
                 details=details
             )

        # Load teachers config for transformation
        with open(TEACHERS_JSON, 'r', encoding='utf-8') as f:
            teachers_config = json.load(f)
            
        # Filter and transform
        lessons_filtered = [l for l in all_lessons if l.teacher != 'Unknown']
        transformed_data = transform_to_teacher_grid(lessons_filtered, teachers_config)
        
        # Export
        output_filename = f"schedule_{file_id}.xlsx"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        export_to_excel(transformed_data, teachers_config, output_path)
        
        return ScheduleUploadResponse(
            filename=output_filename,
            status="success",
            message="Schedule processed successfully",
            details=details
        )
            
    except Exception as e:
        print(f"Global error processing schedule: {e}")
        # Return error response instead of 500 so client sees details
        return ScheduleUploadResponse(
            filename=None,
            status="error",
            message=f"Global processing error: {str(e)}",
            details=details
        )
        
    finally:
        # Cleanup input files
        for path in input_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

@app.get("/api/download/{filename}")
def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# Mount static files
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "web/frontend"), html=True), name="frontend")
