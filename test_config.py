"""Real dotenv loading in disposable projects; never read the user's .env."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        self.cwd = Path(temporary.name) / 'other-directory'
        self.cwd.mkdir()
        (self.cwd / 'static').mkdir()
        for name in ('config.py', 'main.py', 'database.py', 'security.py', 'ui_helpers.py'):
            shutil.copyfile(Path(__file__).resolve().parent / name, self.root / name)
        self.env = dict(os.environ)
        for key in ('APP_ENV', 'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_NAME',
                    'DB_PASSWORD', 'SESSION_SECRET', 'PYTHONPATH', 'PYTHON_DOTENV_DISABLED'):
            self.env.pop(key, None)
        self.env['DB_PASSWORD'] = secrets.token_urlsafe(32)
        self.env['SESSION_SECRET'] = secrets.token_urlsafe(48)

    def run_code(self, code='import main'):
        prelude = (
            'import sys\nfrom unittest.mock import patch\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'guard = patch("mysql.connector.connect", side_effect=AssertionError("Real MySQL is forbidden"))\n'
            'guard.start()\n'
        )
        return subprocess.run([sys.executable, '-B', '-c', prelude + code, str(self.root)],
                              cwd=self.cwd, env=self.env, capture_output=True, text=True)

    def assert_config_failure(self, variable):
        result = self.run_code()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{variable} must be set', result.stderr)
        self.assertEqual(result.stdout, '')
        for key in ('DB_PASSWORD', 'SESSION_SECRET'):
            value = self.env.get(key)
            if value and value.strip():
                self.assertNotIn(value, result.stderr)

    def test_missing_session_secret_fails(self):
        self.env.pop('SESSION_SECRET')
        self.assert_config_failure('SESSION_SECRET')

    def test_blank_session_secret_fails(self):
        for value in ('', '   ', '\t'):
            with self.subTest(blank=repr(value)):
                self.env['SESSION_SECRET'] = value
                self.assert_config_failure('SESSION_SECRET')

    def test_missing_db_password_fails_at_startup(self):
        self.env.pop('DB_PASSWORD')
        self.assert_config_failure('DB_PASSWORD')

    def test_blank_db_password_fails_at_startup(self):
        for value in ('', '   ', '\t'):
            with self.subTest(blank=repr(value)):
                self.env['DB_PASSWORD'] = value
                self.assert_config_failure('DB_PASSWORD')

    def write_dotenv(self):
        password, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        (self.root / '.env').write_text(f'DB_PASSWORD={password}\nSESSION_SECRET={secret}\n', encoding='utf-8')
        return password, secret

    def test_external_environment_takes_precedence(self):
        self.write_dotenv()
        result = self.run_code('import os\nbefore = {k: os.environ[k] for k in ("DB_PASSWORD", "SESSION_SECRET")}\n'
                               'import main\nfrom config import require_environment\n'
                               'assert all(require_environment(k) == v for k, v in before.items())\n'
                               'assert main.session_secret == before["SESSION_SECRET"]')
        self.assertEqual(result.returncode, 0)

    def test_project_dotenv_loads_from_another_directory(self):
        self.env.pop('DB_PASSWORD')
        self.env.pop('SESSION_SECRET')
        password, secret = self.write_dotenv()
        (self.cwd / '.env').write_text('DB_PASSWORD=\nSESSION_SECRET=\n', encoding='utf-8')
        result = self.run_code('import main\nfrom config import require_environment\n'
                               f'assert require_environment("DB_PASSWORD") == {password!r}\n'
                               f'assert main.session_secret == {secret!r}')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_empty_external_values_do_not_fall_back_to_dotenv(self):
        self.write_dotenv()
        for key in ('DB_PASSWORD', 'SESSION_SECRET'):
            with self.subTest(variable=key):
                saved = self.env[key]
                self.env[key] = ''
                self.assert_config_failure(key)
                self.env[key] = saved

    def test_secret_characters_and_spaces_are_preserved(self):
        self.env.pop('DB_PASSWORD')
        value = '  ' + secrets.token_urlsafe(32) + '${SESSION_SECRET}#literal  '
        (self.root / '.env').write_text(f"DB_PASSWORD='{value}'\n", encoding='utf-8')
        result = self.run_code('import main\nfrom config import require_environment\n'
                               f'assert require_environment("DB_PASSWORD") == {value!r}')
        self.assertEqual(result.returncode, 0)

    def test_database_entry_validates_before_connecting(self):
        self.env.pop('DB_PASSWORD')
        result = self.run_code('import database\ndatabase.get_db_connection()')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DB_PASSWORD must be set', result.stderr)
        self.assertNotIn('Real MySQL is forbidden', result.stderr)

    def test_development_defaults_and_database_arguments(self):
        result = self.run_code('''import config, database
assert config.APP_ENV == "development"
assert config.SESSION_HTTPS_ONLY is False
with patch("mysql.connector.connect") as connect:
    database.get_db_connection()
    connect.assert_called_once_with(host="localhost", port=3306, user="root",
        password=config.DB_PASSWORD, database="memovault")
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_database_settings_from_dotenv_and_external_overrides(self):
        settings = dict(APP_ENV='production', DB_HOST='db.example.invalid',
                        DB_PORT='3307', DB_USER='memovault_app', DB_NAME='vault')
        self.write_dotenv()
        with (self.root / '.env').open('a', encoding='utf-8') as stream:
            stream.write(''.join(f'{key}={value}\n' for key, value in settings.items()))
        for external in (False, True):
            with self.subTest(external=external):
                if external:
                    settings = dict(APP_ENV='development', DB_HOST='external.example.invalid',
                                    DB_PORT='3308', DB_USER='external_app', DB_NAME='external_vault')
                    self.env.update(settings)
                result = self.run_code(f'''import config, database
assert config.APP_ENV == {settings['APP_ENV']!r}
assert config.SESSION_HTTPS_ONLY == {settings['APP_ENV'] == 'production'!r}
with patch("mysql.connector.connect") as connect:
    database.get_db_connection()
    connect.assert_called_once_with(host={settings['DB_HOST']!r}, port={int(settings['DB_PORT'])},
        user={settings['DB_USER']!r}, password=config.DB_PASSWORD, database={settings['DB_NAME']!r})
''')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_session_cookie_secure_matches_environment(self):
        for environment in ('development', 'production'):
            with self.subTest(environment=environment):
                self.env['APP_ENV'] = environment
                result = self.run_code(f'''import main
from fastapi.testclient import TestClient
# Replace rendering only; exercise the application's actual SessionMiddleware.
from starlette.responses import PlainTextResponse
def render(request):
    request.session["fixture"] = True
    return PlainTextResponse("fixture")
main.render_login = render
with TestClient(main.app, base_url="https://testserver") as client:
    response = client.get("/login")
    assert response.status_code == 200
    flags = {{part.strip().lower() for part in response.headers["set-cookie"].split(";")}}
    assert ("secure" in flags) == {environment == 'production'!r}
    assert "httponly" in flags
    assert "samesite=lax" in flags
''')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_environment_and_database_settings_fail_fast(self):
        for key, values in {
            'APP_ENV': ('', 'prod', 'Production', ' '),
            'DB_PORT': ('', 'abc', '3306.5', '0', '-1', '65536'),
            'DB_HOST': ('', ' '), 'DB_USER': ('', ' '), 'DB_NAME': ('', ' '),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.env[key] = value
                    result = self.run_code('import config')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f'{key} must be', result.stderr)
            self.env.pop(key)

    def test_offline_helper_ignores_dotenv_and_host_configuration(self):
        shutil.copyfile(Path(__file__).resolve().parent / 'offline_test_support.py',
                        self.root / 'offline_test_support.py')
        (self.root / '.env').write_text('APP_ENV=invalid\nDB_PORT=invalid\n', encoding='utf-8')
        self.env.update(APP_ENV='production', DB_PORT='invalid')
        result = self.run_code('''with patch("dotenv.main.DotEnv", side_effect=AssertionError("dotenv file access forbidden")):
    import offline_test_support
import config
assert config.APP_ENV == "development"
assert config.DB_PORT == 3306
try:
    offline_test_support.database.get_db_connection()
except AssertionError as error:
    assert "Real MySQL is forbidden" in str(error)
else:
    raise AssertionError("MySQL guard was bypassed")
''')
        self.assertEqual(result.returncode, 0, result.stderr)
