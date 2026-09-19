"""Startup configuration: external environment takes precedence over project .env."""
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False, interpolate=False)


def require_environment(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be set to a non-empty value in the environment or project .env.")
    # Validate whitespace without changing the actual password/secret.
    return value


SESSION_SECRET = require_environment("SESSION_SECRET")
DB_PASSWORD = require_environment("DB_PASSWORD")

APP_ENV = os.environ.get("APP_ENV", "development")
if APP_ENV not in ("development", "production"):
    raise RuntimeError("APP_ENV must be development or production.")
SESSION_HTTPS_ONLY = APP_ENV == "production"

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "root")
DB_NAME = os.environ.get("DB_NAME", "memovault")
for _name in ("DB_HOST", "DB_USER", "DB_NAME"):
    if not globals()[_name].strip():
        raise RuntimeError(f"{_name} must be non-empty.")
try:
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
except ValueError:
    raise RuntimeError("DB_PORT must be an integer between 1 and 65535.") from None
if not 1 <= DB_PORT <= 65535:
    raise RuntimeError("DB_PORT must be an integer between 1 and 65535.")
