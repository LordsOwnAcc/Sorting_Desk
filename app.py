import os
import sqlite3
import uuid
from flask import Flask, request, jsonify, render_template, send_from_directory, g

from parser import extract_text, extract_contact, extract_skills
from ranker import compute_scores

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "instance", "screener.db")
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB total per request


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            required_skills TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
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
            FOREIGN KEY (job_id) REFERENCES jobs (id)
        );
        """
    )
    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    db = get_db()
    rows = db.execute(
        "SELECT id, title, created_at, "
        "(SELECT COUNT(*) FROM candidates WHERE candidates.job_id = jobs.id) AS candidate_count "
        "FROM jobs ORDER BY created_at DESC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    required_skills = [s.strip() for s in (data.get("required_skills") or []) if s.strip()]

    if not title or not description:
        return jsonify({"error": "Job title and description are required."}), 400

    job_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        "INSERT INTO jobs (id, title, description, required_skills) VALUES (?, ?, ?, ?)",
        (job_id, title, description, ",".join(required_skills)),
    )
    db.commit()
    return jsonify({"id": job_id, "title": title})


@app.route("/api/jobs/<job_id>/screen", methods=["POST"])
def screen_resumes(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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
               (id, job_id, filename, stored_name, name, email, phone, skills,
                matched_skills, missing_skills, similarity, skill_match_pct, score, rank)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                c["id"], job_id, c["filename"], c["stored_name"], c["name"], c["email"], c["phone"],
                ",".join(c["skills"]), ",".join(c["matched_skills"]), ",".join(c["missing_skills"]),
                c["similarity"], c["skill_match_pct"], c["score"], c["rank"],
            ),
        )
    db.commit()

    for c in candidates:
        c.pop("resume_text", None)

    return jsonify({"candidates": candidates, "skipped": skipped, "required_skills": required_skills})


@app.route("/api/jobs/<job_id>/candidates", methods=["GET"])
def get_candidates(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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
    job_dict = dict(job)
    job_dict["required_skills"] = [s for s in (job_dict["required_skills"] or "").split(",") if s]
    return jsonify({"job": job_dict, "candidates": candidates})


@app.route("/api/resume/<job_id>/<stored_name>")
def download_resume(job_id, stored_name):
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    return send_from_directory(job_dir, stored_name)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    print("\n  Resume Screener running -> http://127.0.0.1:5000\n")
    if not debug_mode:
        print("  (debug mode off — set FLASK_DEBUG=1 for local dev auto-reload)\n")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)