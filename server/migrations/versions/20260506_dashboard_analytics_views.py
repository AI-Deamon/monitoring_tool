"""Add dashboard analytics materialized views

Revision ID: 20260506_dash_mv_views
Revises: 20260506_missing_cols
Create Date: 2026-05-06
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260506_dash_mv_views"
down_revision = "20260506_missing_cols"
branch_labels = None
depends_on = None


def upgrade():
    """Create materialized views used by analytics dashboard widgets."""

    # Recreate views in deterministic order
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_after_hours_activity CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_high_switch_users CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_domain_classified CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_app_category_breakdown CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_fleet_productivity CASCADE;")

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_fleet_productivity AS
        SELECT
            st.date,
            st.agent_id,
            st.username,
            COALESCE(a.hostname, st.username, st.agent_id::text) AS hostname,
            COALESCE(st.active_seconds, 0) AS active_seconds,
            COALESCE(st.idle_seconds, 0) AS idle_seconds,
            COALESCE(st.locked_seconds, 0) AS locked_seconds,
            COALESCE(st.away_seconds, 0) AS away_seconds,
            (
                COALESCE(st.active_seconds, 0)
                + COALESCE(st.idle_seconds, 0)
                + COALESCE(st.locked_seconds, 0)
                + COALESCE(st.away_seconds, 0)
            ) AS total_seconds,
            CASE
                WHEN (
                    COALESCE(st.active_seconds, 0)
                    + COALESCE(st.idle_seconds, 0)
                    + COALESCE(st.locked_seconds, 0)
                    + COALESCE(st.away_seconds, 0)
                ) > 0
                THEN ROUND(
                    (
                        (COALESCE(st.active_seconds, 0) * 100.0)
                        / (
                            COALESCE(st.active_seconds, 0)
                            + COALESCE(st.idle_seconds, 0)
                            + COALESCE(st.locked_seconds, 0)
                            + COALESCE(st.away_seconds, 0)
                        )
                    )::numeric,
                    2
                )
                ELSE 0
            END AS productivity_score,
            CASE
                WHEN (
                    COALESCE(st.active_seconds, 0)
                    + COALESCE(st.idle_seconds, 0)
                    + COALESCE(st.locked_seconds, 0)
                    + COALESCE(st.away_seconds, 0)
                ) > 0
                THEN ROUND(
                    (
                        (COALESCE(st.idle_seconds, 0) * 100.0)
                        / (
                            COALESCE(st.active_seconds, 0)
                            + COALESCE(st.idle_seconds, 0)
                            + COALESCE(st.locked_seconds, 0)
                            + COALESCE(st.away_seconds, 0)
                        )
                    )::numeric,
                    2
                )
                ELSE 0
            END AS idle_ratio,
            CASE
                WHEN (
                    COALESCE(st.active_seconds, 0)
                    + COALESCE(st.idle_seconds, 0)
                    + COALESCE(st.locked_seconds, 0)
                    + COALESCE(st.away_seconds, 0)
                ) > 0
                THEN ROUND(
                    (
                        (COALESCE(st.locked_seconds, 0) * 100.0)
                        / (
                            COALESCE(st.active_seconds, 0)
                            + COALESCE(st.idle_seconds, 0)
                            + COALESCE(st.locked_seconds, 0)
                            + COALESCE(st.away_seconds, 0)
                        )
                    )::numeric,
                    2
                )
                ELSE 0
            END AS locked_ratio
        FROM screen_time st
        LEFT JOIN agents a ON a.agent_id = st.agent_id;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_fleet_productivity_date ON mv_fleet_productivity(date);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_fleet_productivity_agent_date ON mv_fleet_productivity(agent_id, date);"
    )

    op.execute(
        """
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
                CASE
                    WHEN LOWER(au.app) SIMILAR TO '%(excel|word|powerpoint|outlook|office|notepad|onenote)%' THEN 'productivity'
                    WHEN LOWER(au.app) SIMILAR TO '%(teams|slack|zoom|meet|skype|discord|telegram|whatsapp)%' THEN 'communication'
                    WHEN LOWER(au.app) SIMILAR TO '%(code|visual studio|pycharm|intellij|sublime|terminal|git|devenv)%' THEN 'development'
                    WHEN LOWER(au.app) SIMILAR TO '%(chrome|edge|firefox|safari|browser|brave|opera)%' THEN 'browsing'
                    ELSE 'other'
                END AS category,
                SUM(COALESCE(au.duration_seconds, 0))::BIGINT AS total_duration_seconds,
                SUM(COALESCE(au.session_count, 0))::BIGINT AS total_session_count,
                MAX(au.date) AS last_seen_date
            FROM app_usage au
            GROUP BY au.app,
                CASE
                    WHEN LOWER(au.app) SIMILAR TO '%(excel|word|powerpoint|outlook|office|notepad|onenote)%' THEN 'productivity'
                    WHEN LOWER(au.app) SIMILAR TO '%(teams|slack|zoom|meet|skype|discord|telegram|whatsapp)%' THEN 'communication'
                    WHEN LOWER(au.app) SIMILAR TO '%(code|visual studio|pycharm|intellij|sublime|terminal|git|devenv)%' THEN 'development'
                    WHEN LOWER(au.app) SIMILAR TO '%(chrome|edge|firefox|safari|browser|brave|opera)%' THEN 'browsing'
                    ELSE 'other'
                END
        ) AS app_rollup;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_app_category_breakdown_category ON mv_app_category_breakdown(category);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_app_category_breakdown_app ON mv_app_category_breakdown(app);"
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_domain_classified AS
        SELECT
            du.date,
            du.agent_id,
            du.username,
            COALESCE(a.hostname, du.username, du.agent_id::text) AS hostname,
            du.domain,
            du.browser,
            COALESCE(du.duration_seconds, 0) AS duration_seconds,
            COALESCE(du.session_count, 0) AS session_count,
            COALESCE(rule.classified_as, du.domain) AS effective_category,
            COALESCE(
                rule.action,
                CASE WHEN COALESCE(review_flags.needs_review, FALSE) THEN 'needs_review' ELSE 'unclassified' END
            ) AS risk_action,
            (
                COALESCE(review_flags.needs_review, FALSE)
                OR COALESCE(rule.action, '') = 'needs_review'
            ) AS needs_review
        FROM domain_usage du
        LEFT JOIN agents a ON a.agent_id = du.agent_id
        LEFT JOIN LATERAL (
            SELECT
                r.classified_as,
                r.action
            FROM domain_classification_rules r
            WHERE r.is_active = TRUE
              AND (
                    (r.pattern_type = 'exact' AND LOWER(du.domain) = LOWER(r.pattern))
                 OR (r.pattern_type = 'startswith' AND LOWER(du.domain) LIKE LOWER(r.pattern) || '%')
                 OR (r.pattern_type = 'endswith' AND LOWER(du.domain) LIKE '%' || LOWER(r.pattern))
                 OR ((r.pattern_type IS NULL OR r.pattern_type = 'substring') AND LOWER(du.domain) LIKE '%' || LOWER(r.pattern) || '%')
              )
            ORDER BY r.priority ASC, r.id ASC
            LIMIT 1
        ) AS rule ON TRUE
        LEFT JOIN (
            SELECT
                LOWER(ds.domain) AS domain_key,
                ds.start_time::DATE AS activity_date,
                BOOL_OR(COALESCE(ds.needs_review, FALSE)) AS needs_review
            FROM domain_sessions ds
            GROUP BY LOWER(ds.domain), ds.start_time::DATE
        ) AS review_flags
            ON review_flags.domain_key = LOWER(du.domain)
           AND review_flags.activity_date = du.date;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_domain_classified_date ON mv_domain_classified(date);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_domain_classified_domain ON mv_domain_classified(domain);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_domain_classified_review ON mv_domain_classified(needs_review);"
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_high_switch_users AS
        SELECT
            au.date,
            au.agent_id,
            au.username,
            COALESCE(a.hostname, au.username, au.agent_id::text) AS hostname,
            SUM(COALESCE(au.session_count, 0))::BIGINT AS session_count,
            SUM(COALESCE(au.duration_seconds, 0))::BIGINT AS total_duration_seconds,
            CASE
                WHEN SUM(COALESCE(au.session_count, 0)) > 0
                THEN ROUND(
                    SUM(COALESCE(au.duration_seconds, 0))::NUMERIC
                    / NULLIF(SUM(COALESCE(au.session_count, 0)), 0),
                    2
                )
                ELSE 0
            END AS avg_session_duration_seconds,
            CASE
                WHEN SUM(COALESCE(au.session_count, 0)) >= 300 OR (
                    SUM(COALESCE(au.duration_seconds, 0))::NUMERIC
                    / NULLIF(SUM(COALESCE(au.session_count, 0)), 0)
                ) < 90 THEN 'high'
                WHEN SUM(COALESCE(au.session_count, 0)) >= 180 OR (
                    SUM(COALESCE(au.duration_seconds, 0))::NUMERIC
                    / NULLIF(SUM(COALESCE(au.session_count, 0)), 0)
                ) < 180 THEN 'medium'
                ELSE 'low'
            END AS risk_band
        FROM app_usage au
        LEFT JOIN agents a ON a.agent_id = au.agent_id
        GROUP BY au.date, au.agent_id, au.username, a.hostname;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_high_switch_users_date ON mv_high_switch_users(date);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_high_switch_users_risk ON mv_high_switch_users(risk_band);"
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_after_hours_activity AS
        SELECT
            app_s.start_time::DATE AS activity_date,
            app_s.agent_id,
            app_s.username,
            COALESCE(a.hostname, app_s.username, app_s.agent_id::text) AS hostname,
            EXTRACT(HOUR FROM app_s.start_time)::INT AS activity_hour,
            SUM(COALESCE(app_s.duration_seconds, 0))::BIGINT AS duration_seconds,
            COUNT(*)::BIGINT AS session_count,
            (
                EXTRACT(HOUR FROM app_s.start_time) < 8
                OR EXTRACT(HOUR FROM app_s.start_time) >= 19
            ) AS is_after_hours
        FROM app_sessions app_s
        LEFT JOIN agents a ON a.agent_id = app_s.agent_id
        GROUP BY
            app_s.start_time::DATE,
            app_s.agent_id,
            app_s.username,
            a.hostname,
            EXTRACT(HOUR FROM app_s.start_time);
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_after_hours_activity_date ON mv_after_hours_activity(activity_date);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_after_hours_activity_after_hours ON mv_after_hours_activity(is_after_hours);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_after_hours_activity_agent_date ON mv_after_hours_activity(agent_id, activity_date);"
    )


def downgrade():
    """Drop dashboard analytics materialized views."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_after_hours_activity CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_high_switch_users CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_domain_classified CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_app_category_breakdown CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_fleet_productivity CASCADE;")
