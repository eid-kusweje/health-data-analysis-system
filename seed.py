"""
seed.py - Demo users + synthetic Malawi dataset.

The synthetic dataset is DE-IDENTIFIED AGGREGATE data (monthly counts per
district / disease / sex / age group). It contains deliberately planted
data-quality problems so that every data-quality check can be demonstrated
and tested:

  * ~9% of case counts left blank (missing values), and ~28% blank for
    Mangochi, so one district visibly needs data-quality follow-up
  * exact duplicate rows appended, plus re-submitted rows whose totals
    conflict with the original submission (consistency)
  * a few negative and non-numeric case counts (validity)
  * one unusually large malaria spike in Mangochi (outlier for review)
  * inconsistent sex spellings (M / male / Male / F / female ...) and a
    small number of "Unknown" sex values (validity)
  * inconsistent district capitalisation and trailing spaces, plus a few
    district names that are not in the 28-district list (e.g. a city
    label used where a district is expected)
  * ~15% of reports submitted late (timeliness)
  * a few deaths > cases rows (consistency)

Run directly to (re)create sample_data files:
    python seed.py
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pandas as pd

import db
from analysis import MALAWI_DISTRICTS, detect_mapping

DEMO_USERS = [
    ("System Administrator", "admin@demo.mw", "Admin123!", "admin"),
    ("Demo Analyst", "analyst@demo.mw", "Analyst123!", "analyst"),
    ("Demo Viewer", "viewer@demo.mw", "Viewer123!", "viewer"),
]

DISEASE_BASE = {  # rough relative monthly burden used only for simulation
    "Malaria": 900, "Pneumonia": 320, "Diarrhoea": 380,
    "Tuberculosis": 90, "Cholera": 25, "Dysentery": 110,
}
AGE_GROUPS = ["0-4", "5-14", "15-49", "50+"]
AGE_WEIGHTS = [0.34, 0.22, 0.32, 0.12]
SEX_SPELLINGS = {"Male": ["Male", "M", "male"], "Female": ["Female", "F", "female"]}
DEMO_DISTRICTS = ["Lilongwe", "Blantyre", "Mangochi", "Mzimba", "Kasungu",
                  "Zomba", "Karonga", "Salima", "Dedza", "Thyolo",
                  "Machinga", "Nkhotakota"]
# Seasonal multipliers (rainy season Nov-Apr raises malaria/diarrhoea/cholera)
SEASONAL = {"Malaria": [1.35, 1.4, 1.3, 1.15, 0.85, 0.7, 0.65, 0.65, 0.7, 0.8, 1.0, 1.25],
            "Diarrhoea": [1.3, 1.3, 1.2, 1.05, 0.9, 0.8, 0.75, 0.75, 0.8, 0.9, 1.05, 1.2],
            "Cholera": [1.8, 1.9, 1.5, 1.1, 0.6, 0.35, 0.3, 0.3, 0.4, 0.6, 1.0, 1.5]}


def generate_demo_dataframe(seed: int = 2063) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rnd = random.Random(seed)
    months = pd.period_range("2023-01", "2025-06", freq="M")
    pop_factor = {d: float(rng.uniform(0.35, 1.6)) for d in DEMO_DISTRICTS}
    pop_factor["Lilongwe"], pop_factor["Blantyre"] = 1.9, 1.6

    rows = []
    for period in months:
        month_start = period.to_timestamp()
        month_end = period.to_timestamp(how="end").normalize()
        for district in DEMO_DISTRICTS:
            for disease, base in DISEASE_BASE.items():
                seasonal = SEASONAL.get(disease, [1.0] * 12)[period.month - 1]
                trend = 1 + 0.10 * ((period.year - 2023) + (period.month - 1) / 12)
                expected = base * pop_factor[district] * seasonal * trend
                monthly_total = max(int(rng.normal(expected, max(expected * 0.18, 1))), 0)
                for sex in ("Male", "Female"):
                    sex_share = 0.48 if sex == "Male" else 0.52
                    for age, age_w in zip(AGE_GROUPS, AGE_WEIGHTS):
                        cases = int(round(monthly_total * sex_share * age_w
                                          * float(rng.uniform(0.8, 1.2))))
                        cfr = {"Malaria": 0.004, "Pneumonia": 0.02, "Diarrhoea": 0.006,
                               "Tuberculosis": 0.05, "Cholera": 0.015,
                               "Dysentery": 0.008}[disease]
                        deaths = int(rng.binomial(max(cases, 0), cfr)) if cases > 0 else 0
                        delay_days = int(rng.integers(3, 13))
                        if rnd.random() < 0.15:  # planted late reports
                            delay_days = int(rng.integers(25, 75))
                        date_reported = month_end + pd.Timedelta(days=delay_days)
                        rows.append({
                            "district": district,
                            "region": MALAWI_DISTRICTS[district],
                            "disease": disease,
                            "period_date": month_start.strftime("%Y-%m-%d"),
                            "date_reported": date_reported.strftime("%Y-%m-%d"),
                            "sex": sex, "age_group": age,
                            "cases": cases, "deaths": deaths,
                        })
    df = pd.DataFrame(rows)

    # ---- planted data-quality problems (documented above) ----
    n = len(df)
    df["cases"] = df["cases"].astype(object)  # allow a few non-numeric entries
    blank_idx = rng.choice(df.index, size=int(n * 0.09), replace=False)
    df.loc[blank_idx, "cases"] = np.nan
    Mangochi = df[df.district == "Mangochi"].index
    m_blank = rng.choice(Mangochi, size=int(len(Mangochi) * 0.28), replace=False)
    df.loc[m_blank, "cases"] = np.nan
    neg_idx = rng.choice(df.index, size=18, replace=False)
    df.loc[neg_idx, "cases"] = -5
    text_idx = rng.choice(df.index, size=25, replace=False)
    df.loc[text_idx, "cases"] = "many"
    bad_cfr = rng.choice(df.index, size=10, replace=False)
    df.loc[bad_cfr, "deaths"] = pd.to_numeric(df.loc[bad_cfr, "cases"],
                                             errors="coerce").fillna(10) + 3
    spike = df[(df.district == "Mangochi") & (df.disease == "Malaria")
               & (df.period_date == "2024-02-01")].index
    df.loc[spike, "cases"] = pd.to_numeric(df.loc[spike, "cases"],
                                           errors="coerce").fillna(100) * 6
    df["sex"] = [rnd.choice(SEX_SPELLINGS[s]) if rnd.random() < 0.35 else s
                 for s in df["sex"]]
    unk_sex = rng.choice(df.index, size=int(n * 0.012), replace=False)
    df.loc[unk_sex, "sex"] = "Unknown"
    df["district"] = [d.lower() if rnd.random() < 0.08 else (d + " " if rnd.random() < 0.05 else d)
                      for d in df["district"]]
    city_idx = rng.choice(df[df.district.str.strip().str.lower() == "blantyre"].index,
                          size=40, replace=False)
    df.loc[city_idx, "district"] = "Blantyre City"
    dupes = df.sample(220, random_state=seed)
    conflicts = df.sample(45, random_state=seed + 1).copy()
    conflicts["cases"] = pd.to_numeric(conflicts["cases"], errors="coerce").fillna(7) + 13
    df = pd.concat([df, dupes, conflicts], ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


TEMPLATE_COLUMNS = ["district", "region", "disease", "period_date",
                    "date_reported", "sex", "age_group", "cases", "deaths"]


def write_sample_files(base_dir: Path) -> Path:
    sample_dir = base_dir / "sample_data"
    sample_dir.mkdir(parents=True, exist_ok=True)
    demo = generate_demo_dataframe()
    demo_path = sample_dir / "malawi_synthetic_health_data.csv"
    demo.to_csv(demo_path, index=False)
    pd.DataFrame([
        ["Lilongwe", "Central", "Malaria", "2025-01-01", "2025-02-06", "Female", "0-4", 120, 1],
        ["Zomba", "Southern", "Diarrhoea", "2025-01-01", "2025-02-08", "Male", "5-14", 45, 0],
    ], columns=TEMPLATE_COLUMNS).to_csv(sample_dir / "data_template.csv", index=False)
    return demo_path


def seed_database(db_path, base_dir: Path, upload_dir: Path) -> None:
    """Create demo users and register the demo dataset (idempotent)."""
    db.init_db(db_path)
    admin_id = None
    for name, email, password, role in DEMO_USERS:
        if not db.get_user_by_email(db_path, email):
            uid = db.create_user(db_path, name, email, password, role)
        else:
            uid = db.get_user_by_email(db_path, email)["id"]
        if role == "admin":
            admin_id = uid

    existing = [d for d in db.list_datasets(db_path) if d["is_demo"]]
    if existing:
        return
    demo_path = base_dir / "sample_data" / "malawi_synthetic_health_data.csv"
    if not demo_path.exists():
        demo_path = write_sample_files(base_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / "demo_malawi_synthetic_health_data.csv"
    stored.write_bytes(demo_path.read_bytes())
    df = pd.read_csv(stored)
    db.add_dataset(
        db_path, name="Malawi synthetic demo data (2023-2025)",
        original_filename=demo_path.name, stored_path=str(stored),
        file_type="csv", row_count=len(df), col_count=len(df.columns),
        mapping=detect_mapping(df), owner_id=admin_id, is_demo=True,
        description="Synthetic de-identified aggregate data with deliberately "
                    "planted data-quality problems - for training and system "
                    "testing only, not real Malawi statistics.")
    db.log_action(db_path, admin_id, "seed", "Demo users and demo dataset created")


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    p = write_sample_files(base)
    print(f"Wrote {p} ({len(pd.read_csv(p)):,} rows) and data_template.csv")
