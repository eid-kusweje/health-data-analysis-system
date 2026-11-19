"""
Example: use the analytics engine from your own Python code — no web
server needed. This is the "integratable with Python" path: the same
functions that power the dashboard can run inside a script, a Jupyter
notebook, or another system (e.g. a DHIS2 export job).

Run from the project folder:
    python examples/python_integration_example.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import analyse_dataframe  # noqa: E402

csv_path = Path(__file__).resolve().parents[1] / "sample_data" / "test_dirty_data.csv"
df = pd.read_csv(csv_path)

result = analyse_dataframe(df, filters={"disease": "Malaria"})
q, p = result["quality"], result["patterns"]

print(f"File: {csv_path.name}  ({len(df)} rows)")
print(f"Data-quality score: {q['overall_score']} / 100  ({q['rating']})")
print("Dimensions:", json.dumps(q["dimensions"]))
print("Checks with affected records:")
for c in q["checks"]:
    if c["affected"]:
        print(f"  - {c['check']}: {c['affected']}")
print(f"\nMalaria only -> cases: {p['kpis']['total_cases']:.0f}, "
      f"districts: {p['kpis']['districts']}")
print("Top districts for malaria:", p["by_district"][:3])
