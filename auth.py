"""
Minimal session-based auth. Two roles: 'recruiter' and 'candidate'.
Passwords hashed with werkzeug's generate_password_hash (pbkdf2).
"""
import uuid
from functools import wraps
from flask import session, redirect, url_for, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash


def create_user(db, email, password, name, role):
    email = email.strip().lower()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return None, "An account with that email already exists."
    if role not in ("recruiter", "candidate"):
        return None, "Invalid role."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    user_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO users (id, email, password_hash, name, role) VALUES (?, ?, ?, ?, ?)",
        (user_id, email, generate_password_hash(password), name.strip(), role),
    )
    db.commit()
    return {"id": user_id, "email": email, "name": name.strip(), "role": role}, None


def verify_login(db, email, password):
    email = email.strip().lower()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return None, "Incorrect email or password."
    return dict(row), None


def current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "email": session.get("email"),
        "name": session.get("name"),
        "role": session.get("role"),
    }


def log_in_session(user):
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["name"] = user["name"]
    session["role"] = user["role"]


def log_out_session():
    session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in."}), 401
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Please log in."}), 401
                return redirect(url_for("login_page"))
            if session.get("role") != role:
                return jsonify({"error": f"This action is for {role} accounts."}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator
