# SentinelEdge Server — New Machine Setup

Fresh install package. No database data is included — this creates an empty
schema on the new machine. Existing agents' historical data does NOT travel
with this package.

## What changed from the earlier package

The bundled `.env` in this zip is your old dev `.env` (still pointing at a
local `sentinel_test` database) — **but you don't need to fix it by hand
anymore.** `setup.sh` now generates its own `.env` from scratch, with:

- A freshly generated, per-install database password (previously hardcoded
  and shared across every install of this script).
- `UPDATE_SIGNING_KEY` and `REGISTRATION_SECRET` — previously missing/unset
  entirely, which meant agent update signature verification was silently
  broken and agent registration was wide open to anyone who could reach the
  server.
- `DEFAULT_ADMIN_PASSWORD` — a freshly generated password for the
  auto-created `admin` account, replacing the previous hardcoded
  `changeme123` default.
- `FLASK_ENV=production` instead of `development` — the old value disabled
  the registration-secret enforcement above (and a CORS wildcard guard)
  regardless of whether `REGISTRATION_SECRET` was set.

If a `.env` already exists when `setup.sh` runs, it's backed up to
`.env.backup` first, then overwritten. **Just run `setup.sh` — don't hand-edit
the bundled `.env`.**

## Setup steps

1. **Prerequisites**: Python 3.8+, PostgreSQL 12+, `psql`/`createdb` on PATH,
   `sudo` access (the script manages the `postgresql` systemd service and
   creates the DB role via `sudo -u postgres`). This script targets Linux —
   if the new machine is Windows, use `setup_windows_db.bat` /
   `setup_fresh_db.bat` instead and build `.env` by hand from the same keys.

2. **Run it** from inside this extracted folder — this one command does
   everything:
   ```
   chmod +x setup.sh
   ./setup.sh
   ```
   It checks prerequisites, creates a venv, installs dependencies, creates
   the Postgres role + database, generates `.env` with fresh secrets, runs
   `alembic upgrade head`, verifies the DB connection + migration state, and
   — if systemd is present and no `sentineledge.service` already exists —
   **installs, enables, and starts the server as a systemd service itself.**
   No manual `cp`/path-editing/`systemctl enable` needed; it uses the actual
   install directory and running user automatically. If `sentineledge.service`
   already exists (e.g. you're re-running setup after a code update), it's
   left untouched — restart it yourself with `sudo systemctl restart
   sentineledge`.

   Verified end-to-end in a clean Ubuntu WSL environment: full `setup.sh` run
   → migrations to head → service installed, enabled, running → gunicorn
   actually serving `/` (health check) and `/dashboard/` (redirects to login
   when unauthenticated). Also verified `Restart=always` actually works:
   `sudo kill -9 <gunicorn PID>` and systemd relaunched it within seconds;
   `enable` means it also starts on boot.

   If systemd isn't available (containers, some minimal images), setup.sh
   says so and falls back to printing the manual start commands instead
   (`gunicorn -c gunicorn_config.py server_main:application`).

   The auto-installed service pins `GUNICORN_WORKERS=4`. Left unset,
   `gunicorn_config.py` defaults to `cpu_count()*2+1`, which was **17
   workers** on the 8-core test box — massive overkill for a ~50-agent
   fleet, and it visibly hammered Postgres with 17 simultaneous
   connection-pool setups on every start (transient `SSL SYSCALL error: EOF
   detected` warnings during boot — the app's leader-election logic
   tolerated it and recovered on its own, but there's no reason to invite
   it). Edit `/etc/systemd/system/sentineledge.service`'s
   `Environment=GUNICORN_WORKERS=` line to tune for the actual target
   hardware if 4 isn't right.

3. **Copy the admin password shown at the end** — it's generated per-install
   and only printed once. Log in and change it via the dashboard.

4. **Verify**: open `http://<this-machine>:<PORT from .env>/dashboard/` and
   confirm login works with the generated admin password. Useful commands:
   ```
   sudo systemctl status sentineledge    # check it's up
   sudo systemctl restart sentineledge   # after changing .env or code
   sudo journalctl -u sentineledge -f    # follow logs
   ```

5. **If this server replaces an existing one for the same agent fleet**,
   open the new `.env` and overwrite `UPDATE_SIGNING_KEY` with the OLD
   server's value before starting anything. Agents verify update packages
   against whatever key signed them — a mismatch makes every agent silently
   reject updates. Existing agents will also need to re-register (their API
   keys don't exist in this fresh database), so plan for that separately.
   Restart afterward: `sudo systemctl restart sentineledge`.

6. **Firewall**: open the `PORT` from `.env` if agents or dashboard users are
   on other machines.

`sentineledge.service` is still included in this package as a reference —
useful if you want to inspect what setup.sh installs before running it, or
if you're building the service by hand on a machine where auto-install was
skipped.

## What's included / excluded

Same as before: full server code, migrations, `server_requirements.txt`,
`alembic.ini`. Excluded: `__pycache__/`, `logs/`, and `updates/` +
`scripts/updates/` (agent installer binaries — copy separately or rebuild
via `build_exe.py` if this server needs to keep serving updates to an
existing fleet). No database dump — this is schema-only, not a data
migration.
