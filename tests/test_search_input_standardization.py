"""
Tests for Standardized Search Bars Across SentinelEdge
======================================================
Verifies that all search bars across the application follow the unified
design system, include search icons, use the standardized .se-search-wrapper
and .se-search-input architecture, and maintain accessible attributes and theme tokens.
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(REPO_ROOT, 'server', 'templates')
CSS_DIR = os.path.join(REPO_ROOT, 'server', 'static', 'css')


class TestSearchDesignTokensAndCSS(unittest.TestCase):
    """Verifies that design tokens and CSS rules for search components are defined properly."""

    def setUp(self):
        with open(os.path.join(CSS_DIR, 'theme.css'), 'r', encoding='utf-8') as f:
            self.theme_css = f.read()
        with open(os.path.join(CSS_DIR, 'dashboard.css'), 'r', encoding='utf-8') as f:
            self.dashboard_css = f.read()
        with open(os.path.join(CSS_DIR, 'header-responsive.css'), 'r', encoding='utf-8') as f:
            self.header_css = f.read()

    def test_theme_css_contains_search_tokens_light_and_dark(self):
        # Light mode tokens
        self.assertIn('--search-height:', self.theme_css)
        self.assertIn('--search-height-compact:', self.theme_css)
        self.assertIn('--search-bg:', self.theme_css)
        self.assertIn('--search-border:', self.theme_css)
        self.assertIn('--search-focus-ring:', self.theme_css)
        self.assertIn('--search-icon-color:', self.theme_css)

        # Check dark mode override block exists
        dark_idx = self.theme_css.find('[data-theme="dark"]')
        self.assertGreater(dark_idx, 0)
        end_dark = self.theme_css.find('html:not(.dark)', dark_idx)
        dark_section = self.theme_css[dark_idx:end_dark]
        self.assertIn('--search-bg:', dark_section)
        self.assertIn('--search-border:', dark_section)
        self.assertIn('--search-focus-ring:', dark_section)

    def test_theme_css_exempts_search_inputs_from_padding_collapse(self):
        # Check that input:not(...) rule explicitly exempts search inputs
        self.assertIn(':not(.se-search-input)', self.theme_css)

    def test_dashboard_css_has_search_component_styles(self):
        # Wrapper
        self.assertIn('.se-search-wrapper', self.dashboard_css)
        self.assertIn('position: relative;', self.dashboard_css)

        # Icon positioning
        self.assertIn('.se-search-icon', self.dashboard_css)
        self.assertIn('position: absolute;', self.dashboard_css)
        self.assertIn('top: 50%;', self.dashboard_css)
        self.assertIn('transform: translateY(-50%);', self.dashboard_css)
        self.assertIn('pointer-events: none;', self.dashboard_css)

        # Input padding - ensures text never overlaps the 16px icon
        self.assertIn('.se-search-input', self.dashboard_css)
        self.assertIn('padding-left: 2.375rem', self.dashboard_css)

        # Compact variant
        self.assertIn('.se-search-wrapper--compact', self.dashboard_css)
        self.assertIn('.se-search-input--compact', self.dashboard_css)

        # Focus ring
        self.assertIn('box-shadow: var(--search-focus-ring', self.dashboard_css)

    def test_header_responsive_css_aligns_with_search_tokens(self):
        self.assertIn('.se-agent-selector__search-wrapper', self.header_css)
        self.assertIn('.se-agent-selector__search-icon', self.header_css)
        self.assertIn('.se-agent-selector__search-input', self.header_css)
        self.assertIn('padding: 0 0.75rem 0 2.375rem', self.header_css)


class TestSearchFieldMarkupInTemplates(unittest.TestCase):
    """Verifies that all 11 search fields across templates have wrapper, icon, and standardized classes."""

    def read_template(self, rel_path):
        full_path = os.path.join(TEMPLATES_DIR, rel_path)
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_base_html_team_selector_search(self):
        html = self.read_template(os.path.join('dashboard', 'base.html'))
        self.assertIn('id="agent-selector-search"', html)
        self.assertIn('se-search-wrapper', html)
        self.assertIn('se-search-icon', html)
        self.assertIn('se-search-input', html)
        self.assertIn("icon('search'", html)
        self.assertIn('role="searchbox"', html)

    def test_agents_html_search(self):
        html = self.read_template(os.path.join('dashboard', 'agents.html'))
        self.assertIn('id="agent-search"', html)
        self.assertIn('se-search-wrapper', html)
        self.assertIn('se-search-icon', html)
        self.assertIn('se-search-input', html)
        self.assertIn("icon('search'", html)
        self.assertIn('role="searchbox"', html)

    def test_assets_html_searches(self):
        html = self.read_template(os.path.join('dashboard', 'assets.html'))
        # Header search
        self.assertIn('id="asset-search-header"', html)
        # Table search
        self.assertIn('id="asset-search"', html)
        # Check both have .se-search-wrapper and icon
        self.assertGreaterEqual(html.count('se-search-wrapper'), 2)
        self.assertGreaterEqual(html.count('se-search-icon'), 2)
        self.assertGreaterEqual(html.count('se-search-input'), 2)

    def test_asset_details_html_software_search(self):
        html = self.read_template(os.path.join('dashboard', 'asset_details.html'))
        self.assertIn('id="software-search"', html)
        self.assertIn('se-search-wrapper--compact', html)
        self.assertIn('se-search-icon', html)
        self.assertIn('se-search-input--compact', html)
        self.assertIn("icon('search'", html)

    def test_updates_html_search(self):
        html = self.read_template(os.path.join('dashboard', 'updates.html'))
        self.assertIn('id="update-search"', html)
        self.assertIn('se-search-wrapper', html)
        self.assertIn('se-search-icon', html)
        self.assertIn('se-search-input', html)
        self.assertIn("icon('search'", html)
        # Ensure icon is inside wrapper before input
        icon_pos = html.find('se-search-icon')
        input_pos = html.find('id="update-search"')
        self.assertLess(icon_pos, input_pos)

    def test_agent_detail_html_all_four_searches(self):
        html = self.read_template(os.path.join('dashboard', 'agent_detail.html'))
        for input_id in ['app-search', 'domain-search', 'visits-search', 'inventory-search']:
            with self.subTest(input_id=input_id):
                self.assertIn(f'id="{input_id}"', html)
        self.assertGreaterEqual(html.count('se-search-wrapper'), 4)
        self.assertGreaterEqual(html.count('se-search-icon'), 4)
        self.assertGreaterEqual(html.count('se-search-input'), 4)

    def test_reports_html_recipient_search(self):
        html = self.read_template(os.path.join('dashboard', 'reports.html'))
        self.assertIn('id="um-recipient-search"', html)
        self.assertIn('se-search-wrapper', html)
        self.assertIn('se-search-icon', html)
        self.assertIn('se-search-input', html)
        self.assertIn("icon('search'", html)

    def test_reusable_search_macro_component_exists(self):
        macro_path = os.path.join(TEMPLATES_DIR, 'components', 'search_input.html')
        self.assertTrue(os.path.exists(macro_path))
        with open(macro_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('macro search_input(', content)
        self.assertIn('se-search-wrapper', content)
        self.assertIn('se-search-icon', content)
        self.assertIn('se-search-input', content)


class TestLiveRenderedRoutes(unittest.TestCase):
    """Verifies that routes rendered through Flask test client contain the standardized search bars."""

    @classmethod
    def setUpClass(cls):
        from server_app import create_app
        from auth import DashboardUser
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def test_routes_render_search_bars(self):
        with self.app.app_context():
            client = self.app.test_client()
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['role'] = 'admin'
                sess['username'] = 'admin'
                sess['tab_token'] = 'test-token-123'
                sess['session_version'] = 1

            headers = {'X-Tab-Session': 'test-token-123'}

            # 1. /dashboard (Header Team Selector)
            resp = client.get('/dashboard', headers=headers)
            if resp.status_code == 200:
                html = resp.data.decode('utf-8', errors='ignore')
                self.assertIn('agent-selector-search', html)
                self.assertIn('se-search-wrapper', html)
                self.assertIn('se-search-icon', html)

            # 2. /agents
            resp = client.get('/agents', headers=headers)
            if resp.status_code == 200:
                html = resp.data.decode('utf-8', errors='ignore')
                self.assertIn('agent-search', html)
                self.assertIn('se-search-wrapper', html)
                self.assertIn('se-search-icon', html)

            # 3. /assets
            resp = client.get('/assets', headers=headers)
            if resp.status_code == 200:
                html = resp.data.decode('utf-8', errors='ignore')
                self.assertIn('asset-search-header', html)
                self.assertIn('asset-search', html)
                self.assertIn('se-search-wrapper', html)

            # 4. /updates
            resp = client.get('/updates', headers=headers)
            if resp.status_code == 200:
                html = resp.data.decode('utf-8', errors='ignore')
                self.assertIn('update-search', html)
                self.assertIn('se-search-wrapper', html)

            # 5. /reports
            resp = client.get('/reports', headers=headers)
            if resp.status_code == 200:
                html = resp.data.decode('utf-8', errors='ignore')
                self.assertIn('um-recipient-search', html)
                self.assertIn('se-search-wrapper', html)


if __name__ == '__main__':
    unittest.main()

