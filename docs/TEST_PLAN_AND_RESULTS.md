# Test Plan and Results

**System:** Health and Disease Analytics (Malawi) · **Build tested:** 2 Nov 2026
**Run everything:** `pip install -r requirements.txt && python -m pytest -q`
**Automated result: 21 passed, 0 failed** (12 analysis unit tests + 9 API tests).

## 1. Test strategy
| Level | Tool | What it proves |
|---|---|---|
| Unit | pytest + Pandas fixtures (`tests/test_analysis.py`) | Every data-quality check finds exactly the planted error; filters/totals arithmetic is exact |
| Expected-result files | `sample_data/test_dirty_data.csv`, demo dataset | Whole-pipeline results match a hand-computed expectation table (§3) |
| API/integration | Flask test client + temp SQLite (`tests/test_api.py`) | Auth, RBAC, upload validation, exports, admin, backup — without touching the real DB |
| Manual UAT | Checklist in §4 (also in-app under Help) | The exact click-path an examiner can repeat in 5 minutes |

## 2. Automated test inventory
**test_analysis.py:** alias column-mapping · missing/duplicate/completeness
counts · six validity/consistency checks each finding exactly 1 planted
error · timeliness 15-day rule (1 on-time + 1 late → 50.0) · timeliness
*not assessable* path + weight renormalisation · 900-vs-~10 outlier spike
flagged first · pattern totals with negatives excluded (100+50+20=170;
Malaria filter = 150) · zero-filled missing month in trend · line-list
mode (3 rows → 3 cases) · cleaning standardisation keeping rows ·
duplicate removal only on request · dirty-file expectation table ·
demo-dataset planted problems.

**test_api.py:** public health endpoint · 401 when logged out · wrong
password rejected · viewer upload → 403 · full upload→quality(100.0 on
clean file)→filtered patterns(150)→preview flow · patient-name file →
422 “de-identified” · `.txt` → 400 · 1-column file → 422 · cleaned/DQ/
pattern CSV exports 200 · delete then 404 · analyst blocked from admin
endpoints (403) · admin creates user, duplicate email → 409 · SQLite
backup downloads and starts with the `SQLite` file signature.

Bugs found by this suite during development (good viva material):
negative case counts were initially double-counted as “deaths > cases”
(fixed by comparing only valid counts); IQR outliers grouped only by
disease flagged large districts and rainy-season peaks (fixed: group by
disease+district+sex+age at 3×IQR); future-dated rows initially stretched
trends to 2099 (fixed: excluded from pattern totals, kept in DQ counts).

Post-release bug fixed in v1.0.1 (also good viva material — an environment
bug the test client could not see): when the dashboard runs **embedded in
a cross-site iframe (hosted live preview)**, the browser blocks the
third-party session cookie, so login returned 200 but the next API call
was 401 and the user bounced straight back to the login page (visible in
server logs as `POST /login 200` → `GET /api/datasets 401`). Fix: login
now also returns a revocable **Bearer token** (SHA-256 hash in SQLite,
7-day expiry) which the page sends as an `Authorization` header on every
call — including uploads/downloads — while routes identify the user via
`current_user()` instead of `session["user_id"]`; additionally the
session cookie is issued `SameSite=None; Secure` behind an HTTPS proxy
(and stays `Lax` on local HTTP). Locked in by two regression tests:
token-only auth with cookies deleted, and cookie attributes behind
`X-Forwarded-Proto: https`.

## 3. Expected results — know these numbers before your final test

### 3.1 `test_dirty_data.csv` (21 rows — upload it yourself in Datasets)
Overall score **85.0 (Good)** · completeness 76.19 · validity 80.95 ·
uniqueness 90.48 · consistency 95.24 · timeliness 95.24

| Check | Expected | Planted where |
|---|---|---|
| Records missing a key field | **5** (23.81%) | 3 blank cases + 1 “many” + 1 Unknown sex |
| Missing cells (total) | **3** | Zomba Feb, Mangochi Feb & Mar `cases` |
| Exact duplicate rows | **2** | Lilongwe Jan malaria row; Karonga Feb TB row |
| Negative cases | **1** | Zomba Diarrhoea Mar (−7) |
| Non-numeric cases | **1** | Blantyre Malaria Feb (“many”) |
| Future dates | **1** | Blantyre Cholera period 2099-01-01 |
| Unrecognised sex | **1** | “Unknown” (Blantyre City row) |
| Districts not in Malawi list | **1** → tag: *Blantyre City* | city used as district (`zomba ` with space is accepted after standardisation) |
| Deaths > cases | **1** | Mangochi Jan: 10 cases, 15 deaths |
| Late reports | **1** | Lilongwe Pneumonia Feb, reported 20 May |
| Pattern totals | **960 cases, 29 deaths, period 2025-01→2025-03** | negative & 2099 rows excluded from totals; Lilongwe top (549, 57.2%) |

### 3.2 Demo dataset (17,545 rows — loaded automatically)
Overall score **93.41 (Good)** · completeness 87.81 · validity 98.32 ·
uniqueness 98.75 · consistency 99.48 · timeliness 85.26 (weakest dimension)

* 723,784 cases · 8,270 deaths · CFR 1.14% · 2023-01 → 2025-06 · 12 of 28
  districts + 1 unrecognised district value (*Blantyre City*, 40 rows)
* 2,139 records missing a key field (12.19%) · 220 exact duplicates ·
  18 negative + 26 non-numeric case counts · 212 unrecognised sex values ·
  84 records in conflicting re-submitted totals · **2,587 late reports**
* Top outlier = planted **Mangochi malaria spike, 2024-02** (2,634 cases
  vs group’s usual max ≈504); 34 extreme outliers in total
* **Mangochi record completeness ≈ 65.8%** (every other district ≈ 89–90%)
  → the “Caution: completeness is lowest for Mangochi…” insight must appear
* Malaria is the top disease (50.3%); Lilongwe the top district (103,347)

## 4. Manual UAT checklist (final-test script, ≈5 minutes)
1. ☐ Sign in `analyst@demo.mw / Analyst123!` → Dashboard loads on demo data; score pill shows 93.4 · Good.
2. ☐ Dashboard: 4 KPI cards, trend line, disease donut, dimension bars, district table — spot **Mangochi ≈66%**.
3. ☐ Data Quality: score ring 93.4; timeliness is lowest; top outlier is Mangochi/Malaria/2024-02; unknown-district tag *Blantyre City*.
4. ☐ Disease Patterns: filter Disease = Malaria → apply → all KPIs/charts change and the filter pill names the selection; Clear restores.
5. ☐ Datasets: download template; upload `sample_data/test_dirty_data.csv`; verify §3.1 numbers on its Data Quality page.
6. ☐ Reports: view cleaning log, download cleaned CSV, print report → “Save as PDF” produces a clean one-document report.
7. ☐ Sign in as `viewer@demo.mw` → upload area replaced by a read-only notice; API upload would return 403.
8. ☐ Sign in as `admin@demo.mw` → create a user, deactivate them, check the audit log entries, download `backup_app.sqlite3`.
9. ☐ Offline check: disconnect internet, restart `python app.py`, repeat step 1 — everything still works (no external assets).
10. ☐ Reset check (optional): stop server, delete `instance/app.sqlite3`, restart — demo accounts + demo dataset are recreated.

## 5. Non-functional checks performed
* `python -m pytest -q` → **21 passed** (≈4 s) on Python 3.13.
* Live-server smoke test: health → login → overview JSON (score 93.41,
  30 trend points) → dirty-file upload (201) → homepage 200.
* Design compliance greps: palette hexes only (+ white), zero gradient
  CSS, one `font-family`, zero external URLs (see SYSTEM_DESIGN §7).
* Performance: overview of the 17,545-row demo set returns in ≈1 s locally.
