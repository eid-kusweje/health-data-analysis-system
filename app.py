"""
app.py - Flask web application & REST API.

Health and Disease Analytics: a web-based exploratory data analysis
dashboard for public health data quality and disease pattern analysis
in Malawi (Malawi 2063 aligned).

Run:
    pip install -r requirements.txt
    python app.py            # http://127.0.0.1:5000

Demo accounts (created automatically on first run):
    admin@demo.mw / Admin123!      (administrator)
    analyst@demo.mw / Analyst123!  (upload, analyse, export)
    viewer@demo.mw / Viewer123!    (view only)

Python integration: every analysis is available as JSON under /api/...,
and the pure functions in analysis.py can be imported directly.
"""
from __future__ import annotations

import io
import os
import re
import shutil
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import (Flask, jsonify, request, send_file, send_from_directory,
                   session)
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import db as dbmod
import seed as seedmod
from analysis import (MALAWI_DISTRICTS, clean_dataframe, data_quality,
                      detect_mapping, disease_patterns, profile_dataframe)

BASE_DIR = Path(__file__).resolve().parent
ALLOWED_EXT = {"csv", "xlsx", "xls"}


def read_file(path: str | Path) -> pd.DataFrame:
    """Read CSV/Excel keeping pandas default missing-value handling."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and (obj != obj):  # NaN
        return None
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:
            return str(obj)
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


class CrossSiteSessionInterface(SecureCookieSessionInterface):
    """Session cookie that survives cross-site embedding (live previews).

    When a request arrives over HTTPS (directly or via a preview/reverse
    proxy) the cookie is issued as SameSite=None + Secure, which browsers
    accept in a cross-site iframe. On plain-HTTP local use it stays
    SameSite=Lax without Secure, so http://127.0.0.1 testing still works.
    (Flask writes this cookie AFTER after_request handlers run, so this
    per-request interface override is the reliable hook.)"""

    @staticmethod
    def _is_https() -> bool:
        try:
            proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
            return request.is_secure or proto == "https"
        except RuntimeError:  # no active request context
            return False

    def get_cookie_samesite(self, app):
        return "None" if self._is_https() else "Lax"

    def get_cookie_secure(self, app):
        return self._is_https()


def create_app(db_path=None, upload_dir=None, seed_demo=True) -> Flask:
    app = Flask(__name__, static_folder=str(BASE_DIR / "static"))
    # Trust X-Forwarded-Proto/Host from the (HTTPS) preview/reverse proxy so
    # request.scheme is correct when the app is embedded or proxied.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # plain-HTTP/local default
    app.session_interface = CrossSiteSessionInterface()

    DB = Path(db_path) if db_path else BASE_DIR / "instance" / "app.sqlite3"
    UPLOADS = Path(upload_dir) if upload_dir else BASE_DIR / "instance" / "uploads"
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dbmod.init_db(DB)
    if seed_demo:
        seedmod.seed_database(DB, BASE_DIR, UPLOADS)
    app.config["DB_PATH"] = str(DB)

    # -- auth helpers ------------------------------------------------------
    def _bearer_token():
        auth = request.headers.get("Authorization", "")
        return auth[7:].strip() if auth.lower().startswith("bearer ") else None

    def current_user():
        # Primary: Bearer token (works even where cookies are blocked, e.g.
        # embedded previews). Fallback: the classic session cookie.
        raw = _bearer_token()
        if raw:
            user = dbmod.get_user_by_token(DB, raw)
            if user and user["is_active"]:
                return user
        uid = session.get("user_id")
        user = dbmod.get_user(DB, uid) if uid else None
        return user if user and user["is_active"] else None

    def login_required(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not current_user():
                return jsonify({"error": "Login required"}), 401
            return view(*a, **kw)
        return wrapped

    def role_required(*roles):
        def deco(view):
            @wraps(view)
            def wrapped(*a, **kw):
                user = current_user()
                if not user:
                    return jsonify({"error": "Login required"}), 401
                if user["role"] not in roles:
                    return jsonify({"error": "You do not have permission for this action"}), 403
                return view(*a, **kw)
            return wrapped
        return deco

    def load_dataset(dataset_id):
        meta = dbmod.get_dataset(DB, dataset_id)
        if not meta:
            return None, None, (jsonify({"error": "Dataset not found"}), 404)
        path = Path(meta["stored_path"])
        if not path.is_absolute():
            path = (BASE_DIR / path)
        if not path.exists():
            return meta, None, (jsonify({"error": "Dataset file is missing on the server"}), 410)
        try:
            return meta, read_file(path), None
        except Exception as exc:  # corrupt / unreadable file
            return meta, None, (jsonify({"error": f"Could not read dataset: {exc}"}), 422)

    # -- pages ---------------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # -- API: system ----------------------------------------------------------
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "system": "Malawi Health & Disease Analytics",
                        "database": "SQLite", "version": "1.0.1"})

    @app.get("/api/reference")
    def reference():
        return jsonify({"districts": MALAWI_DISTRICTS})

    # -- API: auth --------------------------------------------------------------
    @app.post("/api/auth/login")
    def login():
        data = request.get_json(silent=True) or {}
        user = dbmod.verify_user(DB, data.get("email", ""), data.get("password", ""))
        if not user:
            return jsonify({"error": "Invalid email or password, or account inactive"}), 401
        session["user_id"] = user["id"]
        dbmod.log_action(DB, user["id"], "login", user["email"])
        # The token is what the web page actually authenticates with (sent
        # as an Authorization header); the session cookie is a fallback.
        return jsonify({"user": dbmod.public_user(user),
                        "token": dbmod.create_auth_token(DB, user["id"]),
                        "token_type": "Bearer", "expires_in_days": 7})

    @app.post("/api/auth/logout")
    def logout():
        dbmod.revoke_token(DB, _bearer_token())
        session.clear()
        return jsonify({"message": "Logged out"})

    @app.get("/api/me")
    def me():
        user = current_user()
        if not user:
            return jsonify({"error": "Login required"}), 401
        return jsonify({"user": dbmod.public_user(user)})

    # -- API: datasets --------------------------------------------------------------
    @app.get("/api/datasets")
    @login_required
    def datasets():
        return jsonify({"datasets": _json_safe(dbmod.list_datasets(DB))})

    @app.post("/api/datasets/upload")
    @role_required("admin", "analyst")
    def upload():
        if "file" not in request.files or not request.files["file"].filename:
            return jsonify({"error": "Choose a CSV or Excel file to upload"}), 400
        f = request.files["file"]
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXT:
            return jsonify({"error": "Only .csv, .xlsx or .xls files are accepted"}), 400
        safe = secure_filename(f.filename) or f"dataset.{ext}"
        stored = UPLOADS / f"u{current_user()['id']}_{os.urandom(4).hex()}_{safe}"
        f.save(stored)
        try:
            df = read_file(stored)
        except Exception as exc:
            stored.unlink(missing_ok=True)
            return jsonify({"error": f"Could not read that file: {exc}"}), 422
        if df.empty or len(df.columns) < 2:
            stored.unlink(missing_ok=True)
            return jsonify({"error": "The file needs at least 2 columns and 1 row of data"}), 422
        # Privacy guard: refuse obvious personal identifiers
        forbidden = {"patient_name", "name", "phone", "phone_number", "national_id",
                     "id_number", "address", "home_address"}
        cols = {re.sub(r"[^a-z0-9_]", "_", str(c).strip().lower()) for c in df.columns}
        found = sorted(cols & forbidden)
        if found:
            stored.unlink(missing_ok=True)
            return jsonify({"error": "This system only accepts de-identified data. "
                            f"Remove personal identifier column(s): {', '.join(found)}"}), 422
        name = (request.form.get("name") or Path(safe).stem).strip()
        mapping = detect_mapping(df)
        did = dbmod.add_dataset(
            DB, name=name, original_filename=f.filename, stored_path=str(stored),
            file_type=ext, row_count=len(df), col_count=len(df.columns),
            mapping=mapping, owner_id=current_user()["id"],
            description=request.form.get("description", ""))
        dbmod.log_action(DB, current_user()["id"], "upload", f"Dataset {did}: {name}")
        return jsonify({"dataset_id": did, "mapping": mapping,
                        "message": "Dataset uploaded"}), 201

    @app.get("/api/datasets/<int:dataset_id>/preview")
    @login_required
    def preview(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        page = max(int(request.args.get("page", 1)), 1)
        per_page = 25
        start, end = (page - 1) * per_page, page * per_page
        rows = df.iloc[start:end].astype(object).where(pd.notna(df.iloc[start:end]), None)
        return jsonify(_json_safe({
            "dataset": {k: meta[k] for k in ("id", "name", "row_count", "col_count",
                                             "mapping", "is_demo", "description")},
            "columns": [str(c) for c in df.columns],
            "rows": rows.values.tolist(),
            "page": page, "per_page": per_page,
            "total_rows": len(df),
            "profile": profile_dataframe(df),
        }))

    @app.get("/api/datasets/<int:dataset_id>/quality")
    @login_required
    def quality(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        return jsonify(_json_safe({"dataset_id": dataset_id,
                                   "quality": data_quality(df, meta["mapping"])}))

    @app.get("/api/datasets/<int:dataset_id>/patterns")
    @login_required
    def patterns(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        filters = {k: request.args.get(k) for k in
                   ("disease", "district", "region", "sex", "age_group",
                    "date_from", "date_to")}
        return jsonify(_json_safe({
            "dataset_id": dataset_id,
            "patterns": disease_patterns(df, filters, meta["mapping"])}))

    @app.get("/api/datasets/<int:dataset_id>/overview")
    @login_required
    def overview(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        return jsonify(_json_safe({
            "dataset_id": dataset_id,
            "quality": data_quality(df, meta["mapping"]),
            "patterns": disease_patterns(df, {}, meta["mapping"])}))

    @app.get("/api/datasets/<int:dataset_id>/cleaned.csv")
    @role_required("admin", "analyst")
    def cleaned_csv(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        cleaned, log = clean_dataframe(
            df, drop_duplicates=request.args.get("drop_duplicates") == "1",
            mapping=meta["mapping"])
        dbmod.log_action(DB, current_user()["id"], "export_cleaned", f"Dataset {dataset_id}")
        if request.args.get("log") == "1":
            return jsonify(_json_safe({"cleaning_log": log, "rows": len(cleaned)}))
        buf = io.StringIO()
        cleaned.to_csv(buf, index=False)
        return send_file(io.BytesIO(buf.getvalue().encode()), mimetype="text/csv",
                         as_attachment=True,
                         download_name=f"cleaned_dataset_{dataset_id}.csv")

    @app.get("/api/datasets/<int:dataset_id>/quality-summary.csv")
    @login_required
    def quality_summary_csv(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        q = data_quality(df, meta["mapping"])
        rows = [{"item": "Overall data-quality score", "value": q["overall_score"],
                 "detail": q["rating"]}]
        rows += [{"item": f"Dimension: {k}", "value": v, "detail": ""}
                 for k, v in q["dimensions"].items()]
        rows += [{"item": f"Check: {c['check']}", "value": c["affected"],
                  "detail": f"{c['pct']}%"} for c in q["checks"]]
        buf = io.StringIO()
        pd.DataFrame(rows).to_csv(buf, index=False)
        return send_file(io.BytesIO(buf.getvalue().encode()), mimetype="text/csv",
                         as_attachment=True,
                         download_name=f"data_quality_summary_{dataset_id}.csv")

    @app.get("/api/datasets/<int:dataset_id>/pattern-summary.csv")
    @login_required
    def pattern_summary_csv(dataset_id):
        meta, df, err = load_dataset(dataset_id)
        if err:
            return err
        filters = {k: request.args.get(k) for k in
                   ("disease", "district", "region", "sex", "age_group",
                    "date_from", "date_to")}
        p = disease_patterns(df, filters, meta["mapping"])
        rows = []
        for section in ("by_disease", "by_district", "trend_monthly"):
            rows += [{"section": section, "label": r["label"], "cases": r["value"]}
                     for r in p[section]]
        buf = io.StringIO()
        pd.DataFrame(rows, columns=["section", "label", "cases"]).to_csv(buf, index=False)
        return send_file(io.BytesIO(buf.getvalue().encode()), mimetype="text/csv",
                         as_attachment=True,
                         download_name=f"disease_pattern_summary_{dataset_id}.csv")

    @app.delete("/api/datasets/<int:dataset_id>")
    @role_required("admin", "analyst")
    def delete_ds(dataset_id):
        meta = dbmod.get_dataset(DB, dataset_id)
        if not meta:
            return jsonify({"error": "Dataset not found"}), 404
        user = current_user()
        if meta["is_demo"] and user["role"] != "admin":
            return jsonify({"error": "Only an administrator can delete the demo dataset"}), 403
        if user["role"] == "analyst" and meta["owner_id"] not in (None, user["id"]):
            return jsonify({"error": "Analysts can only delete their own datasets"}), 403
        Path(meta["stored_path"]).unlink(missing_ok=True)
        dbmod.delete_dataset(DB, dataset_id)
        dbmod.log_action(DB, user["id"], "delete_dataset", f"Dataset {dataset_id}")
        return jsonify({"message": "Dataset deleted"})

    @app.get("/api/template.csv")
    @login_required
    def template_csv():
        path = BASE_DIR / "sample_data" / "data_template.csv"
        if not path.exists():
            seedmod.write_sample_files(BASE_DIR)
        return send_file(path, as_attachment=True, download_name="data_template.csv")

    # -- API: admin ---------------------------------------------------------------
    @app.get("/api/admin/users")
    @role_required("admin")
    def admin_users():
        return jsonify({"users": dbmod.list_users(DB)})

    @app.post("/api/admin/users")
    @role_required("admin")
    def admin_create_user():
        data = request.get_json(silent=True) or {}
        name, email = (data.get("name") or "").strip(), (data.get("email") or "").strip()
        password, role = data.get("password") or "", data.get("role") or "analyst"
        if not name or "@" not in email or len(password) < 8:
            return jsonify({"error": "Provide a name, a valid email and a password "
                            "of at least 8 characters"}), 400
        if role not in ("admin", "analyst", "viewer"):
            return jsonify({"error": "Role must be admin, analyst or viewer"}), 400
        try:
            uid = dbmod.create_user(DB, name, email, password, role)
        except Exception:
            return jsonify({"error": "A user with that email already exists"}), 409
        dbmod.log_action(DB, current_user()["id"], "create_user", email)
        return jsonify({"user_id": uid}), 201

    @app.post("/api/admin/users/<int:user_id>/toggle-active")
    @role_required("admin")
    def admin_toggle_user(user_id):
        if user_id == current_user()["id"]:
            return jsonify({"error": "You cannot deactivate your own account"}), 400
        target = dbmod.get_user(DB, user_id)
        if not target:
            return jsonify({"error": "User not found"}), 404
        dbmod.set_user_active(DB, user_id, not target["is_active"])
        dbmod.log_action(DB, current_user()["id"], "toggle_user", target["email"])
        return jsonify({"is_active": not target["is_active"]})

    @app.get("/api/admin/audit")
    @role_required("admin")
    def admin_audit():
        return jsonify({"audit": dbmod.list_audit(DB)})

    @app.get("/api/admin/system")
    @role_required("admin")
    def admin_system():
        return jsonify({
            "database_file": Path(DB).name,
            "database_size_kb": round(Path(DB).stat().st_size / 1024, 1) if Path(DB).exists() else 0,
            "users": len(dbmod.list_users(DB)),
            "datasets": len(dbmod.list_datasets(DB)),
            "uploads_folder": str(UPLOADS.name),
        })

    @app.get("/api/admin/backup.sqlite3")
    @role_required("admin")
    def admin_backup():
        """Download a copy of the SQLite database (system backup)."""
        backup = UPLOADS / "backup_app.sqlite3"
        shutil.copyfile(DB, backup)
        dbmod.log_action(DB, current_user()["id"], "backup_download", "")
        return send_file(backup, as_attachment=True, download_name="backup_app.sqlite3")

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify({"error": "File is larger than the 20 MB limit"}), 413

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
