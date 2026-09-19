# MemoVault development configuration and session security

Use PowerShell in the project directory. A virtual environment is recommended:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` is the single supported installation entry point and pins the
runtime and TestClient versions. Tests use standard-library unittest; pytest is
not required. This document covers development/production configuration and security behavior.

## Local configuration

Create `.env` only if it does not already exist (an empty template may already
have been created for you):

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

Edit `.env` locally and fill both secret fields; the other settings retain local defaults:

```dotenv
APP_ENV=development
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_NAME=memovault
DB_PASSWORD=
SESSION_SECRET=
```

- `DB_PASSWORD`: your existing local MySQL password. There is no default password.
- `SESSION_SECRET`: a strong random value, kept stable across restarts. Generate
  one locally, paste it into `.env`, and do not share the output:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Quote values containing spaces or `#` (for example, use single quotes when the
value does not itself contain a single quote). Variable interpolation is disabled,
so `${...}` inside a secret remains literal. Do not trim meaningful password spaces.

`config.py` locates `.env` using its own absolute file path, not the terminal's
working directory. Loading happens before the application's first environment
read. Existing system/PowerShell variables take precedence, including empty
values: an empty external value will cause validation to fail rather than fall
back to `.env`. If old terminal overrides are unwanted, remove them in that
terminal before starting the application.

Missing, empty or whitespace-only `SESSION_SECRET` or `DB_PASSWORD` stops startup
with a configuration error naming the variable, without printing its value.
This validates presence, not whether a password is accepted by MySQL or whether
an independently chosen signing key is sufficiently random. Restart after editing `.env`.

`.env` is ignored by Git and must never be committed. `.env.example` intentionally
contains no secret values and can be committed. Do not force-add `.env`.

## Start

After filling `.env`, future launches do not require setting secrets in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Run this command from the project directory: configuration loading is independent
of the current directory, but existing static/template paths remain relative.
The legacy `server.py` entry point is disabled. Fresh databases use
`database/schema.sql`; existing single-user databases require the manual ownership
procedure in `database/migrations/README.md`. Do not apply the fresh schema to an
existing database.
These instructions do not run migrations or change database accounts.

## Session and CSRF behavior

SessionMiddleware uses HttpOnly, SameSite=Lax and a browser-session cookie
(`max_age=None`); local HTTP retains `https_only=False`. Cookies are signed, not
encrypted. Authenticated sessions contain `user_id` and `csrf_token`; anonymous
login/registration forms also provision a CSRF token.

Successful login clears the previous session and generates a new CSRF token.
All nine current POST routes, including login, registration and logout, require
the session's hidden `csrf_token` form field. CSRF is separate from authentication
and Record/Type ownership checks. For requests that pass authentication, invalid CSRF returns 403 before writes.
Unauthenticated protected routes redirect to login before CSRF validation.
The Account menu first opens a confirmation dialog; confirming sends POST
`/logout` with CSRF and clears the cookie session. GET `/logout` remains 405.
Changing `SESSION_SECRET` invalidates existing signed cookies.

## Offline tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

Discovery includes configuration, Session, registration, ownership and CSRF tests.
Application tests import through `offline_test_support.py` with synthetic secrets
and mocked dotenv file I/O, so they never read your `.env`. Configuration tests
exercise the real loader in temporary project copies and isolated subprocesses.
Database access is mocked or uses the in-memory SQLite adapter; real MySQL
connections are forbidden in automated tests.

The discovery suite contains only automated tests and their helpers. Test identities
and passwords are synthetic fixtures, not application defaults. SQLite and mocks
do not validate MySQL DDL, timestamp conversion, locking, or collation semantics.

## Production configuration

On Ubuntu 24.04, set `APP_ENV=production`, configure `DB_HOST`, `DB_PORT`,
`DB_USER`, `DB_PASSWORD`, `DB_NAME`, and supply a strong `SESSION_SECRET` through
service environment variables or the project `.env`. Create a dedicated MySQL
account with appropriate permissions and set `DB_USER` to that account; production
must not use the local `root` default. No database accounts or schemas are changed
by configuration loading.

`APP_ENV=production` automatically sets `https_only=True`; browsers receive the
Secure session cookie over HTTPS. Terminate HTTPS at Nginx and proxy to Uvicorn.
Start Uvicorn from the project directory, without development `--reload`.
`APP_ENV` accepts exactly `development` or `production`; other values fail startup.
`DB_PORT` must be an integer from 1 to 65535. Explicitly blank `DB_HOST`, `DB_USER`,
or `DB_NAME` also fails startup. Configuration is loaded once; restart the service
after changes. Existing Windows HTTP development commands remain unchanged.
