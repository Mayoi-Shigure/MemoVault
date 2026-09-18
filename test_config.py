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
        for name in ('config.py', 'main.py', 'database.py', 'security.py'):
            shutil.copyfile(Path(__file__).resolve().parent / name, self.root / name)
        self.env = dict(os.environ)
        for key in ('DB_PASSWORD', 'SESSION_SECRET', 'PYTHONPATH', 'PYTHON_DOTENV_DISABLED'):
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
