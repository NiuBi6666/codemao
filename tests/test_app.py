import io
import os
import re
import tempfile
import unittest

from openpyxl import Workbook

from codemao import create_app
from codemao.db import get_db, utcnow
from werkzeug.security import generate_password_hash


HEADERS = ["用户ID", "姓名", "性别", "年龄", "年级", "班级名称"]


def workbook_bytes(rows, headers=HEADERS):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE_PATH": os.path.join(self.tempdir.name, "test.sqlite3"),
                "ADMIN_USERNAME": "admin",
                "ADMIN_PASSWORD": "test-password-123",
                "ADMIN_DISPLAY_NAME": "Test Admin",
                "INITIAL_ROSTER_FILE": "",
                "COOKIE_SECURE": False,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def csrf(self, path="/login"):
        response = self.client.get(path)
        match = re.search(rb'name="_csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def login(self, username="admin", password="test-password-123"):
        token = self.csrf("/login")
        return self.client.post(
            "/login",
            data={"username": username, "password": password, "_csrf_token": token},
            follow_redirects=True,
        )

    def import_rows(self, rows, headers=HEADERS):
        token = self.csrf("/roster")
        return self.client.post(
            "/roster/import",
            data={
                "_csrf_token": token,
                "roster": (workbook_bytes(rows, headers), "students.xlsx"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    def test_login_requires_valid_credentials_and_csrf(self):
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "test-password-123"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.login(password="wrong-password")
        self.assertIn("用户名或密码错误".encode(), response.data)

        response = self.login()
        self.assertIn("批量查询".encode(), response.data)

    def test_name_and_id_queries_deduplicate_inputs(self):
        self.login()
        response = self.import_rows(
            [
                ["1001", "张三", "男", 13, "七年级", "一班"],
                ["1002", "张三", "女", 12, "六年级", "二班"],
                ["1003", "李四", "男", 14, "八年级", "三班"],
            ]
        )
        self.assertIn("名单导入成功，共 3 名学生".encode(), response.data)

        token = self.csrf("/")
        response = self.client.post(
            "/",
            data={"names": "张三\n张三\n不存在\n不存在", "_csrf_token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"1001", response.data)
        self.assertIn(b"1002", response.data)
        self.assertEqual(response.data.count("重名候选".encode()), 2)
        self.assertIn("未找到".encode(), response.data)

        token = self.csrf("/?mode=id")
        response = self.client.post(
            "/",
            data={
                "mode": "id",
                "ids": "1003\n1003\n9999\n9999",
                "_csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'class="result-row'), 2)
        self.assertEqual(response.data.count("李四".encode()), 1)
        self.assertIn("按 ID 查学生".encode(), response.data)
        self.assertIn(b"9999", response.data)

    def test_invalid_import_keeps_existing_roster(self):
        self.login()
        self.import_rows([["1001", "张三", "男", 13, "七年级", "一班"]])
        response = self.import_rows(
            [["2001", "李四", "男", 14, "八年级", "二班"]],
            headers=["错误ID", "姓名", "性别", "年龄", "年级", "班级名称"],
        )
        self.assertIn("表头必须依次为".encode(), response.data)
        with self.app.app_context():
            rows = get_db().execute("SELECT user_id FROM students").fetchall()
            self.assertEqual([row["user_id"] for row in rows], ["1001"])

    def test_query_only_user_cannot_manage_roster(self):
        with self.app.app_context():
            connection = get_db()
            now = utcnow()
            cursor = connection.execute(
                """
                INSERT INTO users
                    (username, display_name, password_hash, is_active, is_superadmin, created_at, updated_at)
                VALUES (?, ?, ?, 1, 0, ?, ?)
                """,
                ("reader", "Reader", generate_password_hash("reader-password-123"), now, now),
            )
            role_id = connection.execute("SELECT id FROM roles WHERE name = '查询员'").fetchone()["id"]
            connection.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (cursor.lastrowid, role_id),
            )
            connection.commit()

        self.login("reader", "reader-password-123")
        response = self.client.get("/roster")
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
