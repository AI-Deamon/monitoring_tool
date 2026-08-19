"""expand app category breakdown keywords

Revision ID: f1ed8d78511e
Revises: 20260811_add_battery_health
Create Date: 2026-08-18 16:35:33.128601

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1ed8d78511e'
down_revision: Union[str, Sequence[str], None] = '20260811_add_battery_health'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep in sync with the keyword lists in server_dashboard.py::api_category_breakdown().
# Both classify the same four buckets from an app name; letting them drift means the
# Overview page's "App Usage by Category" chart (Python) and its Top Apps panel
# (this view) would disagree on the same app's category.
_NEW_CASE = """
                CASE
                    WHEN LOWER(au.app) SIMILAR TO '%(excel|word|powerpnt|powerpoint|outlook|olk|office|onenote|notepad|notion|obsidian|evernote|todoist|trello|asana|monday|miro|acrobat|visio|planner)%' THEN 'productivity'
                    WHEN LOWER(au.app) SIMILAR TO '%(teams|slack|zoom|meet|skype|discord|telegram|whatsapp|signal|webex|gotomeeting|element|thunderbird|mattermost|ringcentral|viber)%' THEN 'communication'
                    WHEN LOWER(au.app) SIMILAR TO '%(code|visual studio|pycharm|intellij|sublime|terminal|git|devenv|webstorm|goland|phpstorm|rubymine|clion|datagrip|android studio|eclipse|netbeans|postman|insomnia|docker|sourcetree|gitkraken|cursor|antigravity|windsurf|powershell|cmd)%' THEN 'development'
                    WHEN LOWER(au.app) SIMILAR TO '%(chrome|edge|firefox|safari|browser|brave|opera|vivaldi|chromium|arc|iron)%' THEN 'browsing'
                    ELSE 'other'
                END"""

_OLD_CASE = """
                CASE
                    WHEN LOWER(au.app) SIMILAR TO '%(excel|word|powerpoint|outlook|office|notepad|onenote)%' THEN 'productivity'
                    WHEN LOWER(au.app) SIMILAR TO '%(teams|slack|zoom|meet|skype|discord|telegram|whatsapp)%' THEN 'communication'
                    WHEN LOWER(au.app) SIMILAR TO '%(code|visual studio|pycharm|intellij|sublime|terminal|git|devenv)%' THEN 'development'
                    WHEN LOWER(au.app) SIMILAR TO '%(chrome|edge|firefox|safari|browser|brave|opera)%' THEN 'browsing'
                    ELSE 'other'
                END"""


def _rebuild_view(case_sql: str) -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_app_category_breakdown CASCADE;")
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW mv_app_category_breakdown AS
        SELECT
            app_rollup.app,
            app_rollup.category,
            app_rollup.total_duration_seconds,
            app_rollup.total_session_count,
            app_rollup.last_seen_date
        FROM (
            SELECT
                au.app,
                {case_sql} AS category,
                SUM(COALESCE(au.duration_seconds, 0))::BIGINT AS total_duration_seconds,
                SUM(COALESCE(au.session_count, 0))::BIGINT AS total_session_count,
                MAX(au.date) AS last_seen_date
            FROM app_usage au
            GROUP BY au.app, {case_sql}
        ) AS app_rollup;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_app_category_breakdown_category ON mv_app_category_breakdown(category);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_app_category_breakdown_app ON mv_app_category_breakdown(app);"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_view(_NEW_CASE)


def downgrade() -> None:
    """Downgrade schema."""
    _rebuild_view(_OLD_CASE)
