#!/usr/bin/env python3
"""
Deployment smoke test — the release gate for "works on a new machine".

Exercises the real system end-to-end against the database in DATABASE_URL:
    1. alembic upgrade head (fresh or existing DB)
    2. boot the actual server (server_main.py) on a test port
    3. register a fake agent through /register (with secret if configured)
    4. push real telemetry: heartbeat, state_duration event, screentime spans
    5. assert the data landed: screen_time row and screen_time_spans row

Usage (from monitoring_tool/server):
    python -m scripts.deployment_smoke_test
Exit code 0 = deployable, non-zero = broken. Prints PASS/FAIL per step.

Notes:
    - Uses only stdlib + the server's own dependencies.
    - Safe to run against a dev DB: it creates one throwaway agent named
      smoke-test-<pid> and its telemetry rows.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
PORT = int(os.getenv('SMOKE_TEST_PORT', '5099'))
BASE = f"http://127.0.0.1:{PORT}"

_failures = []


def step(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(name)
    return ok


def http(method, path, body=None, headers=None, timeout=15):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or '{}')
        except Exception:
            return e.code, {}


def main():
    os.chdir(SERVER_DIR)
    from dotenv import load_dotenv
    # override=True mirrors server_config.py: .env beats inherited shell env,
    # so the secret we send matches the one the spawned server loads.
    load_dotenv(override=True)

    if not os.getenv('DATABASE_URL'):
        print("DATABASE_URL not set — aborting")
        return 2

    py = sys.executable

    # ── 0. Update-signing configuration ──────────────────────────────
    # If UPDATE_SIGNING_KEY is unset the server serves an EMPTY signature,
    # and every agent that has a signing_key configured rejects the update
    # silently ("Server response has no signature"). Auto-update then never
    # works and nothing in the logs says why - so gate the release on it.
    step("UPDATE_SIGNING_KEY is configured (agents reject unsigned updates)",
         bool(os.getenv('UPDATE_SIGNING_KEY')),
         "set UPDATE_SIGNING_KEY in .env - it must match the agent's "
         "updates.signing_key" if not os.getenv('UPDATE_SIGNING_KEY') else "")

    # ── 1. Migrations ────────────────────────────────────────────────
    r = subprocess.run([py, '-m', 'alembic', 'upgrade', 'head'],
                       capture_output=True, text=True, timeout=300)
    if not step("alembic upgrade head", r.returncode == 0,
                r.stderr.strip().splitlines()[-1] if r.returncode != 0 and r.stderr else ""):
        return 1

    # ── 2. Boot the real server ──────────────────────────────────────
    env = {**os.environ, 'SERVER_PORT': str(PORT),
           'RUN_BACKGROUND_TASKS': '0'}  # smoke test asserts ingestion, not jobs
    if not os.getenv('REGISTRATION_SECRET'):
        # Without a secret, /register only works in dev mode.
        env['FLASK_ENV'] = 'development'
    proc = subprocess.Popen([py, 'server_main.py'], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(60):
            try:
                status, _body = http('GET', '/')
                if status == 200:
                    up = True
                    break
            except Exception:
                pass
            if proc.poll() is not None:
                break
            time.sleep(1)
        if not step("server boots and serves health endpoint", up):
            return 1

        # ── 3. Agent registration ────────────────────────────────────
        agent_uuid = str(uuid.uuid4())
        headers = {}
        secret = os.getenv('REGISTRATION_SECRET')
        if secret:
            headers['X-Registration-Secret'] = secret
        status, body = http('POST', '/register', {
            'agent_id': agent_uuid,
            'hostname': f'smoke-test-{os.getpid()}',
            'os_version': 'Windows 11 Pro',
            'agent_version': '4.0.1',
        }, headers)
        api_key = body.get('api_key', '')
        agent_id = (body.get('agent') or {}).get('agent_id') or agent_uuid
        if not step("agent registration returns api_key",
                    status in (200, 201) and bool(api_key), f"HTTP {status}: {body}"):
            return 1
        # /register returns a JWT in the api_key field; agents send it as a
        # Bearer token (X-API-Key expects the sk_live scheme, not JWTs).
        auth = {'Authorization': f'Bearer {api_key}',
                'X-Agent-ID': str(agent_id)}

        # ── 4. Telemetry ─────────────────────────────────────────────
        status, body = http('POST', '/heartbeat', {'status': 'online'}, auth)
        step("heartbeat accepted", status == 200, f"HTTP {status}: {body}")

        now = datetime.now()
        status, body = http('POST', '/api/v1/telemetry/event', {
            'type': 'state_duration',
            'state': 'active',
            'duration_seconds': 120,
            'timestamp': now.isoformat(),
        }, auth)
        step("state_duration event processed (process_screentime_delta)",
             status == 200 and body.get('status') == 'success',
             f"HTTP {status}: {body}")

        # Spans use UTC-aware ISO timestamps, matching the agent's
        # _create_span format exactly.
        from datetime import timezone as _tz
        utc_now = datetime.now(_tz.utc)
        span_start = utc_now - timedelta(minutes=10)
        span_end = utc_now - timedelta(minutes=5)
        status, body = http('POST', '/api/v1/telemetry/screentime-spans', {
            'spans': [{
                'span_id': f'{agent_id}-active-{int(span_start.timestamp()*1000)}',
                'state': 'active',
                'start_time': span_start.isoformat(),
                'end_time': span_end.isoformat(),
                'duration_seconds': 300,
            }],
        }, auth)
        step("screentime span stored", status == 200, f"HTTP {status}: {body}")

        # Cumulative daily totals (process_screentime_event).
        status, body = http('POST', '/api/v1/telemetry/screentime', {
            'active_seconds': 600,
            'idle_seconds': 60,
            'locked_seconds': 30,
            'away_seconds': 0,
            'current_state': 'active',
            'timestamp': now.isoformat(),
        }, auth)
        step("screentime totals processed (process_screentime_event)",
             status == 200, f"HTTP {status}: {body}")

        # App session (process_app_switch_event -> app_sessions + app_usage).
        sess_start = now - timedelta(minutes=5)
        status, body = http('POST', '/api/v1/telemetry/app-switch', {
            'app': 'chrome.exe',
            'friendly_name': 'Google Chrome',
            'category': 'browser',
            'window_title': 'Smoke Test',
            'timestamp': now.isoformat(),
            'session_start': sess_start.isoformat(),
            'session_end': now.isoformat(),
            'total_seconds': 300,
        }, auth)
        step("app-switch processed (process_app_switch_event)",
             status == 200, f"HTTP {status}: {body}")

        # Domain session (process_domain_switch_event -> domain_sessions/usage).
        status, body = http('POST', '/api/v1/telemetry/domain-switch', {
            'domain': 'example.com',
            'browser': 'chrome',
            'url': 'https://example.com/page',
            'timestamp': now.isoformat(),
            'session_start': sess_start.isoformat(),
            'session_end': now.isoformat(),
            'total_seconds': 300,
        }, auth)
        step("domain-switch processed (process_domain_switch_event)",
             status == 200, f"HTTP {status}: {body}")

        # ── 5. Assert the data actually landed ───────────────────────
        import sqlalchemy as sa
        eng = sa.create_engine(os.environ['DATABASE_URL'])
        with eng.connect() as c:
            st = c.execute(sa.text(
                "SELECT active_seconds FROM screen_time WHERE agent_id = :a"
            ), {'a': str(agent_id)}).fetchone()
            step("screen_time row exists with active seconds",
                 st is not None and (st[0] or 0) >= 120,
                 f"row={st}")

            sp = c.execute(sa.text(
                "SELECT count(*) FROM screen_time_spans WHERE agent_id = :a"
            ), {'a': str(agent_id)}).scalar()
            step("screen_time_spans row exists", (sp or 0) >= 1, f"count={sp}")

            for table in ('app_sessions', 'app_usage',
                          'domain_sessions', 'domain_usage'):
                n = c.execute(sa.text(
                    f"SELECT count(*) FROM {table} WHERE agent_id = :a"
                ), {'a': str(agent_id)}).scalar()
                step(f"{table} row exists", (n or 0) >= 1, f"count={n}")

        # ── 6. Background sync (dashboard reads these aggregates) ─────
        with eng.begin() as c:
            c.execute(sa.text(
                "SELECT sync_app_usage_from_sessions(CURRENT_DATE)"))
            c.execute(sa.text(
                "SELECT sync_domain_usage_from_sessions(CURRENT_DATE)"))
            rows = c.execute(sa.text(
                "SELECT * FROM sync_screen_time_from_sessions(CURRENT_DATE)"
            )).fetchall()
        step("ScreenTimeSync stored functions run clean", True,
             f"{len(rows)} agent row(s) synced")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if _failures:
        print(f"SMOKE TEST FAILED — {len(_failures)} step(s): {', '.join(_failures)}")
        return 1
    print("SMOKE TEST PASSED — deployable.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
