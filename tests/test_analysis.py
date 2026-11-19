"""Unit tests for the pure Pandas analysis functions (analysis.py).

Run:  python -m pytest -q
Each test states the planted problem and the exact expected result, so the
suite doubles as executable evidence for the project objectives.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis import (analyse_dataframe, clean_dataframe, data_quality,  # noqa: E402
                      detect_mapping, disease_patterns)

ROOT = Path(__file__).resolve().parents[1]


def check(quality, prefix):
    return next(c for c in quality["checks"] if c["check"].startswith(prefix))


def base_df(rows):
    cols = ["district", "disease", "period_date", "date_reported",
            "sex", "age_group", "cases", "deaths"]
    return pd.DataFrame(rows, columns=cols)


def test_detect_mapping_aliases():
    df = pd.DataFrame(columns=["District Name", "Diagnosis", "Reporting Period",
                               "Gender", "Value", "unrelated"])
    m = detect_mapping(df)
    assert m["district"] == "District Name"
    assert m["disease"] == "Diagnosis"
    assert m["period_date"] == "Reporting Period"
    assert m["sex"] == "Gender"
    assert m["cases"] == "Value"


def test_missing_duplicates_and_completeness():
    df = base_df([
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Female", "0-4", 10, 0],
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Female", "0-4", 10, 0],  # duplicate
        ["Zomba", "Malaria", "2025-02-01", "2025-03-05", "Male", "5-14", None, 0],   # missing cases
        ["Zomba", "Malaria", "2025-03-01", "2025-04-05", "Male", "5-14", 7, 0],
    ])
    q = data_quality(df)
    assert q["duplicates"] == 1
    assert check(q, "Records missing a key field")["affected"] == 1
    assert q["complete_records_pct"] == 75.0
    assert q["dimensions"]["uniqueness"] == 75.0


def test_validity_checks_each_find_one_planted_error():
    df = base_df([
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Female", "0-4", -3, 0],
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Female", "0-4", "many", 0],
        ["Lilongwe", "Malaria", "2099-01-01", "2025-02-05", "Female", "0-4", 5, 0],
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Unknown", "0-4", 5, 0],
        ["Nowhere Town", "Malaria", "2025-01-01", "2025-02-05", "Male", "0-4", 5, 0],
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Male", "0-4", 5, 9],  # deaths > cases
    ])
    q = data_quality(df)
    assert check(q, "Negative case counts")["affected"] == 1
    assert check(q, "Non-numeric case counts")["affected"] == 1
    assert check(q, "Future period dates")["affected"] == 1
    assert check(q, "Unrecognised sex values")["affected"] == 1
    assert check(q, "Districts not in Malawi list")["affected"] == 1
    assert check(q, "Deaths greater than cases")["affected"] == 1
    assert q["unknown_districts"] == ["Nowhere Town"]


def test_timeliness_late_after_15_days_past_month_end():
    df = base_df([
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-10", "Female", "0-4", 5, 0],  # 10 days: on time
        ["Lilongwe", "Malaria", "2025-02-01", "2025-04-20", "Female", "0-4", 5, 0],  # late
    ])
    q = data_quality(df)
    assert q["timeliness"]["assessable"] is True
    assert q["timeliness"]["late_rows"] == 1
    assert q["dimensions"]["timeliness"] == 50.0


def test_timeliness_not_assessable_without_report_date():
    df = pd.DataFrame([["Lilongwe", "Malaria", "2025-01-01", 5]],
                      columns=["district", "disease", "period_date", "cases"])
    q = data_quality(df)
    assert q["timeliness"]["assessable"] is False
    assert q["dimensions"]["timeliness"] is None
    assert 0 <= q["overall_score"] <= 100
    assert "timeliness" not in q["score_weights"]


def test_extreme_outlier_spike_is_flagged():
    months = pd.period_range("2024-01", periods=14, freq="M")
    values = [9, 10, 11, 10, 12, 9, 11, 10, 12, 11, 10, 9, 11, 900]  # last = spike
    df = base_df([["Mangochi", "Malaria", str(m.to_timestamp().date()),
                   str((m.to_timestamp(how="end") + pd.Timedelta(days=5)).date()),
                   "Female", "0-4", v, 0] for m, v in zip(months, values)])
    q = data_quality(df)
    assert q["outlier_count"] >= 1
    assert q["outliers"][0]["cases"] == 900
    assert q["outliers"][0]["district"] == "Mangochi"


def test_patterns_totals_filters_and_zero_filled_trend():
    df = base_df([
        ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Female", "0-4", 100, 2],
        ["Lilongwe", "Malaria", "2025-03-01", "2025-04-05", "Male", "0-4", 50, 1],
        ["Zomba", "Cholera", "2025-01-01", "2025-02-05", "Female", "0-4", 20, 1],
        ["Zomba", "Malaria", "2025-01-01", "2025-02-05", "Female", "0-4", -99, 0],  # excluded
    ])
    all_p = disease_patterns(df)
    assert all_p["kpis"]["total_cases"] == 170  # 100 + 50 + 20, negative excluded
    malaria = disease_patterns(df, {"disease": "Malaria"})
    assert malaria["kpis"]["total_cases"] == 150
    assert [t["value"] for t in malaria["trend_monthly"]] == [100, 0, 50]  # Feb filled
    assert malaria["kpis"]["districts"] == 1


def test_line_list_mode_counts_one_case_per_row():
    df = pd.DataFrame([["Lilongwe", "Malaria", "2025-01-01"],
                       ["Lilongwe", "Malaria", "2025-01-01"],
                       ["Zomba", "Cholera", "2025-01-01"]],
                      columns=["district", "disease", "period_date"])
    p = disease_patterns(df)
    assert p["kpis"]["total_cases"] == 3


def test_cleaning_standardises_but_keeps_rows_by_default():
    df = base_df([
        [" lilongwe ", "malaria", "2025-01-01", "2025-02-05", "m", "0-4", "12", 0],
        ["Zomba", "Malaria", "2025-01-01", "2025-02-05", "FEMALE", "0-4", -4, 0],
    ])
    cleaned, log = clean_dataframe(df)
    assert len(cleaned) == 2
    assert cleaned.loc[0, "district"] == "Lilongwe"
    assert cleaned.loc[0, "sex"] == "Male"
    assert pd.isna(cleaned.loc[1, "cases"])  # negative blanked, row kept
    assert any("Standardised sex" in entry["action"] for entry in log)


def test_cleaning_drop_duplicates_only_on_request():
    row = ["Lilongwe", "Malaria", "2025-01-01", "2025-02-05", "Male", "0-4", 5, 0]
    df = base_df([row, row])
    assert len(clean_dataframe(df)[0]) == 2
    assert len(clean_dataframe(df, drop_duplicates=True)[0]) == 1


@pytest.mark.skipif(not (ROOT / "sample_data" / "test_dirty_data.csv").exists(),
                    reason="dirty test file not generated")
def test_dirty_file_expected_results():
    df = pd.read_csv(ROOT / "sample_data" / "test_dirty_data.csv")
    q = data_quality(df)
    assert check(q, "Missing values (all cells)")["affected"] == 3
    assert q["duplicates"] == 2
    assert check(q, "Negative case counts")["affected"] == 1
    assert check(q, "Non-numeric case counts")["affected"] == 1
    assert check(q, "Future period dates")["affected"] == 1
    assert check(q, "Unrecognised sex values")["affected"] == 1
    assert check(q, "Deaths greater than cases")["affected"] == 1
    assert q["unknown_districts"] == ["Blantyre City"]
    assert q["timeliness"]["late_rows"] == 1


@pytest.mark.skipif(not (ROOT / "sample_data" / "malawi_synthetic_health_data.csv").exists(),
                    reason="demo file not generated (run python seed.py)")
def test_demo_dataset_planted_problems_are_detected():
    df = pd.read_csv(ROOT / "sample_data" / "malawi_synthetic_health_data.csv")
    result = analyse_dataframe(df)
    q, p = result["quality"], result["patterns"]
    assert 85 <= q["overall_score"] < 95 and q["rating"] == "Good"
    Mangochi = next(r for r in p["district_table"] if r["district"] == "Mangochi")
    assert Mangochi["completeness_pct"] < 75  # planted poor completeness
    assert q["outliers"][0]["district"] == "Mangochi"  # planted spike
    assert q["outliers"][0]["disease"] == "Malaria"
    assert q["timeliness"]["late_rows"] > 1000
    assert p["by_disease"][0]["label"] == "Malaria"
