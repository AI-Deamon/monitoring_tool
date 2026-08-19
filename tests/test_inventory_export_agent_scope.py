"""
Tests for the single-agent form of the inventory spreadsheet export.

The agent detail page's Inventory tab used to build its own download by
scraping the rendered #inventory-table into CSV in the browser. That produced a
different document from the one the Reports page hands out for the same data —
no title row, no agent identity, no de-duplication, and whichever columns the
table happened to render. (It was also broken: rows were joined on the literal
two-character sequence \\n, so the file was always one long line.)

Both entry points now go through build_inventory_workbook() via
/dashboard/api/inventory/fleet-export.xlsx, with an optional `agent_id`
parameter narrowing the workbook to one agent. These tests pin the three things
that would silently reintroduce two divergent templates:

  * the parameter actually filters, rather than being accepted and ignored
  * the unscoped export still covers the whole fleet
  * multi-tenant scoping still applies when the parameter is supplied, so a
    known agent id is not a way around org isolation
"""

import uuid

import pytest


@pytest.fixture
def app(monkeypatch):
    # monkeypatch, not os.environ[...] = ...: other suites deliberately run
    # against the real DATABASE_URL, and permanently repointing it at in-memory
    # SQLite makes every later test fail with "no such table: agents".
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-unit-tests')

    from server_app import create_app
    from extensions import db

    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


def _make_user(role, org_id=None):
    from auth import DashboardUser
    from extensions import db

    user = DashboardUser(
        username=f'{role}-{uuid.uuid4().hex[:6]}',
        role=role,
        is_active=True,
        session_version=1,
        must_change_password=False,
    )
    if org_id is not None:
        user.org_id = org_id
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    from auth import issue_tab_session

    raw = issue_tab_session(user)
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['session_version'] = user.session_version
        # login_required accepts the bootstrap copy from the cookie when no
        # X-Tab-Session header is present, which is the case for a plain GET.
        sess['tab_token'] = raw


def _make_agent(hostname, org_id=None, apps=()):
    """Create an agent with `apps` = [(name, version), ...]."""
    import server_models
    from extensions import db

    agent_id = uuid.uuid4()
    agent = server_models.Agent(agent_id=agent_id, hostname=hostname)
    if org_id is not None:
        agent.org_id = org_id
    db.session.add(agent)
    db.session.flush()

    for name, version in apps:
        db.session.add(server_models.AppInventory(
            agent_id=agent_id,
            name=name,
            version=version,
            publisher='ACME',
            source='Registry-HKLM',
        ))
    db.session.commit()
    return str(agent_id)


def _workbook_from(resp):
    from io import BytesIO

    from openpyxl import load_workbook

    return load_workbook(BytesIO(resp.data))


def _apps_in(ws):
    """Application names from a sheet, skipping the 4-row title/header block."""
    return [row[0] for row in ws.iter_rows(min_row=5, values_only=True) if row[0]]


class TestAgentScoping:

    def test_agent_id_narrows_the_workbook_to_one_sheet(self, app):
        with app.app_context():
            wanted = _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            _make_agent('beta-host', apps=[('Beta App', '2.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={wanted}'
                )

            assert resp.status_code == 200
            wb = _workbook_from(resp)
            assert wb.sheetnames == ['alpha-host']
            assert _apps_in(wb['alpha-host']) == ['Alpha App']

    def test_scoped_export_excludes_other_agents_applications(self, app):
        """The bug this guards against is the filter being dropped."""
        with app.app_context():
            wanted = _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            _make_agent('beta-host', apps=[('Beta App', '2.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={wanted}'
                )

            wb = _workbook_from(resp)
            everything = [name for ws in wb.worksheets for name in _apps_in(ws)]
            assert 'Beta App' not in everything

    def test_omitting_agent_id_still_exports_the_whole_fleet(self, app):
        with app.app_context():
            _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            _make_agent('beta-host', apps=[('Beta App', '2.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get('/dashboard/api/inventory/fleet-export.xlsx')

            assert resp.status_code == 200
            wb = _workbook_from(resp)
            assert sorted(wb.sheetnames) == ['alpha-host', 'beta-host']

    def test_unknown_agent_id_is_an_empty_document_not_an_error(self, app):
        """An agent with no inventory is an empty state, not a failure."""
        with app.app_context():
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={uuid.uuid4()}'
                )

            assert resp.status_code == 200
            wb = _workbook_from(resp)
            assert wb.sheetnames == ['No data']


class TestTemplateParity:
    """The scoped sheet must be the same document the Reports export produces."""

    def test_sheet_carries_the_title_and_agent_identity_block(self, app):
        with app.app_context():
            wanted = _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={wanted}'
                )

            ws = _workbook_from(resp)['alpha-host']
            assert 'alpha-host' in str(ws.cell(row=1, column=1).value)
            assert wanted in str(ws.cell(row=2, column=1).value)

    def test_sheet_uses_the_shared_column_headers(self, app):
        from report_engine import _INVENTORY_HEADERS

        with app.app_context():
            wanted = _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={wanted}'
                )

            ws = _workbook_from(resp)['alpha-host']
            headers = [c.value for c in ws[4][:len(_INVENTORY_HEADERS)]]
            assert headers == list(_INVENTORY_HEADERS)

    def test_duplicates_collapse_in_the_scoped_export_too(self, app):
        """FR-018 de-duplication is part of the template, not of the fleet path."""
        with app.app_context():
            wanted = _make_agent('alpha-host', apps=[
                ('Alpha App', '1.0'),
                ('Alpha App', '1.0'),
                ('Alpha App', '2.0'),
            ])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={wanted}'
                )

            ws = _workbook_from(resp)['alpha-host']
            assert _apps_in(ws) == ['Alpha App', 'Alpha App']  # 1.0 and 2.0


class TestFilename:

    def test_single_agent_download_is_named_after_the_machine(self, app):
        with app.app_context():
            wanted = _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={wanted}'
                )

            disposition = resp.headers.get('Content-Disposition', '')
            assert 'alpha-host' in disposition
            assert 'fleet' not in disposition

    def test_fleet_download_keeps_its_name(self, app):
        with app.app_context():
            _make_agent('alpha-host', apps=[('Alpha App', '1.0')])
            admin = _make_user('admin')

            with app.test_client() as client:
                _login(client, admin)
                resp = client.get('/dashboard/api/inventory/fleet-export.xlsx')

            assert 'inventory_fleet_' in resp.headers.get('Content-Disposition', '')


class TestMultiTenancy:

    def test_agent_id_does_not_bypass_org_scoping(self, app):
        """
        Narrowing must intersect with the org filter, not replace it. A user who
        learns another org's agent id must still get nothing back.
        """
        with app.app_context():
            foreign = _make_agent('foreign-host', org_id=2,
                                  apps=[('Secret App', '1.0')])
            user = _make_user('user', org_id=1)

            with app.test_client() as client:
                _login(client, user)
                resp = client.get(
                    f'/dashboard/api/inventory/fleet-export.xlsx?agent_id={foreign}'
                )

            assert resp.status_code == 200
            wb = _workbook_from(resp)
            everything = [name for ws in wb.worksheets for name in _apps_in(ws)]
            assert 'Secret App' not in everything
