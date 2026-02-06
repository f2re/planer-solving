# Gemini Project: Schedule Planner (OR-Tools)

This project aims to develop an automated educational scheduling system using Google OR-Tools CP-SAT Solver.

## Project Overview
The system processes various input data (teachers, disciplines, rooms, etc.) in CSV format and generates an optimized schedule exported to Excel, considering both hard and soft constraints.

## Technical Stack
- **Language:** Python 3.11+
- **Solver:** Google OR-Tools CP-SAT (Constraint Programming)
- **Data Processing:** pandas
- **Export:** openpyxl (Excel), python-dateutil
- **Testing:** pytest (assumed based on `tests/` structure)

## Core Capabilities
- **Hard Constraints:** Teacher/Room/Group conflict prevention, room capacity, availability, room types, workload limits.
- **Soft Constraints:** Gap minimization (students/teachers), workload balancing, grouping consecutive lessons, building transition minimization.

## Project Structure
- `input/`: Source CSV files.
- `output/`: Generated Excel schedules and warning reports.
- `src/`: Core logic (data loading, validation, solver, constraints, exporter).
- `tests/`: Unit and integration tests.
- `config.json`: System configuration and constraint weights.
- `schedule_generator.py`: Main entry point.

## Current Status
- Initializing project context.
- `TASK_DESCRIPTION.md` reviewed.
- `GEMINI.md` created.

## Gemini CLI Instructions
- Adhere to the modular structure in `src/`.
- Ensure all CSV inputs follow the schema defined in `TASK_DESCRIPTION.md`.
- Prioritize CP-SAT solver efficiency and multi-threading where applicable.
- Maintain high test coverage (>80%).
