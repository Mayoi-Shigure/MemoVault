"""Import the application using synthetic secrets, without reading local .env."""
import os
import secrets
from unittest.mock import patch


# Only dotenv file I/O is mocked here; configuration validation stays enabled.
# test_config exercises the real loader against isolated temporary project files.
with patch.dict(os.environ, {
    "APP_ENV": "development",
    "DB_HOST": "localhost",
    "DB_PORT": "3306",
    "DB_USER": "root",
    "DB_NAME": "memovault",
    "SESSION_SECRET": secrets.token_urlsafe(48),
    "DB_PASSWORD": secrets.token_urlsafe(32),
}), patch("dotenv.load_dotenv", return_value=False), patch(
    "mysql.connector.connect", side_effect=AssertionError("Real MySQL is forbidden in tests")
):
    import database
    import main
