import re
import sqlite3
import time
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

import os
DATABASE = os.environ.get("DATABASE_PATH", "/data/uptimer.db")
PORT = int(os.environ.get("PORT", 5000))

CHECK_INTERVAL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monitored_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_checked_at TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_id INTEGER NOT NULL,
            status_code INTEGER,
            response_time_ms REAL,
            is_up INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            checked_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (url_id) REFERENCES monitored_urls(id) ON DELETE CASCADE
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_checks_url_id ON health_checks(url_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_checks_checked_at ON health_checks(checked_at)"
    )
    conn.commit()
    conn.close()


def ping_url(url_id, url):
    start = time.monotonic()
    is_up = False
    status_code = None
    response_time_ms = None
    error_message = None

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        elapsed = time.monotonic() - start
        status_code = resp.status_code
        response_time_ms = round(elapsed * 1000, 2)
        is_up = 200 <= status_code < 400
    except requests.exceptions.Timeout:
        elapsed = time.monotonic() - start
        response_time_ms = round(elapsed * 1000, 2)
        error_message = "Timeout"
    except requests.exceptions.ConnectionError:
        response_time_ms = round((time.monotonic() - start) * 1000, 2)
        error_message = "Connection refused"
    except requests.exceptions.RequestException as e:
        response_time_ms = round((time.monotonic() - start) * 1000, 2)
        error_message = str(e)[:200]

    conn = get_db()
    conn.execute(
        """
        INSERT INTO health_checks (url_id, status_code, response_time_ms, is_up, error_message)
        VALUES (?, ?, ?, ?, ?)
    """,
        (url_id, status_code, response_time_ms, 1 if is_up else 0, error_message),
    )
    conn.execute(
        "UPDATE monitored_urls SET last_checked_at = datetime('now') WHERE id = ?",
        (url_id,),
    )
    conn.commit()
    conn.close()


def ping_all_urls():
    conn = get_db()
    urls = conn.execute("SELECT id, url FROM monitored_urls").fetchall()
    conn.close()
    for row in urls:
        try:
            ping_url(row["id"], row["url"])
        except Exception:
            pass


# --- API Routes ---


@app.route("/api/urls", methods=["GET"])
def list_urls():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT u.id, u.url, u.name, u.created_at,
               h.status_code, h.response_time_ms, h.is_up, h.error_message, h.checked_at
        FROM monitored_urls u
        LEFT JOIN health_checks h ON h.id = (
            SELECT id FROM health_checks WHERE url_id = u.id ORDER BY checked_at DESC LIMIT 1
        )
        ORDER BY u.created_at DESC
    """
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append(
            {
                "id": r["id"],
                "url": r["url"],
                "name": r["name"],
                "created_at": r["created_at"],
                "latest_check": {
                    "status_code": r["status_code"],
                    "response_time_ms": r["response_time_ms"],
                    "is_up": bool(r["is_up"]),
                    "error_message": r["error_message"],
                    "checked_at": r["checked_at"],
                }
                if r["checked_at"]
                else None,
            }
        )
    return jsonify(result)


URL_REGEX = re.compile(
    r"^https?://"  # http:// or https://
    r"([a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,}"  # domain
    r"(:\d+)?"  # optional port
    r"(/.*)?$"  # optional path
)


def validate_url(url):
    if not url:
        return "URL is required"
    if not URL_REGEX.match(url):
        return "Invalid URL format — must start with http:// or https://"
    return None


@app.route("/api/urls", methods=["POST"])
def add_url():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    err = validate_url(url)
    if err:
        return jsonify({"error": err}), 400
    name = data.get("name", url)
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO monitored_urls (url, name) VALUES (?, ?)", (url, name)
        )
        url_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "URL already monitored"}), 409
    conn.close()
    threading.Thread(target=ping_url, args=(url_id, url), daemon=True).start()
    return jsonify({"id": url_id, "url": url, "name": name}), 201


@app.route("/api/urls/<int:url_id>", methods=["PATCH"])
def update_url(url_id):
    data = request.get_json(silent=True) or {}
    fields = []
    values = []

    if "url" in data:
        url = data["url"].strip()
        err = validate_url(url)
        if err:
            return jsonify({"error": err}), 400
        fields.append("url = ?")
        values.append(url)

    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        fields.append("name = ?")
        values.append(name)

    if not fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(url_id)
    conn = get_db()
    try:
        conn.execute(
            f"UPDATE monitored_urls SET {', '.join(fields)} WHERE id = ?", values
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "URL already monitored"}), 409
    row = conn.execute(
        "SELECT id, url, name, created_at FROM monitored_urls WHERE id = ?",
        (url_id,),
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "URL not found"}), 404

    return jsonify(
        {
            "id": row["id"],
            "url": row["url"],
            "name": row["name"],
            "created_at": row["created_at"],
        }
    )


@app.route("/api/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    conn = get_db()
    conn.execute("DELETE FROM monitored_urls WHERE id = ?", (url_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"}), 200


@app.route("/api/urls/<int:url_id>/checks", methods=["GET"])
def check_history(url_id):
    limit = request.args.get("limit", 50, type=int)
    conn = get_db()
    rows = conn.execute(
        """
        SELECT status_code, response_time_ms, is_up, error_message, checked_at
        FROM health_checks
        WHERE url_id = ?
        ORDER BY checked_at DESC
        LIMIT ?
    """,
        (url_id, limit),
    ).fetchall()
    conn.close()
    return jsonify(
        [
            {
                "status_code": r["status_code"],
                "response_time_ms": r["response_time_ms"],
                "is_up": bool(r["is_up"]),
                "error_message": r["error_message"],
                "checked_at": r["checked_at"],
            }
            for r in rows
        ]
    )


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(ping_all_urls, "interval", seconds=CHECK_INTERVAL_SECONDS)
    scheduler.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
