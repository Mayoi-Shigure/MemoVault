import base64
import json
import os
import secrets
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from csrf_test_support import csrf_post
from security import is_csrf_token
from mysql.connector import Error as DatabaseError

from offline_test_support import main


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = {"id": 17, "username": "FixtureAccount", "email": "abc@example.com",
                    "password_hash": main.hash_password(" secret-password ")}

    def setUp(self):
        guard = patch('mysql.connector.connect', side_effect=AssertionError('Real MySQL is forbidden'))
        guard.start()
        self.addCleanup(guard.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        for name, value in [("get_common_context", {"sidebar_types": [], "sidebar_records": [], "ungrouped_count": 0}),
                            ("get_notes", []), ("get_types", [])]:
            p = patch.object(main, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def sign_session(self, data):
        cookie = TimestampSigner(main.session_secret).sign(base64.b64encode(json.dumps(data).encode())).decode()
        self.client.cookies.set("session", cookie, domain="testserver.local", path="/")

    def authenticate(self, login=" FixtureAccount "):
        with patch.object(main, "get_user_by_login", return_value=self.user) as lookup:
            response = csrf_post(self.client, "/login", data={"login": login, "password": " secret-password "}, follow_redirects=False)
            lookup.assert_called_once_with(login.strip())
        return response

    def test_secret_required_at_initialization(self):
        for value in (None, "", "   "):
            env = dict(os.environ)
            env.pop("SESSION_SECRET", None)
            env["DB_PASSWORD"] = secrets.token_urlsafe(32)
            if value is not None:
                env["SESSION_SECRET"] = value
            result = subprocess.run([sys.executable, "-c", "from unittest.mock import patch\nwith patch('dotenv.load_dotenv', return_value=False):\n    import main"], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SESSION_SECRET must be set", result.stderr)

    def test_success_cookie_and_dashboard(self):
        for identity in (" FixtureAccount ", " ABC@example.com "):
            response = self.authenticate(identity)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/")
            cookie_header = response.headers["set-cookie"].lower()
            self.assertIn("httponly", cookie_header)
            self.assertIn("samesite=lax", cookie_header)
            self.assertNotIn("secure", cookie_header)
            payload = TimestampSigner(main.session_secret).unsign(self.client.cookies.get("session"))
            session = json.loads(base64.b64decode(payload))
            self.assertEqual(set(session), {"user_id", "csrf_token"})
            self.assertEqual(session["user_id"], 17)
            self.assertTrue(is_csrf_token(session["csrf_token"]))
            with patch.object(main, "get_user_by_id", return_value={"id": 17, "username": "FixtureAccount"}) as lookup:
                dashboard = self.client.get("/")
                lookup.assert_called_once_with(17)
            self.assertIn('data-en="Signed in" data-zh="已登录"', dashboard.text)
            self.assertIn("FixtureAccount", dashboard.text)
            self.assertIn('action="/logout" method="POST"', dashboard.text)

    def test_global_account_on_all_authenticated_pages(self):
        self.sign_session({"user_id": 17})
        user = {"id": 17, "username": '<User & "name">'}
        note = {"id": 1, "title": "Example", "content": "", "url": "",
                "type_id": None, "created_at": "", "updated_at": ""}
        with patch.object(main, "get_user_by_id", return_value=user), \
                patch.object(main, "get_note", return_value=note):
            for path in ("/", "/notes", "/notes/1", "/notes/1/edit"):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('id="account-trigger-sidebar"', response.text)
                    self.assertIn('id="account-trigger-mobile"', response.text)
                    self.assertIn('&lt;User &amp; &#34;name&#34;&gt;', response.text)
                    self.assertNotIn(user["username"], response.text)
                    self.assertIn('data-en="Sign out" data-zh="退出登录"', response.text)
                    self.assertEqual(response.text.count('action="/logout" method="POST"'), 1)
                    content = response.text.split('<main class="page-shell">')[1].split('</main>')[0]
                    self.assertNotIn('/logout', content)

    def test_unknown_and_wrong_password_have_identical_response(self):
        bodies = []
        for user in (None, self.user):
            with patch.object(main, "get_user_by_login", return_value=user):
                response = csrf_post(self.client, "/login", data={"login": " <script> ", "password": "wrong-secret"})
            self.assertEqual(response.status_code, 401)
            self.assertIn("用户名、邮箱或密码错误。", response.text)
            self.assertIn('value="&lt;script&gt;"', response.text)
            self.assertNotIn("wrong-secret", response.text)
            payload = TimestampSigner(main.session_secret).unsign(self.client.cookies.get("session"))
            self.assertNotIn("user_id", json.loads(base64.b64decode(payload)))
            bodies.append(response.text)
        self.assertEqual(*bodies)

    def test_empty_fields_and_corrupt_hash_are_safe(self):
        self.assertEqual(csrf_post(self.client, "/login", data={}).status_code, 401)
        with patch.object(main, "get_user_by_login", return_value=dict(self.user, password_hash="bad hash")):
            response = csrf_post(self.client, "/login", data={"login": "user", "password": "password"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("bad hash", response.text)

    def test_database_error_is_not_exposed(self):
        with patch.object(main, "get_user_by_login", side_effect=DatabaseError("PRIVATE SQL")):
            response = csrf_post(self.client, "/login", data={"login": "user", "password": "password"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("PRIVATE SQL", response.text)

    def test_success_replaces_prior_session(self):
        self.sign_session({"user_id": 5, "old_value": "remove me"})
        self.authenticate()
        payload = TimestampSigner(main.session_secret).unsign(self.client.cookies.get("session"))
        session = json.loads(base64.b64decode(payload))
        self.assertEqual(set(session), {"user_id", "csrf_token"})
        self.assertEqual(session["user_id"], 17)
        self.assertTrue(is_csrf_token(session["csrf_token"]))

    def test_logout_and_anonymous_access(self):
        self.authenticate()
        response = csrf_post(self.client, "/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        self.assertIn("expires=Thu, 01 Jan 1970", response.headers["set-cookie"])
        self.assertIsNone(self.client.cookies.get("session"))
        with patch.object(main, "get_user_by_id") as lookup:
            dashboard = self.client.get("/", follow_redirects=False)
            lookup.assert_not_called()
        self.assertNotIn("Signed in as", dashboard.text)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Save anything useful.", dashboard.text)
        protected = self.client.get("/notes", follow_redirects=False)
        self.assertEqual(protected.status_code, 303)
        self.assertEqual(protected.headers["location"], "/login")
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_deleted_user_and_invalid_identity_clear_session(self):
        for identity in (17, "17", -1, True):
            self.client.cookies.clear()
            self.sign_session({"user_id": identity})
            with patch.object(main, "get_user_by_id", return_value=None):
                response = self.client.get("/", follow_redirects=False)
            self.assertNotIn("Signed in as", response.text)
            self.assertIn("expires=Thu, 01 Jan 1970", response.headers["set-cookie"])

    def test_tampered_cookie_is_anonymous(self):
        self.client.cookies.set("session", "tampered-cookie")
        with patch.object(main, "get_user_by_id") as lookup:
            response = self.client.get("/", follow_redirects=False)
            lookup.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Save anything useful.", response.text)
        self.assertNotIn("Signed in as", response.text)

    def test_landing_is_public_without_loading_private_data(self):
        with patch.object(main, "get_common_context") as common, patch.object(main, "get_notes") as records:
            response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        common.assert_not_called()
        records.assert_not_called()
        self.assertIn('href="/register"', response.text)
        self.assertIn('href="/login"', response.text)
        self.assertIn('data-zh="个人互联网记忆库"', response.text)
        self.assertNotIn('account-trigger', response.text)
        self.assertNotIn('csrf_token', response.text)
        for path in ("/notes", "/notes/1", "/notes/1/edit", "/notes/not-an-int/edit"):
            protected = self.client.get(path, follow_redirects=False)
            self.assertEqual(protected.status_code, 303)
            self.assertEqual(protected.headers["location"], "/login")

    def test_login_ui_and_registration_stay_public(self):
        login = self.client.get("/login")
        self.assertIn('action="/login" method="POST"', login.text)
        self.assertNotIn("disabled", login.text)
        self.assertNotIn("sidebar", login.text)
        self.assertEqual(self.client.get("/register").status_code, 200)


if __name__ == "__main__":
    unittest.main()
