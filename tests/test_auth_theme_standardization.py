"""
Tests for Phase 2: Complete Light and Dark Theme Support across SentinelEdge Auth and User-Management Pages.
Covers:
- /auth/users (users.html)
- /auth/users/add (add_user.html)
- /auth/users/<id>/edit (edit_user.html)
- /auth/change-password (change_password.html)
- /auth/forgot-password (forgot_password.html)
- /auth/reset-password/<token> (reset_password.html)
"""
import re
from pathlib import Path
import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "server" / "templates" / "auth"
STATIC_DIR = Path(__file__).resolve().parent.parent / "server" / "static"

AUTH_TEMPLATES = [
    "users.html",
    "add_user.html",
    "edit_user.html",
    "change_password.html",
    "forgot_password.html",
    "reset_password.html",
]


class TestAuthThemeTemplatesIntegrity:
    """Verifies that all auth templates have anti-FOUC script, theme-manager.js, and theme.css."""

    @pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
    def test_anti_fouc_script_present(self, template_name):
        path = TEMPLATES_DIR / template_name
        assert path.exists(), f"{template_name} does not exist"
        content = path.read_text(encoding="utf-8")
        assert "sentinel-theme" in content, f"{template_name} is missing sentinel-theme anti-FOUC check"
        assert "prefers-color-scheme" in content, f"{template_name} is missing system dark mode check in anti-FOUC script"
        assert "data-theme" in content, f"{template_name} is missing data-theme in anti-FOUC script"

    @pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
    def test_theme_manager_script_included(self, template_name):
        path = TEMPLATES_DIR / template_name
        content = path.read_text(encoding="utf-8")
        assert "theme-manager.js" in content, f"{template_name} does not load theme-manager.js"

    @pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
    def test_theme_css_linked(self, template_name):
        path = TEMPLATES_DIR / template_name
        content = path.read_text(encoding="utf-8")
        assert "css/theme.css" in content, f"{template_name} does not link theme.css"

    @pytest.mark.parametrize("template_name", [
        "add_user.html",
        "edit_user.html",
        "change_password.html",
        "forgot_password.html",
        "reset_password.html",
    ])
    def test_semantic_auth_classes_present(self, template_name):
        path = TEMPLATES_DIR / template_name
        content = path.read_text(encoding="utf-8")
        assert "se-auth-body" in content, f"{template_name} is missing se-auth-body"
        assert "se-auth-card" in content, f"{template_name} is missing se-auth-card"
        assert "se-auth-input" in content or "se-auth-select" in content, f"{template_name} is missing theme-aware inputs"


class TestThemeCssDesignTokens:
    """Verifies that theme.css defines complete tokens and dark mode overrides for auth elements."""

    @pytest.fixture(autouse=True)
    def setup_css(self):
        css_path = STATIC_DIR / "css" / "theme.css"
        assert css_path.exists()
        self.css_content = css_path.read_text(encoding="utf-8")

    def test_input_background_tokens_present(self):
        assert "--bg-input: #ffffff;" in self.css_content
        assert "--bg-input: #0f172a;" in self.css_content

    def test_auth_classes_in_theme_css(self):
        for cls in [
            ".se-auth-body",
            ".se-auth-card",
            ".se-auth-card-title",
            ".se-auth-card-subtitle",
            ".se-auth-label",
            ".se-auth-input",
            ".se-auth-select",
            ".se-auth-helper",
            ".se-auth-infobox",
            ".se-auth-eye-btn",
            ".se-auth-divider",
            ".se-alert-danger",
            ".se-alert-success",
            ".se-alert-warning",
            ".se-alert-info",
        ]:
            assert cls in self.css_content, f"theme.css missing {cls}"

    def test_dark_mode_selectors_present(self):
        assert "html.dark body.se-auth-body" in self.css_content
        assert "html.dark .se-auth-card" in self.css_content
        assert "html.dark .se-auth-input" in self.css_content
        assert "color-scheme: dark" in self.css_content
