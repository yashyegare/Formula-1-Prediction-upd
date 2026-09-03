"""
Authentication module for F1 Race Predictor.

Uses Flask-Login for session management and werkzeug.security for password
hashing. No email verification — users sign up with username + email + password.

Usage in app.py:
    from auth import auth_bp, login_manager
    app.register_blueprint(auth_bp)
    login_manager.init_app(app)
"""

import re
from functools import wraps

from flask import Blueprint, jsonify, request, session
from flask_login import (
    LoginManager, UserMixin, current_user, login_user,
    logout_user, login_required,
)
from werkzeug.security import generate_password_hash, check_password_hash

from database import (
    create_user, get_user_by_id, get_user_by_username,
    get_user_by_email, update_last_login, delete_user_by_email,
)

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"


# ── User model ───────────────────────────────────────────────────────────

class User(UserMixin):
    """Flask-Login user model backed by SQLite."""

    def __init__(self, id, username, email, display_name=None, avatar_url=None):
        self.id = id
        self.username = username
        self.email = email
        self.display_name = display_name or username
        self.avatar_url = avatar_url

    @staticmethod
    def from_db_row(row):
        """Create a User instance from a database row (dict or sqlite3.Row)."""
        if row is None:
            return None
        d = dict(row) if not isinstance(row, dict) else row
        return User(
            id=d["id"], username=d["username"], email=d["email"],
            display_name=d.get("display_name") or d["username"],
            avatar_url=d.get("avatar_url"),
        )


@login_manager.user_loader
def load_user(user_id: str):
    """Flask-Login callback to load a user by ID."""
    row = get_user_by_id(int(user_id))
    return User.from_db_row(row)


# ── Validation helpers ───────────────────────────────────────────────────

def _validate_username(username: str) -> str | None:
    """Return error message or None if valid."""
    if not username or len(username) < 3:
        return "Username must be at least 3 characters"
    if len(username) > 30:
        return "Username must be at most 30 characters"
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        return "Username can only contain letters, numbers, underscores, and hyphens"
    return None


def _validate_email(email: str) -> str | None:
    if not email or "@" not in email:
        return "Invalid email address"
    if len(email) > 255:
        return "Email too long"
    return None


def _validate_password(password: str) -> str | None:
    if not password or len(password) < 8:
        return "Password must be at least 8 characters"
    if len(password) > 128:
        return "Password too long"
    return None


# ── Auth routes ──────────────────────────────────────────────────────────

@auth_bp.route("/api/auth/signup", methods=["POST"])
def signup():
    """Register a new user."""
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("displayName") or username).strip()

    # Validate
    err = _validate_username(username)
    if err:
        return jsonify({"error": err}), 400
    err = _validate_email(email)
    if err:
        return jsonify({"error": err}), 400
    err = _validate_password(password)
    if err:
        return jsonify({"error": err}), 400

    # Check uniqueness
    if get_user_by_username(username):
        return jsonify({"error": "Username already taken"}), 409
    if get_user_by_email(email):
        return jsonify({"error": "Email already registered"}), 409

    # Create
    password_hash = generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)
    user_id = create_user(username, email, password_hash, display_name)

    # Auto-login
    user = User(id=user_id, username=username, email=email, display_name=display_name)
    login_user(user, remember=True)

    return jsonify({
        "user": {
            "id": user_id, "username": username, "email": email,
            "displayName": display_name,
        }
    }), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    """Log in an existing user."""
    data = request.get_json(force=True, silent=True) or {}
    identifier = (data.get("username") or data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not identifier or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Try username first, then email — users may not remember their auto-generated username
    user_row = get_user_by_username(identifier)
    if not user_row and "@" in identifier:
        user_row = get_user_by_email(identifier)
    if not user_row or not check_password_hash(user_row["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    user = User.from_db_row(user_row)
    login_user(user, remember=True)
    update_last_login(user.id)

    return jsonify({
        "user": {
            "id": user.id, "username": user.username, "email": user.email,
            "displayName": user.display_name,
        }
    })


@auth_bp.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    return jsonify({"ok": True})


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    """Return the current user's profile (or 401 if not logged in)."""
    if current_user.is_authenticated:
        return jsonify({
            "user": {
                "id": current_user.id, "username": current_user.username,
                "email": current_user.email, "displayName": current_user.display_name,
                "avatarUrl": current_user.avatar_url,
            }
        })
    return jsonify({"user": None}), 401


# ── Decorator for optional auth ──────────────────────────────────────────

def optional_auth(f):
    """Decorator that makes @login_required optional — sets current_user
    if logged in, but doesn't block if not."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Flask-Login already handles this via session — if not logged in,
        # current_user.is_authenticated is False but the route still runs.
        return f(*args, **kwargs)
    return decorated


# ── TEMP: delete user by email (remove after use) ────────────────────────
@auth_bp.route("/api/admin/delete-user", methods=["POST"])
def delete_user_temp():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400
    deleted = delete_user_by_email(email)
    return jsonify({"deleted": deleted, "email": email})
