"""API / integration tests using Flask's test client and a temporary
SQLite database (the real instance database is never touched)."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db as dbmod          # noqa: E402
from app import create_app  # noqa: E402

CSV = (b"district,disease,period_date,date_reported,sex,age_group,cases,deaths\n"
       b"Lilongwe,Malaria,2025-01-01,2025-02-05,Female,0-4,100,2\n"
       b"Zomba,Cholera,2025-01-01,2025-02-05,Male,15-49,20,1\n"
       b"Zomba,Malaria,2025-02-01,2025-03-05,Female,0-4,50,0\n")


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    app = create_app(db_path=db_path, upload_dir=tmp_path / "uploads",
                     seed_demo=False)
    app.config["TESTING"] = True
    dbmod.create_user(db_path, "Admin", "admin@t.mw", "Admin123!", "admin")
    dbmod.create_user(db_path, "Analyst", "analyst@t.mw", "Analyst123!", "analyst")
    dbmod.create_user(db_path, "Viewer", "viewer@t.mw", "Viewer123!", "viewer")
    return app.test_client()


def login(client, email="analyst@t.mw", password="Analyst123!"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def upload(client, content=CSV, name="test.csv"):
    return client.post("/api/datasets/upload",
                       data={"file": (io.BytesIO(content), name)},
                       content_type="multipart/form-data")


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.get_json()["status"] == "ok"


def test_bearer_token_works_without_any_cookie(client):
    """Regression test for the 'dashboard bounces back to login' bug.

    In a cross-site embedded preview the browser blocks the session
    cookie, so after a 'successful' login every API call arrived
    unauthenticated (401). Login must therefore also return a Bearer
    token that authenticates requests with NO cookie at all.
    """
    r = login(client)
    assert r.status_code == 200
    token = r.get_json()["token"]
    assert token

    # Drop every cookie - this is what a third-party-cookie-blocking
    # browser effectively does inside an embedded preview iframe.
    client.delete_cookie("session")
    assert client.get("/api/me").status_code == 401          # cookie path gone
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/me", headers=h).status_code == 200
    assert client.get("/api/datasets", headers=h).status_code == 200

    # A protected write + download must also work token-only
    # (these handlers previously read session["user_id"] directly).
    up = client.post("/api/datasets/upload",
                     data={"file": (io.BytesIO(CSV), "t.csv")},
                     content_type="multipart/form-data", headers=h)
    assert up.status_code == 201, up.get_json()
    did = up.get_json()["dataset_id"]
    assert client.get(f"/api/datasets/{did}/cleaned.csv", headers=h).status_code == 200

    # Tampered token rejected; valid token revoked by logout.
    bad = {"Authorization": "Bearer " + token[:-3] + "xxx"}
    assert client.get("/api/me", headers=bad).status_code == 401
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/me", headers=h).status_code == 401


def test_session_cookie_is_cross_site_safe_behind_https_proxy(client):
    """Behind an HTTPS (preview) proxy the session cookie must carry
    SameSite=None; Secure or browsers drop it in iframes."""
    r = client.post("/api/auth/login",
                    json={"email": "analyst@t.mw", "password": "Analyst123!"},
                    headers={"X-Forwarded-Proto": "https"})
    cookie = r.headers.get("Set-Cookie", "")
    assert "SameSite=None" in cookie and "Secure" in cookie


def test_login_required_and_bad_password(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/datasets").status_code == 401
    assert login(client, password="wrong").status_code == 401
    assert login(client).status_code == 200
    assert client.get("/api/me").get_json()["user"]["role"] == "analyst"


def test_viewer_cannot_upload(client):
    login(client, "viewer@t.mw", "Viewer123!")
    assert upload(client).status_code == 403


def test_upload_quality_patterns_preview_flow(client):
    login(client)
    r = upload(client)
    assert r.status_code == 201, r.get_json()
    did = r.get_json()["dataset_id"]

    datasets = client.get("/api/datasets").get_json()["datasets"]
    assert datasets[0]["row_count"] == 3

    q = client.get(f"/api/datasets/{did}/quality").get_json()["quality"]
    assert q["overall_score"] == 100.0  # this small file is clean

    p = client.get(f"/api/datasets/{did}/patterns?disease=Malaria").get_json()["patterns"]
    assert p["kpis"]["total_cases"] == 150
    assert p["filters_applied"] == {"disease": "Malaria"}

    preview = client.get(f"/api/datasets/{did}/preview").get_json()
    assert preview["total_rows"] == 3 and preview["profile"]["rows"] == 3


def test_personal_identifiers_and_wrong_type_refused(client):
    login(client)
    bad = b"patient_name,district,cases\nJane,Lilongwe,3\n"
    r = upload(client, bad, "bad.csv")
    assert r.status_code == 422
    assert "de-identified" in r.get_json()["error"]
    assert upload(client, b"hello", "notes.txt").status_code == 400
    assert upload(client, b"onlyonecol\n1\n2\n", "thin.csv").status_code == 422


def test_exports_and_delete(client):
    login(client)
    did = upload(client).get_json()["dataset_id"]
    assert client.get(f"/api/datasets/{did}/cleaned.csv").status_code == 200
    assert b"Lilongwe" in client.get(f"/api/datasets/{did}/cleaned.csv").data
    assert client.get(f"/api/datasets/{did}/quality-summary.csv").status_code == 200
    assert client.get(f"/api/datasets/{did}/pattern-summary.csv").status_code == 200
    assert client.delete(f"/api/datasets/{did}").status_code == 200
    assert client.get(f"/api/datasets/{did}/quality").status_code == 404


def test_admin_only_endpoints_and_backup(client):
    login(client)  # analyst
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/backup.sqlite3").status_code == 403
    client.post("/api/auth/logout")
    login(client, "admin@t.mw", "Admin123!")
    users = client.get("/api/admin/users").get_json()["users"]
    assert len(users) == 3
    r = client.post("/api/admin/users", json={
        "name": "New Officer", "email": "officer@t.mw",
        "password": "Officer123!", "role": "viewer"})
    assert r.status_code == 201
    assert client.post("/api/admin/users", json={
        "name": "Dupe", "email": "officer@t.mw",
        "password": "Officer123!", "role": "viewer"}).status_code == 409
    backup = client.get("/api/admin/backup.sqlite3")
    assert backup.status_code == 200 and backup.data[:6] == b"SQLite"
