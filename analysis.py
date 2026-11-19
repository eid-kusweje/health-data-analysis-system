"""
analysis.py
===========
Pure, testable data-analysis functions for the Malawi Health & Disease
Analytics dashboard.

This module has NO Flask and NO database code on purpose:
  * it can be unit-tested directly with pytest, and
  * it can be imported from any other Python program, e.g.

        import pandas as pd
        from analysis import analyse_dataframe

        df = pd.read_csv("my_dataset.csv")
        result = analyse_dataframe(df)
        print(result["quality"]["overall_score"])

All functions accept / return plain Python types (dict, list, numbers,
strings) so results can be JSON-serialised by the web API.
"""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Reference data: Malawi districts and regions (28 districts)
# ---------------------------------------------------------------------------
MALAWI_DISTRICTS = {
    "Balaka": "Southern", "Blantyre": "Southern", "Chikwawa": "Southern",
    "Chiradzulu": "Southern", "Chitipa": "Northern", "Dedza": "Central",
    "Dowa": "Central", "Karonga": "Northern", "Kasungu": "Central",
    "Likoma": "Northern", "Lilongwe": "Central", "Machinga": "Southern",
    "Mangochi": "Southern", "Mchinji": "Central", "Mulanje": "Southern",
    "Mwanza": "Southern", "Mzimba": "Northern", "Neno": "Southern",
    "Nkhata Bay": "Northern", "Nkhotakota": "Central", "Nsanje": "Southern",
    "Ntcheu": "Central", "Ntchisi": "Central", "Phalombe": "Southern",
    "Rumphi": "Northern", "Salima": "Central", "Thyolo": "Southern",
    "Zomba": "Southern",
}
_DISTRICT_BY_LOWER = {k.lower(): k for k in MALAWI_DISTRICTS}

# Column-name aliases -> canonical field. Normalised column names are
# lower-case with spaces / hyphens replaced by underscores.
COLUMN_ALIASES = {
    "disease": {"disease", "condition", "diagnosis", "illness"},
    "district": {"district", "district_name"},
    "region": {"region"},
    "facility": {"facility", "facility_name", "health_facility"},
    "period_date": {"period_date", "date", "month", "period", "reporting_period",
                    "visit_date", "case_date"},
    "date_reported": {"date_reported", "report_date", "reported_on",
                      "submission_date", "date_submitted"},
    "cases": {"cases", "case_count", "value", "count", "total_cases",
              "number_of_cases", "no_of_cases"},
    "deaths": {"deaths", "death_count", "total_deaths"},
    "sex": {"sex", "gender"},
    "age_group": {"age_group", "agegroup", "age"},
    "population": {"population", "catchment_population"},
}

MISSING_STRINGS = {"", "na", "n/a", "nan", "null", "none", "-", "unknown?"}


def normalise_column_name(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name.strip("_")


def detect_mapping(df: pd.DataFrame) -> dict:
    """Return {canonical_field: original_column_name} for detected fields."""
    mapping = {}
    used = set()
    normalised = {col: normalise_column_name(col) for col in df.columns}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if col in used:
                continue
            if normalised[col] in aliases:
                mapping[canonical] = col
                used.add(col)
                break
    return mapping


def _is_missing_series(s: pd.Series) -> pd.Series:
    missing = s.isna()
    if s.dtype == object:
        as_str = s.fillna("").astype(str).str.strip().str.lower()
        missing = missing | as_str.isin(MISSING_STRINGS)
    return missing


def standardise_sex(value) -> str | None:
    if pd.isna(value):
        return None
    v = str(value).strip().lower()
    if v in {"m", "male"}:
        return "Male"
    if v in {"f", "female"}:
        return "Female"
    return None  # invalid / unrecognised


def standardise_district(value) -> str | None:
    if pd.isna(value):
        return None
    v = re.sub(r"\s+", " ", str(value).strip())
    if not v or v.lower() in MISSING_STRINGS:
        return None
    return _DISTRICT_BY_LOWER.get(v.lower(), v.title())


def canonicalise(df: pd.DataFrame, mapping: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """
    Return a copy of df with extra canonical columns added:
    _disease, _district, _region, _period_date (datetime), _date_reported,
    _cases (float), _deaths, _sex, _age_group.

    Original columns are never modified - this keeps analysis transparent
    and lets the UI show the user's original data unchanged.
    """
    if mapping is None:
        mapping = detect_mapping(df)
    out = df.copy()

    def text_col(field, standardiser=None):
        if field not in mapping:
            return pd.Series([None] * len(out), index=out.index, dtype=object)
        s = out[mapping[field]]
        if standardiser:
            return s.map(standardiser)
        return s.map(lambda v: None if pd.isna(v) or str(v).strip().lower() in MISSING_STRINGS
                     else str(v).strip())

    out["_disease"] = text_col("disease", lambda v: None if pd.isna(v)
                               else (str(v).strip().title() or None))
    out["_district"] = text_col("district", standardise_district)
    out["_sex"] = text_col("sex", standardise_sex)
    out["_age_group"] = text_col("age_group")
    out["_facility"] = text_col("facility")

    # Region: use the file's region if present, otherwise derive from district.
    region = text_col("region")
    derived = out["_district"].map(lambda d: MALAWI_DISTRICTS.get(d) if d else None)
    out["_region"] = region.where(region.notna() & (region != None), derived)  # noqa: E711
    out["_region"] = [r if (r is not None and not (isinstance(r, float) and np.isnan(r))) else d
                      for r, d in zip(region, derived)]

    for field, canon in (("period_date", "_period_date"),
                         ("date_reported", "_date_reported")):
        if field in mapping:
            out[canon] = pd.to_datetime(out[mapping[field]], errors="coerce",
                                        format="mixed")
        else:
            out[canon] = pd.NaT

    if "cases" in mapping:
        out["_cases_raw"] = out[mapping["cases"]]
        out["_cases"] = pd.to_numeric(out[mapping["cases"]], errors="coerce")
    else:
        # Line-list mode: every row counts as one case.
        out["_cases_raw"] = 1
        out["_cases"] = 1.0

    if "deaths" in mapping:
        out["_deaths"] = pd.to_numeric(out[mapping["deaths"]], errors="coerce")
    else:
        out["_deaths"] = np.nan

    return out, mapping


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------
def profile_dataframe(df: pd.DataFrame) -> dict:
    n_rows, n_cols = df.shape
    columns = []
    total_missing = 0
    for col in df.columns:
        s = df[col]
        miss = int(_is_missing_series(s).sum())
        total_missing += miss
        examples = [str(v) for v in s.dropna().astype(str).unique()[:3]]
        columns.append({
            "name": str(col),
            "dtype": str(s.dtype),
            "missing": miss,
            "missing_pct": round(100 * miss / n_rows, 2) if n_rows else 0.0,
            "unique": int(s.nunique(dropna=True)),
            "examples": examples,
        })
    total_cells = int(n_rows * n_cols)
    return {
        "rows": int(n_rows),
        "columns": int(n_cols),
        "total_cells": total_cells,
        "missing_cells": int(total_missing),
        "completeness_pct": round(100 * (1 - total_missing / total_cells), 2)
        if total_cells else 100.0,
        "per_column": sorted(columns, key=lambda c: -c["missing_pct"]),
    }


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 2) if whole else 0.0


def data_quality(df: pd.DataFrame, mapping: dict | None = None) -> dict:
    """
    Compute WHO-style data-quality dimensions.

    Overall score weights (renormalised if a dimension is not assessable):
        completeness 30, validity 25, uniqueness 20, timeliness 15,
        consistency 10.  Outliers are reported for review but do NOT lower
        the score - an outlier may be a real outbreak, not an error.
    """
    profile = profile_dataframe(df)
    cdf, mapping = canonicalise(df, mapping)
    n = len(df)
    has_cases_col = "cases" in mapping

    # Completeness dimension = % of records with every KEY field present.
    # (Cell-level completeness is still reported in the profile.) Key fields
    # are the ones needed for disease-pattern analysis, when mapped.
    _key_canon = {"disease": "_disease", "district": "_district",
                  "period_date": "_period_date", "cases": "_cases",
                  "sex": "_sex", "age_group": "_age_group"}
    key_fields = [f for f in _key_canon if f in mapping]
    if key_fields and n:
        complete_mask = pd.Series(True, index=cdf.index)
        for f in key_fields:
            complete_mask &= cdf[_key_canon[f]].notna()
        complete_records_pct = round(100 * float(complete_mask.mean()), 2)
        incomplete_records = int((~complete_mask).sum())
    else:
        complete_records_pct = profile["completeness_pct"]
        incomplete_records = 0

    # --- duplicates -------------------------------------------------------
    dup_excess = int(df.duplicated(keep="first").sum()) if n else 0

    # --- validity -----------------------------------------------------------
    validity_rows = set()
    negative_cases = non_numeric_cases = future_dates = 0
    invalid_sex = invalid_district = 0
    if has_cases_col:
        raw = df[mapping["cases"]]
        raw_missing = _is_missing_series(raw)
        coerced_missing = cdf["_cases"].isna()
        non_numeric_mask = (~raw_missing) & coerced_missing
        non_numeric_cases = int(non_numeric_mask.sum())
        validity_rows |= set(df.index[non_numeric_mask])
        neg_mask = cdf["_cases"] < 0
        negative_cases = int(neg_mask.fillna(False).sum())
        validity_rows |= set(df.index[neg_mask.fillna(False)])
    if "period_date" in mapping:
        today = pd.Timestamp(date.today())
        fut_mask = cdf["_period_date"] > today
        future_dates = int(fut_mask.fillna(False).sum())
        validity_rows |= set(df.index[fut_mask.fillna(False)])
    if "sex" in mapping:
        raw_sex_missing = _is_missing_series(df[mapping["sex"]])
        bad_sex = (~raw_sex_missing) & cdf["_sex"].isna()
        invalid_sex = int(bad_sex.sum())
        validity_rows |= set(df.index[bad_sex])
    unknown_districts = []
    if "district" in mapping:
        present = cdf["_district"].dropna()
        unknown_mask = ~cdf["_district"].isin(MALAWI_DISTRICTS) & cdf["_district"].notna()
        invalid_district = int(unknown_mask.sum())
        validity_rows |= set(df.index[unknown_mask.fillna(False)])
        unknown_districts = sorted(present[~present.isin(MALAWI_DISTRICTS)].unique().tolist())[:20]
    validity_score = round(100 * (1 - len(validity_rows) / n), 2) if n else 100.0

    # --- consistency --------------------------------------------------------
    consistency_rows = set()
    deaths_exceed = 0
    if "deaths" in mapping and has_cases_col:
        # Only compare against valid case counts: a negative count is already
        # reported as a validity error and must not double-count here.
        mask = ((cdf["_deaths"] > cdf["_cases"]) & (cdf["_cases"] >= 0)
                & cdf["_deaths"].notna() & cdf["_cases"].notna())
        deaths_exceed = int(mask.fillna(False).sum())
        consistency_rows |= set(df.index[mask.fillna(False)])
    conflict_rows = 0
    group_keys = [k for k in ("_district", "_disease", "_sex", "_age_group", "_facility")
                  if mapping.get({"_district": "district", "_disease": "disease",
                                  "_sex": "sex", "_age_group": "age_group",
                                  "_facility": "facility"}[k])]
    if has_cases_col and "_period_date" in cdf and group_keys and n:
        tmp = cdf.copy()
        tmp["_ym"] = tmp["_period_date"].dt.strftime("%Y-%m")
        grouped = tmp.groupby(group_keys + ["_ym"], dropna=False)["_cases"].nunique()
        conflict_keys = grouped[grouped > 1].index
        if len(conflict_keys):
            key_frame = tmp.set_index(group_keys + ["_ym"])
            mask = key_frame.index.isin(conflict_keys)
            conflict_rows = int(mask.sum())
            # A repeated submission for the same group/month with a different
            # total is only a consistency concern, so record involved rows.
            consistency_rows |= set(tmp.index[mask])
    consistency_score = round(100 * (1 - len(consistency_rows) / n), 2) if n else 100.0

    # --- outliers (IQR per disease & district time series) ------------------
    # Grouping by district as well means a value is only "unusual" compared
    # with that district's own history for that disease - a big district is
    # not flagged simply for being bigger than a small district.
    outliers = []
    if has_cases_col and n:
        # Compare like with like: same disease, district, sex and age group.
        group_cols = [c for c, f in (("_disease", "disease"), ("_district", "district"),
                                     ("_sex", "sex"), ("_age_group", "age_group"))
                      if f in mapping]
        groups = cdf.groupby(group_cols) if group_cols else [("All", cdf)]
        for _, grp in groups:
            vals = grp["_cases"].dropna()
            vals = vals[vals >= 0]
            if len(vals) < 8:
                continue
            q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
            iqr = q3 - q1
            if iqr <= 0:
                continue
            # 3 x IQR (extreme outliers) rather than 1.5 x IQR: seasonal
            # diseases such as malaria legitimately peak in the rainy
            # season, and 1.5 x IQR would flag many true seasonal peaks.
            lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
            flagged = grp[(grp["_cases"] < lo) | (grp["_cases"] > hi)]
            for idx, row in flagged.iterrows():
                outliers.append({
                    "row": int(idx) + 2,  # spreadsheet row (header = row 1)
                    "disease": row.get("_disease"),
                    "district": row.get("_district"),
                    "period": (row["_period_date"].strftime("%Y-%m")
                               if pd.notna(row.get("_period_date")) else None),
                    "cases": float(row["_cases"]),
                    "expected_max": round(float(hi), 1),
                })
    outliers.sort(key=lambda o: -o["cases"])

    # --- timeliness -----------------------------------------------------------
    timeliness = {"assessable": False, "score": None, "late_rows": 0,
                  "late_pct": None, "median_delay_days": None,
                  "note": "Not assessable: dataset needs both a period date "
                          "and a date-reported column."}
    if "period_date" in mapping and "date_reported" in mapping and n:
        both = cdf[cdf["_period_date"].notna() & cdf["_date_reported"].notna()].copy()
        if len(both):
            month_end = both["_period_date"] + pd.offsets.MonthEnd(0)
            delay = (both["_date_reported"] - month_end).dt.days
            late = delay > 15  # monthly report due 15 days after month end
            timeliness = {
                "assessable": True,
                "score": round(100 * (1 - float(late.mean())), 2),
                "late_rows": int(late.sum()),
                "late_pct": round(100 * float(late.mean()), 2),
                "median_delay_days": float(delay.median()),
                "note": "Late = reported more than 15 days after the end of "
                        "the reporting month (period_date is treated as the "
                        "reporting month).",
            }

    completeness = complete_records_pct
    uniqueness = round(100 * (1 - dup_excess / n), 2) if n else 100.0

    parts = [("completeness", completeness, 30), ("validity", validity_score, 25),
             ("uniqueness", uniqueness, 20), ("consistency", consistency_score, 10)]
    if timeliness["assessable"]:
        parts.append(("timeliness", timeliness["score"], 15))
    total_weight = sum(w for _, _, w in parts)
    overall = round(sum(s * w for _, s, w in parts) / total_weight, 2) if total_weight else 100.0
    # Strict bands: routine health data used for planning should be held to
    # a high standard, so "Excellent" starts at 95.
    rating = ("Excellent" if overall >= 95 else "Good" if overall >= 85
              else "Fair" if overall >= 70 else "Needs attention")

    checks = [
        {"check": "Records missing a key field", "affected": incomplete_records,
         "pct": _pct(incomplete_records, n),
         "meaning": "Key fields used: " + (", ".join(key_fields) or "none mapped")
                    + ". Cell-level completeness is shown in the dataset profile."},
        {"check": "Missing values (all cells)", "affected": profile["missing_cells"],
         "pct": _pct(profile["missing_cells"], profile["total_cells"]),
         "meaning": "Empty cells reduce what can be analysed."},
        {"check": "Exact duplicate rows", "affected": dup_excess, "pct": _pct(dup_excess, n),
         "meaning": "Repeated rows can double-count cases."},
        {"check": "Negative case counts", "affected": negative_cases,
         "pct": _pct(negative_cases, n), "meaning": "Case counts cannot be below zero."},
        {"check": "Non-numeric case counts", "affected": non_numeric_cases,
         "pct": _pct(non_numeric_cases, n), "meaning": "Text where a number is expected."},
        {"check": "Future period dates", "affected": future_dates,
         "pct": _pct(future_dates, n), "meaning": "Dates after today suggest entry errors."},
        {"check": "Unrecognised sex values", "affected": invalid_sex,
         "pct": _pct(invalid_sex, n), "meaning": "Values other than Male/Female (or M/F)."},
        {"check": "Districts not in Malawi list", "affected": invalid_district,
         "pct": _pct(invalid_district, n),
         "meaning": "Spelling errors or areas outside the 28 Malawi districts."},
        {"check": "Deaths greater than cases", "affected": deaths_exceed,
         "pct": _pct(deaths_exceed, n), "meaning": "Internally inconsistent record."},
        {"check": "Conflicting totals (same group & month)", "affected": conflict_rows,
         "pct": _pct(conflict_rows, n),
         "meaning": "Same district/disease/month submitted with different totals."},
        {"check": "Late reports", "affected": timeliness["late_rows"],
         "pct": timeliness["late_pct"] if timeliness["assessable"] else None,
         "meaning": timeliness["note"]},
        {"check": "Possible outliers (review, not automatic errors)",
         "affected": len(outliers), "pct": _pct(len(outliers), n),
         "meaning": "Extreme values for the same disease/district/sex/age group "
                    "(beyond 3 x IQR, chosen to avoid flagging normal seasonal "
                    "peaks). May be a real outbreak - verify before removing."},
    ]

    return {
        "mapping": mapping,
        "profile": profile,
        "overall_score": overall,
        "rating": rating,
        "dimensions": {
            "completeness": completeness,
            "validity": validity_score,
            "uniqueness": uniqueness,
            "consistency": consistency_score,
            "timeliness": timeliness["score"],
        },
        "score_weights": {name: w for name, _, w in parts},
        "complete_records_pct": complete_records_pct,
        "key_fields": key_fields,
        "missing_by_column": profile["per_column"],
        "duplicates": dup_excess,
        "timeliness": timeliness,
        "outliers": outliers[:25],
        "outlier_count": len(outliers),
        "unknown_districts": unknown_districts,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Disease patterns
# ---------------------------------------------------------------------------
def _group_sum(cdf: pd.DataFrame, col: str, limit: int | None = None) -> list[dict]:
    if col not in cdf or cdf[col].dropna().empty:
        return []
    s = cdf.groupby(col, dropna=True)["_cases"].sum().sort_values(ascending=False)
    if limit:
        s = s.head(limit)
    return [{"label": str(k), "value": float(v)} for k, v in s.items()]


def apply_filters(cdf: pd.DataFrame, filters: dict) -> pd.DataFrame:
    out = cdf
    for field, col in (("disease", "_disease"), ("district", "_district"),
                       ("region", "_region"), ("sex", "_sex"),
                       ("age_group", "_age_group")):
        value = (filters or {}).get(field)
        if value:
            out = out[out[col].astype(str) == str(value)]
    start, end = (filters or {}).get("date_from"), (filters or {}).get("date_to")
    if start:
        out = out[out["_period_date"] >= pd.Timestamp(start)]
    if end:
        out = out[out["_period_date"] <= pd.Timestamp(end) + pd.offsets.MonthEnd(0)]
    return out


def filter_options(cdf: pd.DataFrame) -> dict:
    def opts(col):
        if col not in cdf:
            return []
        return sorted([str(v) for v in cdf[col].dropna().unique().tolist()])
    return {
        "disease": opts("_disease"), "district": opts("_district"),
        "region": opts("_region"), "sex": opts("_sex"),
        "age_group": opts("_age_group"),
        "date_min": (cdf["_period_date"].min().strftime("%Y-%m")
                     if cdf["_period_date"].notna().any() else None),
        "date_max": (cdf["_period_date"].max().strftime("%Y-%m")
                     if cdf["_period_date"].notna().any() else None),
    }


def disease_patterns(df: pd.DataFrame, filters: dict | None = None,
                     mapping: dict | None = None) -> dict:
    cdf_all, mapping = canonicalise(df, mapping)
    options = filter_options(cdf_all)
    cdf = apply_filters(cdf_all, filters or {})
    # Analytically valid records for case totals: non-negative cases and not
    # future-dated. Invalid records are still counted in "records" and in
    # the data-quality module - they are never silently hidden.
    today = pd.Timestamp(date.today())
    valid_mask = ((cdf["_cases"].fillna(0) >= 0)
                  & (cdf["_period_date"].isna() | (cdf["_period_date"] <= today)))
    valid = cdf[valid_mask]

    total_cases = float(valid["_cases"].sum()) if len(valid) else 0.0
    total_deaths = float(valid["_deaths"].sum()) if valid["_deaths"].notna().any() else None

    # Monthly trend with gaps filled as zero
    trend = []
    if valid["_period_date"].notna().any():
        s = valid.groupby(valid["_period_date"].dt.to_period("M"))["_cases"].sum()
        full = pd.period_range(s.index.min(), s.index.max(), freq="M")
        s = s.reindex(full, fill_value=0)
        trend = [{"label": str(p), "value": float(v)} for p, v in s.items()]

    seasonality = []
    if valid["_period_date"].notna().any():
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        s = valid.groupby(valid["_period_date"].dt.month)["_cases"].sum().reindex(range(1, 13), fill_value=0)
        seasonality = [{"label": month_names[m - 1], "value": float(s[m])} for m in range(1, 13)]

    by_disease = _group_sum(valid, "_disease")
    by_district = _group_sum(valid, "_district", limit=15)

    # Heatmap: top districts x top diseases
    heatmap = {"districts": [], "diseases": [], "cells": []}
    if by_disease and by_district:
        top_d = [d["label"] for d in by_disease[:6]]
        top_dist = [d["label"] for d in by_district[:10]]
        sub = valid[valid["_disease"].isin(top_d) & valid["_district"].isin(top_dist)]
        pivot = sub.pivot_table(index="_district", columns="_disease",
                                values="_cases", aggfunc="sum", fill_value=0)
        heatmap = {
            "districts": [d for d in top_dist if d in pivot.index],
            "diseases": [d for d in top_d if d in pivot.columns],
            "cells": [[float(pivot.loc[dist, dis]) if dist in pivot.index and dis in pivot.columns else 0
                       for dis in top_d if dis in pivot.columns]
                      for dist in top_dist if dist in pivot.index],
        }

    # District table combining burden + data quality (key proposal idea).
    # Completeness here = % of the district's records with all key fields.
    district_table = []
    if "_district" in cdf_all and cdf_all["_district"].notna().any():
        key_cols = ["_disease", "_district", "_period_date", "_cases"]
        for extra in ("_sex", "_age_group"):
            if mapping.get("sex" if extra == "_sex" else "age_group"):
                key_cols.append(extra)
        for dist, grp in cdf.groupby("_district", dropna=True):
            complete_pct = round(100 * float(grp[key_cols].notna().all(axis=1).mean()), 1)
            grp_valid = grp[valid_mask.loc[grp.index]]
            top_disease = None
            if grp_valid["_disease"].notna().any():
                top_disease = str(grp_valid.groupby("_disease")["_cases"].sum().idxmax())
            district_table.append({
                "district": str(dist),
                "region": MALAWI_DISTRICTS.get(str(dist), "-"),
                "records": int(len(grp)),
                "cases": float(grp_valid["_cases"].sum()),
                "top_disease": top_disease,
                "completeness_pct": complete_pct,
            })
        district_table.sort(key=lambda r: -r["cases"])

    insights = []
    if total_cases and by_disease:
        top = by_disease[0]
        insights.append(f"{top['label']} accounts for "
                        f"{round(100 * top['value'] / total_cases, 1)}% of reported cases "
                        "in the current filter selection.")
    if total_cases and by_district:
        top = by_district[0]
        insights.append(f"{top['label']} reports the highest burden "
                        f"({int(top['value']):,} cases, "
                        f"{round(100 * top['value'] / total_cases, 1)}% of the total).")
    if trend and len(trend) >= 6:
        first = np.mean([t["value"] for t in trend[:3]])
        last = np.mean([t["value"] for t in trend[-3:]])
        if first > 0:
            change = round(100 * (last - first) / first, 1)
            direction = "increased" if change > 0 else "decreased"
            insights.append(f"Comparing the first and last 3 months, average monthly "
                            f"cases {direction} by {abs(change)}%.")
    low_quality = sorted((r for r in district_table if r["completeness_pct"] < 90),
                         key=lambda r: r["completeness_pct"])
    if low_quality:
        names = ", ".join(f"{r['district']} ({r['completeness_pct']}%)"
                          for r in low_quality[:3])
        insights.append(f"Caution: record completeness is lowest for {names} - "
                        "interpret their disease patterns together with the "
                        "data-quality results before drawing conclusions.")

    return {
        "mapping": mapping,
        "filter_options": options,
        "filters_applied": {k: v for k, v in (filters or {}).items() if v},
        "kpis": {
            "total_cases": total_cases,
            "total_deaths": total_deaths,
            "case_fatality_pct": (round(100 * total_deaths / total_cases, 2)
                                  if total_deaths is not None and total_cases else None),
            "records": int(len(cdf)),
            "diseases": int(valid["_disease"].nunique(dropna=True)),
            # Only recognised districts count toward "districts covered";
            # unrecognised values (e.g. a city label) are reported separately.
            "districts": int(len(set(valid["_district"].dropna()) & set(MALAWI_DISTRICTS))),
            "unrecognised_district_values": int(
                len(set(valid["_district"].dropna()) - set(MALAWI_DISTRICTS))),
            "period_start": trend[0]["label"] if trend else None,
            "period_end": trend[-1]["label"] if trend else None,
        },
        "trend_monthly": trend,
        "seasonality": seasonality,
        "by_disease": by_disease,
        "by_district": by_district,
        "by_region": _group_sum(valid, "_region"),
        "by_sex": _group_sum(valid, "_sex"),
        "by_age_group": _group_sum(valid, "_age_group"),
        "heatmap": heatmap,
        "district_table": district_table,
        "insights": insights,
    }


# ---------------------------------------------------------------------------
# Cleaning (transparent: formats standardised, records never silently lost)
# ---------------------------------------------------------------------------
def clean_dataframe(df: pd.DataFrame, drop_duplicates: bool = False,
                    mapping: dict | None = None) -> tuple[pd.DataFrame, list[dict]]:
    log = []
    out = df.copy()
    cdf, mapping = canonicalise(df, mapping)

    trimmed = 0
    for col in out.columns:
        if out[col].dtype == object:
            before = out[col].fillna("")
            after = before.map(lambda v: str(v).strip() if isinstance(v, str) else v)
            trimmed += int((before.astype(str) != after.astype(str)).sum())
            out[col] = out[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    log.append({"action": "Trimmed leading/trailing spaces in text cells",
                "affected": trimmed})

    rename = {}
    if "sex" in mapping:
        col = mapping["sex"]
        changed = int((cdf["_sex"].notna() &
                       (out[col].astype(str) != cdf["_sex"].astype(str))).sum())
        out[col] = cdf["_sex"]
        log.append({"action": "Standardised sex values to Male/Female "
                              "(unrecognised values left blank)", "affected": changed})
        rename[col] = "sex"
    if "district" in mapping:
        col = mapping["district"]
        changed = int((cdf["_district"].notna() &
                       (out[col].astype(str) != cdf["_district"].astype(str))).sum())
        out[col] = cdf["_district"]
        log.append({"action": "Standardised district names against the 28 "
                              "Malawi districts", "affected": changed})
        rename[col] = "district"
    if "disease" in mapping:
        rename[mapping["disease"]] = "disease"
        out[mapping["disease"]] = cdf["_disease"]
    for field in ("period_date", "date_reported"):
        if field in mapping:
            col = mapping[field]
            out[col] = cdf["_" + field].dt.strftime("%Y-%m-%d")
            bad = int(cdf["_" + field].isna().sum() -
                      _is_missing_series(df[col]).sum())
            log.append({"action": f"Reformatted {field} to YYYY-MM-DD "
                                  "(unparseable dates left blank)",
                        "affected": max(bad, 0)})
            rename[col] = field
    if "cases" in mapping:
        col = mapping["cases"]
        neg = int((cdf["_cases"] < 0).fillna(False).sum())
        cleaned_cases = cdf["_cases"].where(cdf["_cases"] >= 0)
        out[col] = cleaned_cases
        log.append({"action": "Coerced cases to numbers; negative values set "
                              "blank for follow-up (rows kept)", "affected": neg})
        rename[col] = "cases"
    if "deaths" in mapping:
        out[mapping["deaths"]] = cdf["_deaths"].where(cdf["_deaths"] >= 0)
        rename[mapping["deaths"]] = "deaths"
    if "age_group" in mapping:
        rename[mapping["age_group"]] = "age_group"
    if "region" in mapping:
        rename[mapping["region"]] = "region"

    if drop_duplicates:
        before = len(out)
        out = out.drop_duplicates(keep="first")
        log.append({"action": "Removed exact duplicate rows (user requested)",
                    "affected": before - len(out)})
    else:
        log.append({"action": "Exact duplicate rows kept (tick 'drop duplicates' "
                              "to remove them in the export)",
                    "affected": int(out.duplicated(keep="first").sum())})

    out = out.rename(columns={k: v for k, v in rename.items()
                              if v not in out.columns or k == v})
    return out.reset_index(drop=True), log


def analyse_dataframe(df: pd.DataFrame, filters: dict | None = None) -> dict:
    """Convenience wrapper used by the API and by external Python code."""
    mapping = detect_mapping(df)
    return {
        "mapping": mapping,
        "quality": data_quality(df, mapping),
        "patterns": disease_patterns(df, filters or {}, mapping),
    }
