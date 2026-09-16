import os
import sqlite3
import uuid
from flask import (
    Flask, request, jsonify, render_template, send_from_directory, g,
    session, redirect, url_for,
)

from parser import extract_text, extract_contact, extract_skills
from ranker import compute_scores, score_single
import auth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "instance", "screener.db")
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}
VALID_STATUSES = {"applied", "viewed", "shortlisted", "rejected"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB total per request
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-this-in-production")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _ensure_column(conn, table, column, coldef):
    """Idempotently add a column to an existing table (simple migration helper)."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('recruiter', 'candidate')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            recruiter_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            required_skills TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recruiter_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            user_id TEXT,
            filename TEXT,
            stored_name TEXT,
            name TEXT,
            email TEXT,
            phone TEXT,
            skills TEXT,
            matched_skills TEXT,
            missing_skills TEXT,
            similarity REAL,
            skill_match_pct REAL,
            score REAL,
            rank INTEGER,
            status TEXT NOT NULL DEFAULT 'applied',
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS application_events (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            event TEXT NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id) REFERENCES candidates (id)
        );
        """
    )
    # Migration safety net for DBs created before auth/applications existed.
    _ensure_column(conn, "jobs", "recruiter_id", "TEXT")
    _ensure_column(conn, "jobs", "status", "TEXT NOT NULL DEFAULT 'open'")
    _ensure_column(conn, "candidates", "user_id", "TEXT")
    _ensure_column(conn, "candidates", "status", "TEXT NOT NULL DEFAULT 'applied'")
    _ensure_column(conn, "candidates", "applied_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
    conn.commit()
    conn.close()


init_db()


def log_event(db, candidate_id, event, note=None):
    db.execute(
        "INSERT INTO application_events (id, candidate_id, event, note) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), candidate_id, event, note),
    )


def job_owned_by(db, job_id, recruiter_id):
    return db.execute(
        "SELECT * FROM jobs WHERE id = ? AND recruiter_id = ?", (job_id, recruiter_id)
    ).fetchone()


# ---------------------------------------------------------------- Pages ----

@app.route("/")
def home():
    user = auth.current_user()
    if not user:
        return redirect(url_for("login_page"))
    return redirect(url_for("recruiter_page") if user["role"] == "recruiter" else url_for("candidate_page"))


@app.route("/login")
def login_page():
    if auth.current_user():
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/recruiter")
@auth.role_required("recruiter")
def recruiter_page():
    return render_template("recruiter.html", user=auth.current_user())


@app.route("/candidate")
@auth.role_required("candidate")
def candidate_page():
    return render_template("candidate.html", user=auth.current_user())


# ------------------------------------------------------------- Auth API ----

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    role = data.get("role")

    if not email or not password or not name:
        return jsonify({"error": "Name, email, and password are required."}), 400

    db = get_db()
    user, error = auth.create_user(db, email, password, name, role)
    if error:
        return jsonify({"error": error}), 400
    auth.log_in_session(user)
    return jsonify({"user": user, "redirect": "/recruiter" if role == "recruiter" else "/candidate"})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    db = get_db()
    user, error = auth.verify_login(db, data.get("email") or "", data.get("password") or "")
    if error:
        return jsonify({"error": error}), 401
    auth.log_in_session(user)
    return jsonify({
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]},
        "redirect": "/recruiter" if user["role"] == "recruiter" else "/candidate",
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    auth.log_out_session()
    return jsonify({"ok": True})


# --------------------------------------------------------- Recruiter API ----

@app.route("/api/jobs", methods=["GET"])
@auth.role_required("recruiter")
def list_jobs():
    db = get_db()
    user = auth.current_user()
    rows = db.execute(
        "SELECT id, title, status, created_at, "
        "(SELECT COUNT(*) FROM candidates WHERE candidates.job_id = jobs.id) AS candidate_count, "
        "(SELECT COUNT(*) FROM candidates WHERE candidates.job_id = jobs.id AND status = 'shortlisted') AS shortlisted_count "
        "FROM jobs WHERE recruiter_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/jobs", methods=["POST"])
@auth.role_required("recruiter")
def create_job():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    required_skills = [s.strip() for s in (data.get("required_skills") or []) if s.strip()]

    if not title or not description:
        return jsonify({"error": "Job title and description are required."}), 400

    user = auth.current_user()
    job_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        "INSERT INTO jobs (id, recruiter_id, title, description, required_skills) VALUES (?, ?, ?, ?, ?)",
        (job_id, user["id"], title, description, ",".join(required_skills)),
    )
    db.commit()
    return jsonify({"id": job_id, "title": title})


@app.route("/api/jobs/<job_id>/screen", methods=["POST"])
@auth.role_required("recruiter")
def screen_resumes(job_id):
    db = get_db()
    user = auth.current_user()
    job = job_owned_by(db, job_id, user["id"])
    if not job:
        return jsonify({"error": "Job not found."}), 404

    files = request.files.getlist("resumes")
    if not files:
        return jsonify({"error": "No resumes were uploaded."}), 400

    required_skills = [s for s in (job["required_skills"] or "").split(",") if s]
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    candidates = []
    skipped = []
    for f in files:
        if not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            skipped.append(f.filename)
            continue
        stored_name = f"{uuid.uuid4().hex}{ext}"
        stored_path = os.path.join(job_dir, stored_name)
        f.save(stored_path)

        text = extract_text(stored_path)
        if not text:
            skipped.append(f.filename)
            continue
        contact = extract_contact(text, fallback_name=os.path.splitext(f.filename)[0])
        skills = extract_skills(text)

        candidates.append({
            "id": str(uuid.uuid4()),
            "filename": f.filename,
            "stored_name": stored_name,
            "resume_text": text,
            "name": contact["name"],
            "email": contact["email"],
            "phone": contact["phone"],
            "skills": skills,
        })

    if not candidates:
        return jsonify({"error": "None of the uploaded files could be read.", "skipped": skipped}), 400

    compute_scores(job["description"], required_skills, candidates)

    for c in candidates:
        db.execute(
            """INSERT INTO candidates
               (id, job_id, user_id, filename, stored_name, name, email, phone, skills,
                matched_skills, missing_skills, similarity, skill_match_pct, score, rank, status)
               VALUES (?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,'applied')""",
            (
                c["id"], job_id, c["filename"], c["stored_name"], c["name"], c["email"], c["phone"],
                ",".join(c["skills"]), ",".join(c["matched_skills"]), ",".join(c["missing_skills"]),
                c["similarity"], c["skill_match_pct"], c["score"], c["rank"],
            ),
        )
        log_event(db, c["id"], "applied", note="Uploaded directly by recruiter")
    db.commit()

    for c in candidates:
        c.pop("resume_text", None)

    return jsonify({"candidates": candidates, "skipped": skipped, "required_skills": required_skills})


@app.route("/api/jobs/<job_id>/candidates", methods=["GET"])
@auth.role_required("recruiter")
def get_candidates(job_id):
    db = get_db()
    user = auth.current_user()
    job = job_owned_by(db, job_id, user["id"])
    if not job:
        return jsonify({"error": "Job not found."}), 404

    rows = db.execute(
        "SELECT * FROM candidates WHERE job_id = ? ORDER BY rank ASC", (job_id,)
    ).fetchall()

    candidates = []
    for r in rows:
        d = dict(r)
        for key in ("skills", "matched_skills", "missing_skills"):
            d[key] = [s for s in (d[key] or "").split(",") if s]
        candidates.append(d)
        # Log a "viewed" event the first time a recruiter opens this candidate's results.
        already_viewed = db.execute(
            "SELECT 1 FROM application_events WHERE candidate_id = ? AND event = 'viewed'",
            (d["id"],),
        ).fetchone()
        if not already_viewed:
            log_event(db, d["id"], "viewed", note="Recruiter opened the ranked results")
    db.commit()

    job_dict = dict(job)
    job_dict["required_skills"] = [s for s in (job_dict["required_skills"] or "").split(",") if s]
    return jsonify({"job": job_dict, "candidates": candidates})


@app.route("/api/candidates/<candidate_id>/status", methods=["POST"])
@auth.role_required("recruiter")
def update_status(candidate_id):
    data = request.get_json(force=True)
    new_status = data.get("status")
    if new_status not in VALID_STATUSES:
        return jsonify({"error": "Invalid status."}), 400

    db = get_db()
    user = auth.current_user()
    row = db.execute(
        "SELECT candidates.*, jobs.recruiter_id AS owner_id FROM candidates "
        "JOIN jobs ON jobs.id = candidates.job_id WHERE candidates.id = ?",
        (candidate_id,),
    ).fetchone()
    if not row or row["owner_id"] != user["id"]:
        return jsonify({"error": "Applicant not found."}), 404

    db.execute("UPDATE candidates SET status = ? WHERE id = ?", (new_status, candidate_id))
    log_event(db, candidate_id, new_status)
    db.commit()
    return jsonify({"id": candidate_id, "status": new_status})


@app.route("/api/candidates/<candidate_id>/timeline", methods=["GET"])
@auth.login_required
def get_timeline(candidate_id):
    db = get_db()
    user = auth.current_user()
    row = db.execute(
        "SELECT candidates.*, jobs.recruiter_id AS owner_id, jobs.title AS job_title FROM candidates "
        "JOIN jobs ON jobs.id = candidates.job_id WHERE candidates.id = ?",
        (candidate_id,),
    ).fetchone()
    if not row:
        return jsonify({"error": "Applicant not found."}), 404
    is_owner_recruiter = user["role"] == "recruiter" and row["owner_id"] == user["id"]
    is_applicant = user["role"] == "candidate" and row["user_id"] == user["id"]
    if not (is_owner_recruiter or is_applicant):
        return jsonify({"error": "Not authorized to view this timeline."}), 403

    events = db.execute(
        "SELECT event, note, created_at FROM application_events "
        "WHERE candidate_id = ? ORDER BY created_at ASC",
        (candidate_id,),
    ).fetchall()
    return jsonify({
        "candidate_name": row["name"],
        "job_title": row["job_title"],
        "events": [dict(e) for e in events],
    })


# ---------------------------------------------------------- Candidate API ----

@app.route("/api/open-jobs", methods=["GET"])
@auth.role_required("candidate")
def open_jobs():
    db = get_db()
    user = auth.current_user()
    rows = db.execute(
        """SELECT jobs.id, jobs.title, jobs.description, jobs.required_skills, jobs.created_at,
                  users.name AS recruiter_name,
                  EXISTS(SELECT 1 FROM candidates WHERE candidates.job_id = jobs.id AND candidates.user_id = ?) AS already_applied
           FROM jobs JOIN users ON users.id = jobs.recruiter_id
           WHERE jobs.status = 'open' ORDER BY jobs.created_at DESC""",
        (user["id"],),
    ).fetchall()
    jobs = []
    for r in rows:
        d = dict(r)
        d["required_skills"] = [s for s in (d["required_skills"] or "").split(",") if s]
        d["already_applied"] = bool(d["already_applied"])
        jobs.append(d)
    return jsonify(jobs)


@app.route("/api/jobs/<job_id>/apply", methods=["POST"])
@auth.role_required("candidate")
def apply_to_job(job_id):
    db = get_db()
    user = auth.current_user()
    job = db.execute("SELECT * FROM jobs WHERE id = ? AND status = 'open'", (job_id,)).fetchone()
    if not job:
        return jsonify({"error": "This role isn't open for applications."}), 404

    existing = db.execute(
        "SELECT id FROM candidates WHERE job_id = ? AND user_id = ?", (job_id, user["id"])
    ).fetchone()
    if existing:
        return jsonify({"error": "You've already applied to this role."}), 400

    f = request.files.get("resume")
    if not f or not f.filename:
        return jsonify({"error": "Attach your resume to apply."}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "Resume must be a PDF, DOCX, or TXT file."}), 400

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(job_dir, stored_name)
    f.save(stored_path)

    text = extract_text(stored_path)
    if not text:
        return jsonify({"error": "Couldn't read that resume file — try a different format."}), 400

    contact = extract_contact(text, fallback_name=user["name"])
    skills = extract_skills(text)
    required_skills = [s for s in (job["required_skills"] or "").split(",") if s]
    result = score_single(job["description"], required_skills, text, skills)

    candidate_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO candidates
           (id, job_id, user_id, filename, stored_name, name, email, phone, skills,
            matched_skills, missing_skills, similarity, skill_match_pct, score, rank, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,'applied')""",
        (
            candidate_id, job_id, user["id"], f.filename, stored_name,
            contact["name"] or user["name"], contact["email"], contact["phone"],
            ",".join(skills), ",".join(result["matched_skills"]), ",".join(result["missing_skills"]),
            result["similarity"], result["skill_match_pct"], result["score"],
        ),
    )
    log_event(db, candidate_id, "applied", note="Applied via candidate portal")

    # Recompute rank for the whole job so recruiters see a consistent order.
    all_rows = db.execute(
        "SELECT id, score FROM candidates WHERE job_id = ? ORDER BY score DESC", (job_id,)
    ).fetchall()
    for i, r in enumerate(all_rows, start=1):
        db.execute("UPDATE candidates SET rank = ? WHERE id = ?", (i, r["id"]))
    db.commit()

    return jsonify({"id": candidate_id, "score": result["score"], "status": "applied"})


@app.route("/api/my-applications", methods=["GET"])
@auth.role_required("candidate")
def my_applications():
    db = get_db()
    user = auth.current_user()
    rows = db.execute(
        """SELECT candidates.id, candidates.score, candidates.status, candidates.applied_at,
                  candidates.matched_skills, candidates.missing_skills,
                  jobs.title AS job_title, jobs.id AS job_id
           FROM candidates JOIN jobs ON jobs.id = candidates.job_id
           WHERE candidates.user_id = ? ORDER BY candidates.applied_at DESC""",
        (user["id"],),
    ).fetchall()
    apps = []
    for r in rows:
        d = dict(r)
        for key in ("matched_skills", "missing_skills"):
            d[key] = [s for s in (d[key] or "").split(",") if s]
        apps.append(d)
    return jsonify(apps)


# -------------------------------------------------------------- Resumes ----

@app.route("/api/resume/<job_id>/<stored_name>")
@auth.login_required
def download_resume(job_id, stored_name):
    db = get_db()
    user = auth.current_user()
    row = db.execute(
        "SELECT candidates.*, jobs.recruiter_id AS owner_id FROM candidates "
        "JOIN jobs ON jobs.id = candidates.job_id "
        "WHERE candidates.job_id = ? AND candidates.stored_name = ?",
        (job_id, stored_name),
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    is_owner_recruiter = user["role"] == "recruiter" and row["owner_id"] == user["id"]
    is_applicant = user["role"] == "candidate" and row["user_id"] == user["id"]
    if not (is_owner_recruiter or is_applicant):
        return jsonify({"error": "Not authorized."}), 403

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    return send_from_directory(job_dir, stored_name)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    print("\n  Resume Screener running -> http://127.0.0.1:5000\n")
    if not debug_mode:
        print("  (debug mode off — set FLASK_DEBUG=1 for local dev auto-reload)\n")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
