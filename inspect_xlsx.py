import pandas as pd
import sys

try:
    df = pd.read_excel('obrazec/522.xlsx', header=None)
    print("Shape:", df.shape)
    
    # Try to find weeks row
    weeks_row_idx = None
    for r in range(min(20, len(df))):
        row_vals = [str(x).lower().strip() for x in df.iloc[r, :5] if pd.notna(x)]
        if any(('уч.недели' in x or 'уч. недели' in x) for x in row_vals):
            weeks_row_idx = r
            print(f"Weeks row index: {weeks_row_idx}")
            print("Weeks row content:", df.iloc[r, :15].tolist())
            break
            
    if weeks_row_idx is not None:
        print("Months row index:", weeks_row_idx + 1)
        print("Months row content:", df.iloc[weeks_row_idx + 1, :15].tolist())
        
        print("First day (Mon) grid starts around row:", weeks_row_idx + 3)
        print("Dates row for Mon:", weeks_row_idx + 2)
        print("Dates row content:", df.iloc[weeks_row_idx + 2, :15].tolist())

except Exception as e:
    print(f"Error: {e}")
