import pandas as pd

file = 'obrazec/522.xlsx'
print(f"--- Inspecting bottom of {file} ---")
try:
    df = pd.read_excel(file, header=None)
    print(df.tail(20).to_string())
except Exception as e:
    print(f"Error: {e}")
