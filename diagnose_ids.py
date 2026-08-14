# diagnose_ids.py
import pandas as pd

products_df = pd.read_excel("data/products.xlsx")

# Check the problematic IDs
targets = ["RASKIK_MANGO_150", "RASKIN_NIMBU_PANI_160", "RASKIK_150"]

print("Searching for target product IDs...\n")

for target in targets:
    # Find rows containing the base name
    base = target.split("_")[0]  # e.g. "RASKIK"
    matching_rows = products_df[products_df["product_id"].astype(str).str.contains(base, na=False, case=False)]
    
    print(f"Looking for: '{target}'")
    print(f"Found {len(matching_rows)} rows containing '{base}':\n")
    
    for idx, row in matching_rows.iterrows():
        pid = row["product_id"]
        # Show the raw representation to catch hidden characters
        print(f"   Row {idx}: repr = {repr(pid)}")
        print(f"            length = {len(str(pid))}")
        print(f"            starts with '{str(pid)[:10]}'")
        print(f"            ends with '{str(pid)[-10:]}'")
    
    print("-" * 60)

# Show ALL product IDs so we can see what's actually in the catalog
print("\n\nALL product IDs in catalog (raw representation):")
for idx, pid in enumerate(products_df["product_id"].astype(str)):
    if "RAS" in pid.upper():
        print(f"   {idx}: {repr(pid)}")