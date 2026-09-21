import unittest
from unittest.mock import patch, MagicMock

from fastapi import Request
from fastapi.testclient import TestClient
from csrf_test_support import csrf_post
from mysql.connector import Error as DatabaseError

from offline_test_support import main, database
from security import verify_password


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        guard = patch('mysql.connector.connect', side_effect=AssertionError('Real MySQL is forbidden'))
        guard.start()
        self.addCleanup(guard.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.request = Request({"type": "http", "method": "GET", "path": "/register",
                                "query_string": b"", "headers": [], "scheme": "http",
                                "server": ("testserver", 80), "router": main.app.router, "session": {}})
        self.common = patch.object(main, "get_common_context", return_value={
            "sidebar_types": [], "sidebar_records": [], "ungrouped_count": 0})
        self.common.start()
        self.addCleanup(self.common.stop)

    def register(self, username, email, password, confirm_password):
        return csrf_post(self.client, '/register', data=dict(username=username, email=email,
            password=password, confirm_password=confirm_password), follow_redirects=False)

    def test_validation_boundaries(self):
        valid = ("user", "user@example.com", "password", "password")
        for index, value in [(0, ""), (0, "a" * 51), (1, ""), (1, "a" * 256),
                             (1, "a@b"), (1, "a@@b.com"), (1, "a@b..com"),
                             (1, "a b@example.com"), (2, ""), (2, "1234567"), (3, "different")]:
            with self.subTest(index=index, value=value):
                fields = list(valid)
                fields[index] = value
                self.assertIsNotNone(main.validate_registration(*fields))
        self.assertIsNone(main.validate_registration("a" * 50, "a" * 243 + "@example.com", "password", "password"))

    def test_success_trims_identity_and_hashes_untrimmed_password(self):
        with patch.object(main, "create_user", return_value=1) as create:
            response = self.register(" FixtureAccount ", " ABC@example.com ", " password ", " password ")
        username, email, hashed = create.call_args.args
        self.assertEqual((username, email), ("FixtureAccount", "ABC@example.com"))
        self.assertTrue(verify_password(" password ", hashed))
        self.assertNotEqual(hashed, " password ")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/register?success=1")
        landing = self.client.get("/", follow_redirects=False)
        self.assertEqual(landing.status_code, 200)
        self.assertIn("Save anything useful.", landing.text)
        self.assertEqual(self.client.get("/notes", follow_redirects=False).headers["location"], "/login")

    def test_validation_failure_preserves_escaped_identity_only(self):
        with patch.object(main, "create_user") as create:
            response = self.register(' <script> ', " a@example.com ", "secret", "secret")
        create.assert_not_called()
        html = response.text
        self.assertEqual(response.status_code, 400)
        self.assertIn('value="&lt;script&gt;"', html)
        self.assertIn('value="a@example.com"', html)
        self.assertNotIn("secret", html)

    def test_database_errors_are_safe_and_specific(self):
        for conflicts, message in [((1, 0), "用户名已被使用"), ((0, 1), "邮箱已被使用"),
                                   ((0, 0), "用户名或邮箱已被使用")]:
            with self.subTest(conflicts=conflicts), patch.object(main, "create_user", side_effect=DatabaseError("PRIVATE SQL", errno=1062)), patch.object(main, "get_user_conflicts", return_value=conflicts):
                response = self.register("FixtureAccount", "abc@example.com", "password", "password")
                self.assertEqual(response.status_code, 409)
                self.assertIn(message, response.text)
                self.assertNotIn("PRIVATE SQL", response.text)
        with patch.object(main, "create_user", side_effect=DatabaseError("PRIVATE SQL")), patch.object(main, "get_common_context", side_effect=DatabaseError("PRIVATE SQL")):
            response = self.register("user", "a@example.com", "password", "password")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("PRIVATE SQL", response.text)

    def test_get_and_success_page(self):
        for success in ("", "1"):
            response = main.register_page(self.request, success)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["registration_success"], success == "1")

    def test_insert_failure_rolls_back_and_closes(self):
        connection = MagicMock()
        connection.cursor.return_value.execute.side_effect = DatabaseError(errno=1062)
        with patch.object(database, "get_db_connection", return_value=connection):
            with self.assertRaises(DatabaseError):
                database.create_user("user", "a@example.com", "hash")
        connection.rollback.assert_called_once()
        connection.cursor.return_value.close.assert_called_once()
        connection.close.assert_called_once()

    def test_existing_pages_render(self):
        with patch.object(main, "get_current_user", return_value={"id": 1}), patch.object(main, "get_notes", return_value=[]), patch.object(main, "get_types", return_value=[]):
            self.assertEqual(main.home(self.request).status_code, 200)
            self.assertEqual(main.notes(self.request).status_code, 200)


if __name__ == "__main__":
    unittest.main()
