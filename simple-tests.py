import pandas as pd
import json
from dotenv import load_dotenv
load_dotenv()

pd.set_option("display.width", 200, "display.max_columns", 30)

pb = pd.read_parquet("tidy/plan_benefits.parquet")
print("=== plan_benefits sample ===")
print(pb.head(10).to_string(index=False))
print("\n=== null counts per column ===")
print(pb.isna().sum())


pq = pd.read_parquet("tidy/premium_quotes.parquet")
print("\nPremium range:", pq["monthly_premium"].min(), "to", pq["monthly_premium"].max())
print("Any null premiums?", pq["monthly_premium"].isna().sum())

plans = pd.read_parquet("tidy/plans.parquet")
print("\nMetal levels:", plans["metal_level"].value_counts().to_dict())



d = json.load(open("raw_cache/plans_18043_single_40_250fpl.json"))
resp = d["response"]
print("Top-level keys:", list(resp.keys()))
print("Plans returned:", len(resp.get("plans", [])))
# look for anything like a total count or paging info
for k in resp:
    if k != "plans":
        print(f"  {k}: {resp[k]}")