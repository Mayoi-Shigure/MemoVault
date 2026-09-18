"""Local configuration: external environment takes precedence over project .env."""
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
