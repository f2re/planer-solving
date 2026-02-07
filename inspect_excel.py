import pandas as pd
import os

files = ['obrazec/522.xlsx', 'obrazec/Сводное расписание семестр.xlsx']

for file in files:
    print("\n--- Inspecting: " + file + " ---")
    try:
        xl = pd.ExcelFile(file)
        print("Sheets: " + str(xl.sheet_names))
        for sheet in xl.sheet_names:
            print("\nSheet: " + sheet)
            df = pd.read_excel(file, sheet_name=sheet, header=None, nrows=20)
            print(df.to_string())
    except Exception as e:
        print("Error reading " + file + ": " + str(e))