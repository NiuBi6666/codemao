import json
import os
import sqlite3
from datetime import datetime, timezone

from flask import current_app, g
from werkzeug.security import generate_password_hash


PERMISSIONS = (
    ("query_students", "查询学生", "批量查询学生姓名和用户 ID"),
    ("manage_roster", "管理名单", "上传 Excel 并替换学生名单"),
    ("manage_users", "管理用户与权限", "创建用户、分配角色和配置角色权限"),
    ("view_audit", "查看审计日志", "查看登录、查询和管理操作记录"),
)

DEFAULT_ROLES = {
    "查询员": ("query_students",),
    "名单管理员": ("query_students", "manage_roster"),
    "系统管理员": ("query_students", "manage_roster", "manage_users", "view_audit"),
}


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db():
    if "db" not in g:
        path = current_app.config["DATABASE_PATH"]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        g.db = sqlite3.connect(path, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def audit(action, details=None, user_id=None, ip_address=""):
    connection = get_db()
    connection.execute(
        "INSERT INTO audit_logs (user_id, action, details, ip_address, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, action, json.dumps(details or {}, ensure_ascii=False), ip_address, utcnow()),
    )
    connection.commit()


def initialize():
    connection = get_db()
    with current_app.open_resource("schema.sql") as schema:
        connection.executescript(schema.read().decode("utf-8"))

    connection.executemany(
        "INSERT OR IGNORE INTO permissions (code, name, description) VALUES (?, ?, ?)",
        PERMISSIONS,
    )
    for role_name, permission_codes in DEFAULT_ROLES.items():
        connection.execute(
            "INSERT OR IGNORE INTO roles (name, description, is_system, created_at) VALUES (?, ?, 1, ?)",
            (role_name, "系统预置角色", utcnow()),
        )
        role_id = connection.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()["id"]
        for code in permission_codes:
            connection.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
                (role_id, code),
            )

    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        username = current_app.config["ADMIN_USERNAME"].strip()
        password = current_app.config["ADMIN_PASSWORD"]
        if not username or len(password) < 10:
            raise RuntimeError("ADMIN_USERNAME and an ADMIN_PASSWORD of at least 10 characters are required")
        now = utcnow()
        connection.execute(
            """
            INSERT INTO users
                (username, display_name, password_hash, is_active, is_superadmin, created_at, updated_at)
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (
                username,
                current_app.config["ADMIN_DISPLAY_NAME"].strip() or "系统管理员",
                generate_password_hash(password),
                now,
                now,
            ),
        )
    connection.commit()

    initial_file = current_app.config.get("INITIAL_ROSTER_FILE", "")
    student_count = connection.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    if initial_file and student_count == 0 and os.path.isfile(initial_file):
        from .roster import import_roster_path

        import_roster_path(initial_file, imported_by=None)


def init_app(app):
    app.teardown_appcontext(close_db)
