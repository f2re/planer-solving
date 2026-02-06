import argparse
import json
import os
import sys
import logging
from src.data_loader import DataLoader
from src.validator import Validator
from src.solver import ScheduleSolver
from src.exporter import Exporter

def setup_logging(level_name):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("schedule.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def main():
    parser = argparse.ArgumentParser(description="Schedule Generator")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--validate-only", action="store_true", help="Only validate input data")
    args = parser.parse_args()

    # Load config
    if not os.path.exists(args.config):
        print(f"Config file not found: {args.config}")
        sys.exit(1)
        
    with open(args.config, 'r', encoding='utf-8') as f:
        config = json.load(f)

    setup_logging(config.get('logging_level', 'INFO'))
    logger = logging.getLogger(__name__)

    # Load data
    logger.info("Loading data...")
    loader = DataLoader(config['input_directory'])
    try:
        data = loader.load_all()
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        sys.exit(1)

    # Validate
    logger.info("Validating data...")
    validator = Validator(data)
    if not validator.validate_all():
        logger.error("Validation failed! Check logs for details.")
        sys.exit(1)

    if args.validate_only:
        logger.info("Validation successful. Exiting as requested.")
        return

    # Solve
    logger.info("Solving schedule...")
    solver = ScheduleSolver(data, config)
    try:
        assignments = solver.solve()
        # Add solver-computed slots back to data for exporter
        data['valid_global_slots'] = solver.valid_global_slots
    except Exception as e:
        logger.error(f"Error during solving: {e}")
        sys.exit(1)

    if not assignments:
        logger.error("No valid schedule found!")
        sys.exit(1)

    # Export
    logger.info("Exporting results...")
    if not os.path.exists(config['output_directory']):
        os.makedirs(config['output_directory'])
        
    output_path = os.path.join(config['output_directory'], 'schedule_result.xlsx')
    exporter = Exporter(assignments, data, config, output_path)
    try:
        exporter.export()
        logger.info(f"Schedule generated successfully: {output_path}")
    except Exception as e:
        logger.error(f"Error during export: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
