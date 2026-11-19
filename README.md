# Health and Disease Analytics — Malawi

**Designing and Implementation of a Web-Based Exploratory Data Analysis
Dashboard for Public Health Data Quality and Disease Pattern Analysis in Malawi**

| | |
|---|---|
| Student | **Eid Kusweje** (Reg. 24311351003) |
| Program | Bachelor of Science in Computer Science |
| Guide | Mr Bester Sinkhonde |
| Alignment | Malawi 2063 — digital transformation & evidence-based health management |
| Stack | Python · Flask · Pandas/NumPy · SQLite · HTML/CSS/JavaScript (SVG charts) |

A working, testable web application that answers two questions *together*:

1. **What is happening?** — disease trends over time and comparisons across Malawi districts.
2. **Can we trust the data behind it?** — completeness, validity, uniqueness,
   consistency, timeliness and outlier checks on the same dataset.

It complements DHIS2/HMIS (it analyses de-identified exports); it does not
replace them, diagnose patients, or declare outbreaks.

---

## 1. Run the system (final-test quick start)

```bash
cd malawi-health-analytics
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** and sign in:

| Role | Email | Password | Can do |
|---|---|---|---|
| Administrator | `admin@demo.mw` | `Admin123!` | Everything + users, audit log, DB backup |
| Analyst | `analyst@demo.mw` | `Analyst123!` | Upload, analyse, clean, export |
| Viewer | `viewer@demo.mw` | `Viewer123!` | View dashboards & summaries only |

On first run the SQLite database is created at `instance/app.sqlite3`, the
three accounts above are created, and the **synthetic Malawi demo dataset**
(17,545 rows, 12 districts, 6 diseases, Jan 2023 – Jun 2025, with
*deliberately planted* data-quality problems) is loaded automatically.
Delete `instance/app.sqlite3` to reset to this pristine state.

**5-minute test:** follow *Help & Test Guide* inside the app, or
[docs/TEST_PLAN_AND_RESULTS.md](docs/TEST_PLAN_AND_RESULTS.md).

## 2. Run the automated tests

```bash
python -m pytest -q        # 21 tests: analysis units + API/RBAC/auth flow (incl. embedded-login regression)
python seed.py             # (re)generate sample_data/*.csv deterministically
```

Test evidence (planted-error → expected-result tables) is in
[docs/TEST_PLAN_AND_RESULTS.md](docs/TEST_PLAN_AND_RESULTS.md).

## 3. What is implemented (all 8 proposal modules)

| Proposal module | Where it lives |
|---|---|
| 1. Authentication & access control | `app.py` (session auth), `db.py` (PBKDF2 hashes, roles admin/analyst/viewer) |
| 2. Dataset management | Datasets view — CSV/XLSX/XLS upload (20 MB), preview, column profile, delete |
| 3. Validation & cleaning | `analysis.clean_dataframe` — transparent log, rows never silently dropped |
| 4. Data-quality analysis | `analysis.data_quality` — 5 weighted dimensions + 12 counted checks + outliers |
| 5. Disease-pattern analysis | `analysis.disease_patterns` — trend, seasonality, district/age/sex, heatmap |
| 6. Interactive dashboard | `static/` — sidebar + KPI cards + SVG charts + filters (no JS libraries) |
| 7. Report generation & export | Printable report (browser → PDF), cleaned CSV, DQ/pattern summary CSVs |
| 8. Administration | Admin view — users, activation, audit log, system info, **SQLite backup download** |

Key design feature from the proposal: the **district table shows burden and
record-completeness side by side** (e.g. Mangochi in the demo data has a
malaria spike *and* ≈66% completeness), so a pattern is never interpreted
without its data quality.

## 4. Data the system accepts

De-identified CSV/Excel with any of these columns (aliases matched
case-insensitively — `Diagnosis`, `Gender`, `Reporting Period`, `Value`, …):

`district, region, disease, period_date, date_reported, sex, age_group,
cases, deaths` (+ optional `facility`, `population`)

* `sample_data/data_template.csv` — 2-row template (also downloadable in-app)
* `sample_data/test_dirty_data.csv` — 21 rows with one of almost every error
* `sample_data/malawi_synthetic_health_data.csv` — full demo dataset
* Files with personal identifiers (`patient_name`, `phone`, `national_id`,
  `address`, …) are **refused**. Without a `cases` column each row counts as
  one case (line-list mode). Missing dimensions are reported as
  *“not assessable”* rather than guessed.

## 5. Python integration

The analysis layer is framework-free and importable from any Python program:

```python
import pandas as pd
from analysis import analyse_dataframe

result = analyse_dataframe(pd.read_csv("my_export.csv"))
print(result["quality"]["overall_score"], result["quality"]["rating"])
print(result["patterns"]["by_disease"][:3])
```

The same results are exposed as a JSON REST API (authenticate first):

```
GET  /api/health
POST /api/auth/login · POST /api/auth/logout · GET /api/me
GET  /api/datasets · POST /api/datasets/upload (multipart)
GET  /api/datasets/<id>/preview?page=1
GET  /api/datasets/<id>/overview | /quality
GET  /api/datasets/<id>/patterns?disease=Malaria&district=Mangochi&sex=Female
GET  /api/datasets/<id>/cleaned.csv?drop_duplicates=1   (or ?log=1 for the JSON log)
GET  /api/datasets/<id>/quality-summary.csv · /pattern-summary.csv
GET  /api/admin/users · /api/admin/audit · /api/admin/backup.sqlite3   (admin)
```

## 6. Database strategy (SQLite now, PostgreSQL-ready)

Per the implementation notes, **SQLite is the test database and the built-in
backup database**: zero-install, one file (`instance/app.sqlite3`),
downloadable from the Admin page; restore by replacing that file while the
server is stopped. All SQL is isolated in `db.py` using standard SQL and
parameterised queries, so moving users/dataset-metadata to PostgreSQL later
(the deployment option in the concept document) means re-implementing only
that one module. Uploaded dataset *files* live in `instance/uploads/`;
analysis always reads them with Pandas, independent of the metadata DB.

## 7. Project structure

```
malawi-health-analytics/
├── app.py                  Flask app + REST API (create_app factory for tests)
├── analysis.py             PURE Pandas logic: mapping, quality, patterns, cleaning
├── db.py                   SQLite layer (users, datasets, audit) — the only SQL
├── seed.py                 Demo users + deterministic synthetic dataset generator
├── requirements.txt
├── static/                 index.html · style.css · app.js (SVG charts, no libraries)
├── sample_data/            demo data · dirty test file · CSV template
├── tests/                  test_analysis.py (12) · test_api.py (9)
├── examples/               python_integration_example.py (no server needed)
├── run.bat / run.sh        one-click launchers (install deps + start server)
└── docs/                   SYSTEM_DESIGN.md · USER_GUIDE.md · TEST_PLAN_AND_RESULTS.md
└── instance/               created at runtime: app.sqlite3 + uploads/ (not zipped)
```

## 8. Design rules applied (from the supplied references)

* **Colours — palette only:** `#65524D` Taupe grey, `#5878E9` Crayola Blue,
  `#7FC29B` Muted Teal, `#B5EF8A` Light Green, `#D7F171` Lime Cream, plus
  white and flat tints of those colours. No other hues. **No gradients.**
* **Typography — one family:** Arial/Helvetica/sans-serif at every size/weight.
* **Layout — after the supplied dashboard inspiration:** white sidebar with
  pill navigation, four KPI cards with flat icon chips, trend + donut row,
  dimension bars, statistics table. Clinical widgets were replaced by the
  proposal's data-quality/disease-pattern content.
* **Low bandwidth:** one small CSS + one JS file, inline SVG only, no CDN,
  no web fonts, no external images — it runs fully offline.

Verification of these rules (grep evidence) is in
[docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md#7-design-system-evidence).

## 9. Scope & ethics

Synthetic/de-identified aggregate data only. EDA findings are exploratory
observations — not proof of causation and dependent on data quality, case
definitions and reporting coverage. Change `SECRET_KEY` (environment
variable) and use HTTPS + a production WSGI server (e.g. gunicorn) for any
real deployment; the built-in server is for testing/demonstration.
