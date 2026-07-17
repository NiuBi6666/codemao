import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import audit, get_db, utcnow
from .roster import RosterValidationError, parse_roster, replace_roster


bp = Blueprint("web", __name__)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
NAME_SPLIT_RE = re.compile(r"[\n\r,，;；]+")
MAX_QUERY_NAMES = 500


def client_ip():
    return request.headers.get("X-Real-IP", request.remote_addr or "")[:80]


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@bp.app_context_processor
def template_helpers():
    return {
        "csrf_token": csrf_token,
        "has_permission": lambda code: bool(
            getattr(g, "user", None)
            and (g.user["is_superadmin"] or code in getattr(g, "permissions", set()))
        ),
    }


@bp.before_app_request
def load_user_and_check_csrf():
    user_id = session.get("user_id")
    g.user = None
    g.permissions = set()
    if user_id is not None:
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user and user["is_active"]:
            g.user = user
            permission_rows = get_db().execute(
                """
                SELECT DISTINCT rp.permission_code
                FROM user_roles ur
                JOIN role_permissions rp ON rp.role_id = ur.role_id
                WHERE ur.user_id = ?
                """,
                (user_id,),
            ).fetchall()
            g.permissions = {row["permission_code"] for row in permission_rows}
        else:
            session.clear()

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("_csrf_token", "")
        supplied = request.form.get("_csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(400, "表单已过期，请刷新页面后重试")


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("web.login"))
        return view(**kwargs)

    return wrapped


def permission_required(code):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(**kwargs):
            if not g.user["is_superadmin"] and code not in g.permissions:
                abort(403)
            return view(**kwargs)

        return wrapped

    return decorator


def parse_names(raw):
    names = []
    seen = set()
    for part in NAME_SPLIT_RE.split(raw or ""):
        name = "".join(part.strip().split())
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


@bp.route("/healthz")
def healthz():
    try:
        get_db().execute("SELECT 1").fetchone()
        return {"status": "ok"}, 200
    except sqlite3.Error:
        return {"status": "error"}, 503


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("web.query"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        connection = get_db()
        user = connection.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        now = datetime.now(timezone.utc)
        locked = False
        if user and user["locked_until"]:
            try:
                locked = datetime.fromisoformat(user["locked_until"]) > now
            except ValueError:
                locked = False

        if user and user["is_active"] and not locked and check_password_hash(user["password_hash"], password):
            connection.execute(
                "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?",
                (utcnow(), user["id"]),
            )
            connection.commit()
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            csrf_token()
            audit("login_success", user_id=user["id"], ip_address=client_ip())
            return redirect(url_for("web.query"))

        if user and user["is_active"] and not locked:
            attempts = user["failed_login_attempts"] + 1
            lock_until = None
            if attempts >= 5:
                lock_until = (now + timedelta(minutes=15)).replace(microsecond=0).isoformat()
                attempts = 0
            connection.execute(
                "UPDATE users SET failed_login_attempts = ?, locked_until = ?, updated_at = ? WHERE id = ?",
                (attempts, lock_until, utcnow(), user["id"]),
            )
            connection.commit()
        audit(
            "login_failed",
            {"username": username[:50], "locked": locked},
            user_id=user["id"] if user else None,
            ip_address=client_ip(),
        )
        flash("用户名或密码错误，连续失败 5 次将锁定 15 分钟", "error")

    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    user_id = g.user["id"]
    audit("logout", user_id=user_id, ip_address=client_ip())
    session.clear()
    return redirect(url_for("web.login"))


@bp.route("/", methods=("GET", "POST"))
@permission_required("query_students")
def query():
    mode = request.values.get("mode", "name")
    if mode not in {"name", "id"}:
        mode = "name"

    raw_values = ""
    results = None
    summary = None
    if request.method == "POST":
        field_name = "ids" if mode == "id" else "names"
        raw_values = request.form.get(field_name, "")
        values = parse_names(raw_values)
        value_label = "ID" if mode == "id" else "姓名"
        if not values:
            flash(f"请至少输入一个学生{value_label}", "error")
        elif len(values) > MAX_QUERY_NAMES:
            flash(f"单次最多查询 {MAX_QUERY_NAMES} 个{value_label}", "error")
        else:
            placeholders = ",".join("?" for _ in values)
            if mode == "id":
                rows = get_db().execute(
                    f"""
                    SELECT user_id, name, gender, age, grade, class_name
                    FROM students
                    WHERE user_id IN ({placeholders})
                    ORDER BY user_id
                    """,
                    values,
                ).fetchall()
                by_id = {row["user_id"]: row for row in rows}
                results = [
                    {"input_id": user_id, "student": by_id.get(user_id)}
                    for user_id in values
                ]
                found = sum(1 for item in results if item["student"])
                ambiguous = 0
            else:
                rows = get_db().execute(
                    f"""
                    SELECT user_id, name, gender, age, grade, class_name
                    FROM students
                    WHERE name IN ({placeholders})
                    ORDER BY name, grade, class_name, user_id
                    """,
                    values,
                ).fetchall()
                by_name = {}
                for row in rows:
                    by_name.setdefault(row["name"], []).append(row)
                results = [
                    {"input_name": name, "matches": by_name.get(name, [])}
                    for name in values
                ]
                found = sum(1 for item in results if item["matches"])
                ambiguous = sum(1 for item in results if len(item["matches"]) > 1)

            summary = {
                "total": len(results),
                "found": found,
                "missing": len(results) - found,
                "ambiguous": ambiguous,
            }
            audit(
                "student_query",
                {**summary, "mode": mode},
                user_id=g.user["id"],
                ip_address=client_ip(),
            )

    roster_count = get_db().execute("SELECT COUNT(*) FROM students").fetchone()[0]
    return render_template(
        "query.html",
        mode=mode,
        raw_values=raw_values,
        results=results,
        summary=summary,
        roster_count=roster_count,
    )


@bp.get("/roster")
@permission_required("manage_roster")
def roster():
    connection = get_db()
    stats = connection.execute(
        """
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT name) AS distinct_names,
               COUNT(DISTINCT class_name) AS classes
        FROM students
        """
    ).fetchone()
    imports = connection.execute(
        """
        SELECT b.*, u.display_name
        FROM import_batches b
        LEFT JOIN users u ON u.id = b.imported_by
        ORDER BY b.id DESC
        LIMIT 20
        """
    ).fetchall()
    return render_template("roster.html", stats=stats, imports=imports)


@bp.post("/roster/import")
@permission_required("manage_roster")
def roster_import():
    uploaded = request.files.get("roster")
    if not uploaded or not uploaded.filename:
        flash("请选择 Excel 文件", "error")
        return redirect(url_for("web.roster"))
    if not uploaded.filename.lower().endswith(".xlsx"):
        flash("只支持 .xlsx 文件", "error")
        return redirect(url_for("web.roster"))
    try:
        rows = parse_roster(uploaded.stream)
        count = replace_roster(rows, uploaded.filename[:200], g.user["id"])
    except RosterValidationError as exc:
        flash(str(exc), "error")
        audit(
            "roster_import_failed",
            {"filename": uploaded.filename[:200], "reason": str(exc)[:300]},
            user_id=g.user["id"],
            ip_address=client_ip(),
        )
    else:
        flash(f"名单导入成功，共 {count} 名学生", "success")
        audit(
            "roster_imported",
            {"filename": uploaded.filename[:200], "row_count": count},
            user_id=g.user["id"],
            ip_address=client_ip(),
        )
    return redirect(url_for("web.roster"))


def all_roles():
    return get_db().execute(
        """
        SELECT r.*, COUNT(DISTINCT ur.user_id) AS user_count,
               GROUP_CONCAT(DISTINCT p.name) AS permission_names
        FROM roles r
        LEFT JOIN user_roles ur ON ur.role_id = r.id
        LEFT JOIN role_permissions rp ON rp.role_id = r.id
        LEFT JOIN permissions p ON p.code = rp.permission_code
        GROUP BY r.id
        ORDER BY r.is_system DESC, r.name
        """
    ).fetchall()


@bp.get("/users")
@permission_required("manage_users")
def users():
    rows = get_db().execute(
        """
        SELECT u.*, GROUP_CONCAT(r.name, '、') AS role_names
        FROM users u
        LEFT JOIN user_roles ur ON ur.user_id = u.id
        LEFT JOIN roles r ON r.id = ur.role_id
        GROUP BY u.id
        ORDER BY u.is_superadmin DESC, u.username
        """
    ).fetchall()
    return render_template("users.html", users=rows)


def validate_user_form(is_new, target=None):
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    password = request.form.get("password", "")
    role_ids = {value for value in request.form.getlist("role_ids") if value.isdigit()}
    is_active = request.form.get("is_active") == "1"
    error = None
    if not USERNAME_RE.fullmatch(username):
        error = "用户名需为 3-50 位字母、数字、点、下划线或短横线"
    elif not display_name or len(display_name) > 50:
        error = "显示名称不能为空且不能超过 50 个字符"
    elif (is_new or password) and len(password) < 10:
        error = "密码至少需要 10 个字符"
    elif target and target["id"] == g.user["id"] and not is_active:
        error = "不能停用当前登录账号"
    return error, username, display_name, password, role_ids, is_active


@bp.route("/users/new", methods=("GET", "POST"))
@permission_required("manage_users")
def user_new():
    roles = all_roles()
    if request.method == "POST":
        error, username, display_name, password, role_ids, is_active = validate_user_form(True)
        if not error:
            connection = get_db()
            try:
                now = utcnow()
                cursor = connection.execute(
                    """
                    INSERT INTO users
                        (username, display_name, password_hash, is_active, is_superadmin, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (username, display_name, generate_password_hash(password), int(is_active), now, now),
                )
                valid_role_ids = {
                    str(row["id"]) for row in connection.execute("SELECT id FROM roles").fetchall()
                }
                connection.executemany(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                    ((cursor.lastrowid, int(role_id)) for role_id in role_ids & valid_role_ids),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                error = "用户名已存在"
            else:
                audit(
                    "user_created",
                    {"username": username},
                    user_id=g.user["id"],
                    ip_address=client_ip(),
                )
                flash("用户已创建", "success")
                return redirect(url_for("web.users"))
        flash(error, "error")
    return render_template("user_form.html", target=None, roles=roles)


@bp.route("/users/<int:user_id>/edit", methods=("GET", "POST"))
@permission_required("manage_users")
def user_edit(user_id):
    connection = get_db()
    target = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        abort(404)
    if target["is_superadmin"] and not g.user["is_superadmin"]:
        abort(403)
    roles = all_roles()
    selected_roles = {
        str(row["role_id"])
        for row in connection.execute("SELECT role_id FROM user_roles WHERE user_id = ?", (user_id,))
    }
    if request.method == "POST":
        error, username, display_name, password, role_ids, is_active = validate_user_form(False, target)
        if target["is_superadmin"]:
            is_active = True
        if not error:
            try:
                if password:
                    connection.execute(
                        """
                        UPDATE users
                        SET username = ?, display_name = ?, password_hash = ?, is_active = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            username,
                            display_name,
                            generate_password_hash(password),
                            int(is_active),
                            utcnow(),
                            user_id,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE users
                        SET username = ?, display_name = ?, is_active = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (username, display_name, int(is_active), utcnow(), user_id),
                    )
                connection.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
                valid_role_ids = {
                    str(row["id"]) for row in connection.execute("SELECT id FROM roles").fetchall()
                }
                connection.executemany(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                    ((user_id, int(role_id)) for role_id in role_ids & valid_role_ids),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                error = "用户名已存在"
            else:
                audit(
                    "user_updated",
                    {"username": username, "active": is_active, "password_reset": bool(password)},
                    user_id=g.user["id"],
                    ip_address=client_ip(),
                )
                flash("用户信息已更新", "success")
                return redirect(url_for("web.users"))
        flash(error, "error")
        selected_roles = role_ids
    return render_template(
        "user_form.html", target=target, roles=roles, selected_roles=selected_roles
    )


@bp.get("/roles")
@permission_required("manage_users")
def roles():
    return render_template("roles.html", roles=all_roles())


def role_form_data():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    selected = set(request.form.getlist("permissions"))
    valid = {row["code"] for row in get_db().execute("SELECT code FROM permissions")}
    error = None
    if not name or len(name) > 50:
        error = "角色名称不能为空且不能超过 50 个字符"
    elif len(description) > 200:
        error = "角色说明不能超过 200 个字符"
    return error, name, description, selected & valid


@bp.route("/roles/new", methods=("GET", "POST"))
@permission_required("manage_users")
def role_new():
    connection = get_db()
    permissions = connection.execute("SELECT * FROM permissions ORDER BY code").fetchall()
    selected = set()
    if request.method == "POST":
        error, name, description, selected = role_form_data()
        if not error:
            try:
                cursor = connection.execute(
                    "INSERT INTO roles (name, description, is_system, created_at) VALUES (?, ?, 0, ?)",
                    (name, description, utcnow()),
                )
                connection.executemany(
                    "INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
                    ((cursor.lastrowid, code) for code in selected),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                error = "角色名称已存在"
            else:
                audit("role_created", {"name": name}, g.user["id"], client_ip())
                flash("角色已创建", "success")
                return redirect(url_for("web.roles"))
        flash(error, "error")
    return render_template(
        "role_form.html", target=None, permissions=permissions, selected=selected
    )


@bp.route("/roles/<int:role_id>/edit", methods=("GET", "POST"))
@permission_required("manage_users")
def role_edit(role_id):
    connection = get_db()
    target = connection.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not target:
        abort(404)
    permissions = connection.execute("SELECT * FROM permissions ORDER BY code").fetchall()
    selected = {
        row["permission_code"]
        for row in connection.execute(
            "SELECT permission_code FROM role_permissions WHERE role_id = ?", (role_id,)
        )
    }
    if request.method == "POST":
        error, name, description, selected = role_form_data()
        if not error:
            try:
                connection.execute(
                    "UPDATE roles SET name = ?, description = ? WHERE id = ?",
                    (name, description, role_id),
                )
                connection.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
                connection.executemany(
                    "INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
                    ((role_id, code) for code in selected),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                error = "角色名称已存在"
            else:
                audit("role_updated", {"name": name}, g.user["id"], client_ip())
                flash("角色权限已更新", "success")
                return redirect(url_for("web.roles"))
        flash(error, "error")
    return render_template(
        "role_form.html", target=target, permissions=permissions, selected=selected
    )


@bp.post("/roles/<int:role_id>/delete")
@permission_required("manage_users")
def role_delete(role_id):
    connection = get_db()
    target = connection.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not target:
        abort(404)
    if target["is_system"]:
        flash("系统预置角色不能删除", "error")
    else:
        connection.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        connection.commit()
        audit("role_deleted", {"name": target["name"]}, g.user["id"], client_ip())
        flash("角色已删除，原有用户已自动解除该角色", "success")
    return redirect(url_for("web.roles"))


@bp.get("/audit")
@permission_required("view_audit")
def audit_logs():
    logs = get_db().execute(
        """
        SELECT a.*, u.username, u.display_name
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY a.id DESC
        LIMIT 500
        """
    ).fetchall()
    return render_template("audit.html", logs=logs)


@bp.app_errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=str(error.description)), 400


@bp.app_errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="你没有执行此操作的权限"), 403


@bp.app_errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="页面不存在"), 404


@bp.app_errorhandler(413)
def too_large(_error):
    return render_template("error.html", code=413, message="上传文件超过大小限制"), 413
