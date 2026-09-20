# Production deployment and operations

MemoVault's first production deployment is complete at [memo.nemubox.com](https://memo.nemubox.com).
The operator reports Ubuntu 24.04 LTS on a DigitalOcean Droplet, Nginx/Certbot HTTPS,
systemd running Uvicorn as `deploy`, and MySQL 8 on localhost. HTTP redirects to HTTPS;
UFW permits only SSH/HTTP/HTTPS, SSH password authentication and root login are disabled.

Request path: Browser → HTTPS → Nginx :443 → Uvicorn 127.0.0.1:8000 → FastAPI → MySQL 127.0.0.1:3306.

The following is a fresh-server reproduction guide, not a transcript of the live
configuration. `/home/deploy/MemoVault`, service names and retention values below
are examples to adapt consistently. Do not reinitialize the existing production database.
No live server changes are performed by updating this document.

## 1. Ubuntu and SSH access

Using an administrator account on Ubuntu 24.04 LTS:

```sh
sudo apt update
sudo apt install git python3 python3-venv python3-pip mysql-server nginx certbot python3-certbot-nginx ufw cron
sudo adduser deploy
sudo usermod -aG sudo deploy
sudo systemctl enable --now mysql nginx cron
```

Skip account creation if `deploy` already exists. Provision its `~/.ssh/authorized_keys`
privately, owned by `deploy`, with directory mode 700 and file mode 600. Confirm a
second SSH session can log in with a key and use sudo before restricting access.
Keep the original session and Droplet console access available during changes.

Set the following in an administrator-managed file under `/etc/ssh/sshd_config.d/`:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
```

Inspect existing snippets, including cloud-init settings: OpenSSH generally uses
the first obtained value. Validate syntax with `sudo sshd -t`, inspect effective
settings with `sudo sshd -T` (including applicable Match rules), then
`sudo systemctl reload ssh`. Test a new key-authenticated session before closing the old one.
Never copy key contents into this repository or its documentation.

## 2. Clone and install

As `deploy`, substitute the repository clone URL from GitHub's Code menu:

```sh
cd /home/deploy
git clone <repository-clone-url> MemoVault
cd /home/deploy/MemoVault
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Use the pinned requirements, which include the test dependencies. Run Uvicorn from
the repository root because static/template paths are relative. Do not use `server.py`.

## 3. MySQL schema and application account

Configure `/etc/mysql/mysql.conf.d/mysqld.cnf` under `[mysqld]` with
`bind-address = 127.0.0.1`. If MySQL X Plugin is enabled, keep its listener local too
(`mysqlx-bind-address = 127.0.0.1`). Restart MySQL and inspect listeners:

```sh
sudo systemctl restart mysql
sudo ss -lntp
```

For a **fresh database only**, from the repository root:

```sh
sudo mysql < database/schema.sql
sudo env MYSQL_HISTFILE=/dev/null mysql
```

In the interactive administrative client, replace the placeholder privately with
a generated password, using correct SQL string quoting:

```sql
CREATE USER 'memovault_app'@'localhost' IDENTIFIED BY '<generated-app-password>';
GRANT SELECT, INSERT, UPDATE, DELETE ON memovault.* TO 'memovault_app'@'localhost';
```

The fresh schema creates `memovault`, `users`, `types` and `notes`, their indexes,
and ownership foreign keys. Registration creates the six default Types. The app
account needs CRUD permissions, not schema administration. Verify its TCP login
using `mysql -h 127.0.0.1 -u memovault_app -p memovault`; enter the password at the prompt.
Use a separate administrative/backup account for operations requiring more privileges.
Existing single-user installations must follow the [manual migration guide](../database/migrations/README.md).

## 4. Production environment

As `deploy`, create a private `.env` without overwriting an existing one:

```sh
cd /home/deploy/MemoVault
umask 077
test -e .env || cp .env.example .env
chmod 600 .env
```

Edit it locally with these settings; both blank secret fields must be filled privately:

```dotenv
APP_ENV=production
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=memovault_app
DB_PASSWORD=
DB_NAME=memovault
SESSION_SECRET=
```

Generate a signing secret locally with
`.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep its
output private. Keep it stable across restarts; rotation invalidates sessions.
The app loads `.env` into its environment through python-dotenv; pre-existing service
environment variables take precedence. This example relies on that loader rather
than systemd `EnvironmentFile`, whose quoting rules differ. See
[SESSION_SETUP.md](../SESSION_SETUP.md) for quoting and startup validation details.
Production enables Secure cookies; the browser must access the app through HTTPS.

## 5. systemd

Create `/etc/systemd/system/memovault.service` as an administrator:

```ini
[Unit]
Description=MemoVault Uvicorn service
After=network.target mysql.service

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/MemoVault
ExecStart=/home/deploy/MemoVault/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now memovault
sudo systemctl status memovault --no-pager
sudo journalctl -u memovault -n 50 --no-pager
```

No `--reload` is used in production. Only the local proxy is trusted for forwarded
headers. Keep operational logs private; they may contain request details.

## 6. Nginx, firewall and HTTPS

Point the domain's DNS records to the Droplet through the DNS provider; do not
publish the server address in repository documentation. Any AAAA record must also
reach this server correctly. Create `/etc/nginx/sites-available/memovault`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name memo.nemubox.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

For a fresh site, enable it and validate:

```sh
sudo ln -s /etc/nginx/sites-available/memovault /etc/nginx/sites-enabled/memovault
sudo nginx -t
sudo systemctl reload nginx
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status verbose
```

These SSH rules assume the standard SSH port. If customized, allow the actual port
before enabling UFW. Review existing rules and remove unintended inbound allowances;
do not allow 8000 or 3306. Keep MySQL/Uvicorn bound to loopback as well.

Issue the certificate after DNS and HTTP are reachable:

```sh
sudo certbot --nginx -d memo.nemubox.com --redirect
sudo nginx -t
sudo systemctl status certbot.timer --no-pager
sudo certbot renew --dry-run
```

Supply Certbot account contact information privately when prompted. Certbot adds
the TLS configuration and HTTP-to-HTTPS redirect. Confirm automated renewal is
enabled; if the timer is disabled, enable it with `sudo systemctl enable --now certbot.timer`.
Keep certificate keys outside Git.

## 7. Backups and restore tests

**Reported production status:** `~/scripts/backup_memovault.sh` runs daily through
cron on a UTC server, equivalent to 03:00 Beijing time. Recent backups are retained
on the server. A restore test successfully recovered `users`, `types`, `notes`, data,
primary keys, indexes and foreign keys. One backup was copied to the development
computer using SCP. Automated off-server/cloud backups are still pending.

For reproduction, provision a separate localhost backup account and store its
connection settings privately in `/home/deploy/.my.cnf` (owner `deploy`, mode 600).
Use a `[client]` section with host, user and password; never pass a password on a
command line. Grant permissions appropriate to the actual MySQL version and dump
options, including table reads and trigger/routine metadata access. Do not expand
the application's CRUD grants just to run backups. See the
[MySQL mysqldump reference](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html)
for option-specific privileges, including GTID-related requirements.

Create `~/scripts` and `~/backups/memovault` as `deploy` with mode 700. The following
is an example script for `~/scripts/backup_memovault.sh`, not the verified contents
of the installed script. It retains approximately 14 days of successful dumps;
the production retention count was not supplied.

```bash
#!/bin/bash
set -euo pipefail
umask 077
backup_dir=/home/deploy/backups/memovault
mkdir -p "$backup_dir"
dump_file="$backup_dir/memovault_$(date -u +%Y%m%dT%H%M%SZ).sql"
trap 'rm -f -- "$dump_file.partial"' EXIT
/usr/bin/mysqldump --defaults-extra-file=/home/deploy/.my.cnf \
  --single-transaction --no-tablespaces --routines --triggers \
  memovault > "$dump_file.partial"
test -s "$dump_file.partial"
mv -- "$dump_file.partial" "$dump_file"
find "$backup_dir" -maxdepth 1 -type f -name 'memovault_*.sql' -mmin +20160 -delete
```

Set script mode 700, run it once, check its exit status and test restoration before
adding this line to `deploy`'s `crontab -e` on the UTC server:

```cron
0 19 * * * /home/deploy/scripts/backup_memovault.sh >> /home/deploy/backups/backup_memovault.log 2>&1
```

19:00 UTC is 03:00 Asia/Shanghai **the next calendar day**. Verify the server timezone
with `timedatectl` and the installed schedule with `crontab -l`. Inspect failures,
backup timestamps and disk space regularly; cron alone does not guarantee a successful
backup. `--single-transaction` provides an InnoDB snapshot; avoid schema changes
during the dump. A nonempty file alone does not prove restorability.

Restore into an **isolated MySQL 8 instance**, never over the live database for a test.
For a dump produced by the example above (without `--databases`), create an empty
test database and import into it using an administrative client on the isolated host:

```sh
mysql -u root -p -e 'CREATE DATABASE memovault_restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
mysql -u root -p memovault_restore_test < /path/to/private-backup.sql
```

Inspect a dump privately before importing: other dump formats may include `USE`,
`CREATE DATABASE` or qualified names targeting the original database. Do not rely
only on a different database name for isolation. Check table definitions, row counts,
data, primary keys, indexes and ownership foreign keys against the source snapshot,
and test the app against the isolated copy. Do not paste data or query results into Git.
Database dumps do not back up the MySQL account/grants, `.env`, or service configuration;
maintain those separately in secure storage. For disaster recovery, stop writers,
restore a verified backup, validate it, then restart the service.

Copy a completed backup to a private directory outside the repository on the
development computer, substituting the actual filename:

```sh
scp deploy@memo.nemubox.com:/home/deploy/backups/memovault/<backup-filename>.sql <private-local-backup-directory>/
```

Verify transfer integrity with SHA-256 on both ends, restrict access to the copy,
and include it in restore testing. Automating off-server/cloud copies with retention
and failure monitoring remains roadmap work. Never commit real dumps, even temporarily.

## 8. Verification and subsequent releases

- Inspect `systemctl status memovault`, `nginx -t`, `ss -lntp`, effective SSH settings
  and `ufw status verbose`; MySQL and Uvicorn must remain local.
- Check `curl -I http://memo.nemubox.com` redirects to HTTPS, then use
  `curl -sS -o /dev/null -w '%{http_code}\n' https://memo.nemubox.com/login`
  to verify the certificate and a GET response of 200.
- In a browser, verify login/logout and Record/Type operations with temporary test
  content, and confirm session cookies have Secure, HttpOnly and SameSite=Lax.
- For releases, take a verified backup, review the selected revision and any migration
  requirements, install its requirements in the venv, run `python -m unittest discover`
  using that venv, then restart `memovault` and check the site. Never reapply the fresh
  schema to upgrade an existing database. Code rollback must respect schema compatibility.

Offline tests use mocks/SQLite and do not certify MySQL behavior or server security.
The operator-reported deployment/restore facts above were not independently audited
on the server during this documentation update.
