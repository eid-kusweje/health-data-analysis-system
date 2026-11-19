# User Guide — Health and Disease Analytics (Malawi)

## 1. Signing in
Open the system address given by your administrator (locally:
`http://127.0.0.1:5000`). Demo accounts are listed on the sign-in page.
**Viewer** accounts can explore everything but cannot upload, clean or
delete. Sign out from the card at the bottom of the left sidebar.

## 2. The active dataset
Every screen analyses the dataset chosen in the **Active dataset** box at
the top. Change it there, or with **Select** in the Datasets list. The
pill next to it always shows that dataset's data-quality score.

## 3. Dashboard
Your one-page situation summary: total cases, records analysed,
data-quality score, districts covered (of 28), the monthly trend, cases
by disease, the five quality dimensions, top districts, seasonality — and
the **district situation table**, which deliberately places each
district's case burden beside its record completeness. Read the “Key
observations” box before quoting any number from this page.

## 4. Datasets
* **Upload** a de-identified `.csv`, `.xlsx` or `.xls` (max 20 MB) by
  drag-and-drop or file picker. Files containing names, phone numbers,
  national IDs or addresses are refused — remove those columns first.
* Download the **CSV template** to see the expected columns. Common
  alternative headers work too (Diagnosis, Gender, Value, Reporting
  Period…); the mapping chips in the preview show what was detected.
* **Rows / Column profile** tabs show the raw data (missing cells are
  tagged) and per-column missing/unique statistics.
* Analysts can delete their own datasets; only administrators can delete
  the demo dataset.

## 5. Data Quality
* The **score ring** is the weighted overall score (Excellent ≥ 95,
  Good ≥ 85, Fair ≥ 70). Dimension bars show where points were lost.
* **Missing values by column** and **validity flags** tell you exactly
  what to fix at source; districts spelled outside the 28-district list
  are named (e.g. a city label used as a district).
* **All checks** counts every affected record — nothing is auto-fixed.
* **Outliers** are extreme values *for the same disease, district, sex
  and age group*. Verify them with the reporting unit: they may be a
  genuine outbreak. Row numbers match your spreadsheet (header = row 1).
* **Preview cleaning actions** shows precisely what the cleaned export
  changes. Cleaning standardises district names, sex values, dates and
  numbers; impossible numbers are blanked but the row is kept. Exact
  duplicates are removed only if you tick that option when exporting.

## 6. Disease Patterns
Use the filters (disease, district, region, sex, age group, from/to
month), then **Apply filters**. KPIs, trend, disease/district/sex/age
charts, seasonality, the district × disease **heatmap** and the district
table all describe the same filtered selection — the pill under the
filters restates it so screenshots stay interpretable. Negative and
future-dated records never enter case totals.

## 7. Reports & Export
* **Print / save as PDF** — a clean situation report (score, dimensions,
  headline numbers, top diseases/districts, interpretation, methods &
  limitations, Malawi 2063 alignment).
* **Cleaned CSV**, **data-quality summary CSV** and **disease-pattern
  summary CSV** for Excel/R/Python follow-up.

## 8. Administration (admin only)
Create/activate/deactivate users and roles, read the audit log (logins,
uploads, exports, deletions), check system counts, and **download a
backup** of the SQLite database. To restore: stop the server, replace
`instance/app.sqlite3` with the backup file, restart.

## 9. Troubleshooting
| Symptom | Likely cause & fix |
|---|---|
| Dashboard flashes then returns to login (embedded/hosted preview) | Fixed in v1.0.1: the page now signs in with a Bearer token, not only the session cookie that browsers block in cross-site iframes. If you still see it once, hard-refresh (Ctrl+Shift+R / Cmd+Shift+R) to replace the cached old `app.js`. |
| “Only accepts de-identified data…” | Your file has a name/phone/ID/address column — delete it and re-upload. |
| Timeliness says *not assessable* | The file lacks `date_reported` or `period_date`. Add the report/submission date column. |
| Trend chart is empty | No parseable `period_date` values (check date format: `2025-01-01` works). |
| A district is missing from the charts | Check its spelling in Data Quality → unknown districts (e.g. “Blantyre City”). |
| Cases look too low | Blank/non-numeric `cases` are excluded from totals — see Missing values by column. |
| Upload button disabled | You are signed in as a viewer. Ask an admin for an analyst account. |

## 10. Good practice
Interpret patterns *with* their quality score; footnote the score,
completeness and late-report rate in any brief you write from this tool;
never upload identifiable patient data; and remember that a rise in
reported cases can mean better reporting, not only more disease.
