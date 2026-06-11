# Graph Report - D:\monitoring_tool-main\monitoring_tool  (2026-05-12)

## Corpus Check
- 225 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3282 nodes · 5848 edges · 172 communities detected
- Extraction: 54% EXTRACTED · 46% INFERRED · 0% AMBIGUOUS · INFERRED: 2669 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `BufferDB` - 233 edges
2. `CoreConfig` - 157 edges
3. `HelperConfig` - 81 edges
4. `AgentUpdater` - 68 edges
5. `ServerUploader` - 65 edges
6. `StateDetector` - 61 edges
7. `DataCollector` - 58 edges
8. `LiveTelemetryTracker` - 49 edges
9. `_get_connection()` - 48 edges
10. `CoreCommunicator` - 48 edges

## Surprising Connections (you probably didn't know these)
- `Aggregates heartbeats into merged events - Config-driven` --uses--> `BufferDB`  [INFERRED]
  D:\monitoring_tool-main\monitoring_tool\agent\core\aggregator.py → D:\monitoring_tool-main\monitoring_tool\agent\core\buffer.py
- `Apply configuration changes dynamically` --uses--> `BufferDB`  [INFERRED]
  D:\monitoring_tool-main\monitoring_tool\agent\core\aggregator.py → D:\monitoring_tool-main\monitoring_tool\agent\core\buffer.py
- `Get a writable data directory with intelligent fallback.         Tries ProgramD` --uses--> `ConfigValidator`  [INFERRED]
  D:\monitoring_tool-main\monitoring_tool\agent\core\config.py → D:\monitoring_tool-main\monitoring_tool\agent\core\config_schema.py
- `Get default config path - tries stealth name first, then legacy` --uses--> `ConfigValidator`  [INFERRED]
  D:\monitoring_tool-main\monitoring_tool\agent\core\config.py → D:\monitoring_tool-main\monitoring_tool\agent\core\config_schema.py
- `Load, validate, and apply configuration` --uses--> `ConfigValidator`  [INFERRED]
  D:\monitoring_tool-main\monitoring_tool\agent\core\config.py → D:\monitoring_tool-main\monitoring_tool\agent\core\config_schema.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (227): Data Collector Module - ENHANCED ================================ Orchestrates, Apply configuration changes to sub-modules, Standardized FIX 3: Force locked state reporting, Collect data for a heartbeat packet with enhanced screen time tracking., # NOTE: Do NOT reset state machine counters here., Validate duration is a sane number (0-24 hours)., Collect completed state spans from StateDetector.          Returns:, Notify core of a completed idle session.         Accepts clean durations calcul (+219 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (171): HeartbeatAggregator, Aggregates heartbeats into merged events - Config-driven, Apply configuration changes dynamically, CoreConfig, Check if directory is writable (create test file), Get default config path - tries stealth name first, then legacy, Load, validate, and apply configuration, Apply validated config to class attributes (+163 more)

### Community 2 - "Community 2"
Cohesion: 0.01
Nodes (193): Add domain classification system: - Classification rules table - Review queue, Add raw_title, raw_url, domain_source columns to domain_sessions table. Run: py, backfill_existing_data(), downgrade(), Add enhanced OS detection fields to agents table. Date: December 16, 2025  Ad, Remove the new columns if needed (rollback)., Add new OS detection columns to agents table., Attempt to populate new fields from existing data.     This is optional but hel (+185 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (128): DataCollector, CoreCommunicator, Communication Module Enhanced with strict HMAC verification, replay protection,, Flush pending items from queue to core, Queue and send heartbeat to core                  Args:             heartbeat, Queue and send domain visits to core                  Args:             domai, Simple replay protection for outgoing requests, Queue and send domain usage sessions to core                  Args: (+120 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (97): Aggregator Module Merges heartbeats into sessionized events, PHASE 3: Router only - reads cumulative totals from state machine.          Proc, Merge app foreground sessions into events, Process unprocessed heartbeats and create merged events with sequence validation, BaseHTTPRequestHandler, BufferDB, _get_connection(), _get_ist_now() (+89 more)

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (154): BaseModel, AppActiveSchema, AppInventoryItemSchema, AppInventorySchema, AppSwitchSchema, Config, DomainActiveSchema, DomainSwitchSchema (+146 more)

### Community 6 - "Community 6"
Cohesion: 0.02
Nodes (128): agent_detail(), agent_report(), agent_report_v2(), agents_detail(), agents_list(), api_activity_heatmap(), api_agent_activity_timeline(), api_agent_app_sessions() (+120 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (67): AdaptiveSleep, add_cache_headers(), add_timing_header(), batch_query(), BatchAccumulator, cached(), compress_response(), CPUThrottler (+59 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (65): ApplicationPlugin, AssetInfo, AssetLifecycleStatus, BrowserExtension, CLITool, HardwareDriver, NVDCacheEntry, PortableApplication (+57 more)

### Community 9 - "Community 9"
Cohesion: 0.04
Nodes (76): add_user(), admin_required(), api_me(), can_view_agent(), change_password(), check_linked_username_unique(), conditional_limit(), create_default_admin() (+68 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (50): report_constants.py — Shared classification maps and formatting helpers for repo, _agg_screen_time(), build_individual_report(), build_team_report(), build_unified_report(), fail_job(), generate_pdf(), _get_active_agents() (+42 more)

### Community 11 - "Community 11"
Cohesion: 0.04
Nodes (44): backup_database(), Backup database to SQL file, AgentLogger, get_logger(), PerformanceLogger, Enhanced logging configuration for SentinelEdge Server. Provides structured log, Middleware-like logger for HTTP requests., Logger for performance metrics and bottlenecks. (+36 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (32): Helper Configuration Module - Config-Driven v2 Uses unified config schema with, # NOTE: capture_window_titles MUST be True for domain tracking to work, Check if config file has changed and reload if needed.         Returns True if, Register a callback to be notified of config changes, Notify all registered callbacks of config change, DISABLED: Helper should NEVER write to system config.json                  The, Get HMAC key as bytes, Register a callback to be notified of config changes (+24 more)

### Community 13 - "Community 13"
Cohesion: 0.06
Nodes (32): get_date_range(), main(), Parse date range from config., format_duration(), format_hours(), get_category(), get_domain_category(), get_friendly_name() (+24 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (47): check_compatibility(), clear_failure(), download_update(), _get_agent_from_db(), get_available_versions(), _get_global_policy(), get_latest_version(), _get_signing_key() (+39 more)

### Community 15 - "Community 15"
Cohesion: 0.06
Nodes (31): format_duration(), format_hours(), format_month_name(), get_category(), get_domain_category(), get_friendly_name(), get_last_month_dates(), main() (+23 more)

### Community 16 - "Community 16"
Cohesion: 0.06
Nodes (35): audit_data_integrity(), BackgroundScheduler, check_stale_updates(), cleanup_old_data(), _get_schedule_date_range(), Background Tasks - Daily Sync ============================== Runs sync functio, Sync yesterday's data to ensure aggregations are correct, Reprocess failed RawEvents that were stored but not processed.      This handl (+27 more)

### Community 17 - "Community 17"
Cohesion: 0.05
Nodes (30): calculate_file_hash(), ConfigIntegrity, generate_manifest(), get_signer(), init_integrity(), IntegrityWatchdog, load_manifest(), Integrity Verification Module - SEC-024 ENHANCED ============================== (+22 more)

### Community 18 - "Community 18"
Cohesion: 0.06
Nodes (26): ESUInfo, _normalize_for_cpe(), _normalize_for_purl(), ProductKeyInfo, EOL Data Collector Module ========================= Collects End-of-Life speci, Run PowerShell command and return output, Collect all EOL-specific data. Each sub-collector runs independently., Collect installed Windows updates and pending updates.         Uses both Get-Ho (+18 more)

### Community 19 - "Community 19"
Cohesion: 0.07
Nodes (24): CryptoStorage, DATA_BLOB, dpapi_decrypt(), dpapi_encrypt(), DPAPIStorage, get_secure_storage(), Secure Storage Module - Hybrid DPAPI + Cryptography Implementation SEC-004 COMP, Decrypt using Windows DPAPI (+16 more)

### Community 20 - "Community 20"
Cohesion: 0.08
Nodes (19): ConfigProtector, get_config_protector(), get_tamper_detector(), SentinelEdge Security Module - Anti-Tampering Detection =======================, Analyze mouse movement patterns for synthetic input indicators., Detect if system clock has been manipulated to hide time.                  Ind, Verify agent processes are running and haven't been tampered with., Detects attempts to tamper with or bypass the monitoring agent.          Detec (+11 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (20): copyAgentId(), escapeHtml(), fallbackCopy(), fetchJSON(), formatTime(), getSelectedDate(), getSourceBadge(), loadExtendedInventory() (+12 more)

### Community 22 - "Community 22"
Cohesion: 0.13
Nodes (27): _backup_files(), _cleanup_path(), _ensure_logger_file(), _find_required_file(), _get_service_state(), main(), _parse_created_at(), SentinelEdge EXE Swapper ======================== External detached process th (+19 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (27): evaluate_agent_lifecycle(), evaluate_cli_tools_lifecycle(), _evaluate_cycle(), evaluate_extended_inventory_lifecycle(), evaluate_fleet_lifecycle(), get_fleet_lifecycle_summary(), _match_app_lifecycle(), _match_windows_lifecycle() (+19 more)

### Community 24 - "Community 24"
Cohesion: 0.11
Nodes (15): _cpe_sanitize(), CPEResolver, FuzzyMatcher, generate_cpe(), NormalizationEngine, Normalization Engine ==================== Canonical naming and fuzzy matching, Transforms raw software names and publishers into canonical forms.     Used bef, Normalize an application name to its canonical form.          Examples: (+7 more)

### Community 25 - "Community 25"
Cohesion: 0.11
Nodes (21): get_server_tz(), parse_agent_time(), parse_agent_timestamp(), pick_earliest_timestamp(), Telemetry Helpers: Timezone handling, parsing, validation, and logging utilities, Safely convert value to integer with validation., Safely convert value to float with validation., Comprehensive server-side validation for screen time spans.     Returns error m (+13 more)

### Community 26 - "Community 26"
Cohesion: 0.16
Nodes (19): apply_stored_procedures(), check_prerequisites(), create_database(), create_default_admin(), install_dependencies(), print_step(), Apply critical stored procedures, Create default admin user (+11 more)

### Community 27 - "Community 27"
Cohesion: 0.12
Nodes (12): DomainClassifier, get_classifier(), Domain Session Classifier Classifies domain sessions using rules + manual tags, Get classification rules (cached), Classify domain sessions using admin-defined rules, Update match stats for a rule, Extract domain from URL, Check if domain is localhost (+4 more)

### Community 28 - "Community 28"
Cohesion: 0.15
Nodes (14): _explain_eol_proximity(), _generate_recommendations(), Risk Scoring Rubric =================== Composite 1-20 risk scoring system for, Calculate a composite risk score.          Args:             eol_date: End of, Individual risk factor scores (each 0.0-1.0), Complete risk assessment result, Computes composite risk scores for software lifecycle assessments.      Usage:, RiskAssessment (+6 more)

### Community 29 - "Community 29"
Cohesion: 0.1
Nodes (19): child_exit(), on_reload(), on_starting(), post_fork(), pre_exec(), pre_fork(), Gunicorn configuration for SentinelEdge Server Usage: gunicorn -c gunicorn_conf, Called just before a worker is forked. (+11 more)

### Community 30 - "Community 30"
Cohesion: 0.12
Nodes (19): AnomalyThresholds, api_all_agents_integrity(), api_integrity_report(), api_integrity_status(), get_agent_integrity_status(), get_all_agents_integrity(), Server-Side Anomaly Detection Service - SEC-025 ===============================, Get integrity status for all agents (+11 more)

### Community 31 - "Community 31"
Cohesion: 0.2
Nodes (7): DailyReportGenerator, format_duration(), format_hours(), get_category(), get_domain_category(), get_friendly_name(), main()

### Community 32 - "Community 32"
Cohesion: 0.12
Nodes (13): cleanup_rate_limiters(), rate_limit(), rate_limit_by_agent(), RateLimiter, Rate limiting for API endpoints to prevent abuse and ensure fair resource usage., Rate limiting decorator for Flask routes.          Args:         limiter: Rat, Simple in-memory rate limiter for API endpoints., Rate limiting decorator that uses agent_id as the key.          Usage: (+5 more)

### Community 33 - "Community 33"
Cohesion: 0.18
Nodes (15): build_exe(), clean_build(), get_hidden_imports(), get_swapper_imports(), main(), Common hidden imports needed by the agent.          AUDIT (2026-03-11): Verifi, Minimal hidden imports for swapper build., Run PyInstaller for a specific entry point (+7 more)

### Community 34 - "Community 34"
Cohesion: 0.12
Nodes (15): classification_admin_page(), classify_sessions(), create_classification_rule(), delete_classification_rule(), get_classification_rules(), get_review_queue(), Admin endpoints for domain classification management, Update classification rule (+7 more)

### Community 35 - "Community 35"
Cohesion: 0.19
Nodes (13): authenticate_ldap(), _build_user_dn(), _extract_username_from_linked(), get_ad_config(), is_ad_enabled(), AD Authentication Module - LDAP Direct User Bind  Supports authentication agains, Test AD connection with current configuration.      Returns:         Tuple of (s, Check if AD authentication is enabled. (+5 more)

### Community 36 - "Community 36"
Cohesion: 0.22
Nodes (10): initActivityHeatmap(), initCategoryBreakdown(), initIdleTimeAnalysis(), initProductivityGauge(), interpolateHeatmapColor(), lerpColor(), loadActivityHeatmap(), loadCategoryBreakdown() (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.2
Nodes (4): fetchJSON(), getRelativeTime(), relativeTime(), showToast()

### Community 38 - "Community 38"
Cohesion: 0.2
Nodes (6): Enhanced human-readable formatter with IST support and redaction., Convert timestamp to IST., Simple redaction for strings., Sets up and returns a human-readable logger writing to a rotating file., ReadableFormatter, setup_logger()

### Community 39 - "Community 39"
Cohesion: 0.25
Nodes (10): check_package(), main(), Check if a package is installed, install if missing, Run the auto-setup script, Start the server using Waitress (Windows), Start the server using Gunicorn (Linux), Main production startup workflow, run_setup() (+2 more)

### Community 40 - "Community 40"
Cohesion: 0.2
Nodes (2): formatDateTimeIST(), getRelativeTimeIST()

### Community 41 - "Community 41"
Cohesion: 0.22
Nodes (9): _create_span(), get_pending_spans(), _load_persisted_state(), _persist_current_state(), StateDetector Span Generation Methods Add these methods to the StateDetector cl, Save current session for crash recovery., Create an immutable span record with clock drift detection.          Args:, Return and clear pending spans (called by Collector). (+1 more)

### Community 42 - "Community 42"
Cohesion: 0.31
Nodes (8): compute_sha256(), create_package(), main(), SentinelEdge Update Package Creator ===================================== Admi, Compute SHA256 hash of a file., Create HMAC-SHA256 signature of version metadata., Create a signed update package.          Args:         exe_mode: If True, pac, sign_metadata()

### Community 43 - "Community 43"
Cohesion: 0.33
Nodes (8): find_report_files(), get_last_week_dates(), is_report_fresh(), main(), Attach available files and send via SMTP., Look for the HTML and PDF for the given week inside reports/.     Returns (html_, Check the report was generated after the week ended (i.e. not a stale     leftov, send_email()

### Community 44 - "Community 44"
Cohesion: 0.25
Nodes (7): get_app_category(), get_friendly_name(), is_browser(), App Name Mapper - Maps executable names to friendly display names, Get friendly name for an executable.          Args:         exe_name: The exe, Get category for an app (for grouping in dashboard).          Returns: 'browse, Check if app is a browser (for domain tracking).

### Community 45 - "Community 45"
Cohesion: 0.57
Nodes (6): _auth_headers(), main(), Basic E2E smoke test for auto-update endpoints.  Checks: 1) Agent can call /l, test_check_for_update(), test_download_package(), test_report_health()

### Community 46 - "Community 46"
Cohesion: 0.43
Nodes (6): cleanup_old_reports(), generate_report(), get_last_week_dates(), main(), Delete report folders older than keep_weeks weeks., Invoke generate_weekly_reports.py as a subprocess and stream its output to the l

### Community 47 - "Community 47"
Cohesion: 0.4
Nodes (5): Database Migration: Add operational status columns to agents table This migrati, Add operational status columns to agents table, Run migration independently (not from Flask app), run_standalone(), upgrade()

### Community 48 - "Community 48"
Cohesion: 0.47
Nodes (5): get_connection(), migrate(), Migration: Create asset_info table for IT asset hardware tracking.  Creates th, Drop asset_info table (for rollback)., rollback()

### Community 49 - "Community 49"
Cohesion: 0.47
Nodes (5): get_connection(), migrate(), Migration: Add Dashboard-Driven Update Control columns to agents table.  Adds:, Remove update control columns (for rollback)., rollback()

### Community 50 - "Community 50"
Cohesion: 0.4
Nodes (5): parse_db_url(), Performance Optimization Migration - PERF-001 =================================, Parse database URL into connection parameters, Run all performance optimizations, run_migration()

### Community 51 - "Community 51"
Cohesion: 0.33
Nodes (5): downgrade(), Add api_key and status columns to agents table  Revision ID: 003_add_api_key_a, Add api_key and status columns to agents table for new authentication., Remove api_key and status columns from agents table., upgrade()

### Community 52 - "Community 52"
Cohesion: 0.33
Nodes (5): downgrade(), create core aggregation tables  Revision ID: 003a_create_core_tables Revises:, Drop all core aggregation tables., Create all core aggregation tables., upgrade()

### Community 53 - "Community 53"
Cohesion: 0.33
Nodes (5): downgrade(), Add username to screen_time  Revision ID: 004_add_username_to_screentime Revi, Add username column to screen_time table if it doesn't exist., Remove username column from screen_time table., upgrade()

### Community 54 - "Community 54"
Cohesion: 0.33
Nodes (5): downgrade(), Add ON UPDATE CASCADE to foreign keys referencing agents.id  This migration ad, Add ON UPDATE CASCADE to all foreign keys referencing agents.id, Remove CASCADE from foreign keys (revert to simple FKs), upgrade()

### Community 55 - "Community 55"
Cohesion: 0.33
Nodes (5): downgrade(), Consolidated Migration - All Database Schema and Procedures  This migration co, Consolidate all manual migrations into one authoritative migration.     This in, Downgrade is intentionally minimal - we don't want to drop data.     Only drop, upgrade()

### Community 56 - "Community 56"
Cohesion: 0.33
Nodes (5): downgrade(), add_security_indicators  Revision ID: a7e3b9c12d45 Revises: d20081a6c299 Cre, Create security_indicators table., Drop security_indicators table., upgrade()

### Community 57 - "Community 57"
Cohesion: 0.33
Nodes (5): downgrade(), fix app_switch deduplication logic  Revision ID: 20260401_fix_dedup Revises:, Fix process_app_switch_event to handle duplicate key violations gracefully., Restore the broken version without deduplication handling., upgrade()

### Community 58 - "Community 58"
Cohesion: 0.33
Nodes (5): downgrade(), Add dashboard analytics materialized views  Revision ID: 20260506_dash_mv_views, Create materialized views used by analytics dashboard widgets., Drop dashboard analytics materialized views., upgrade()

### Community 59 - "Community 59"
Cohesion: 0.33
Nodes (5): downgrade(), eol_scanning_tables  Revision ID: d20081a6c299 Revises: df29e57c74bb Create Date, Create EOL scanning tables., Drop EOL scanning tables., upgrade()

### Community 60 - "Community 60"
Cohesion: 0.33
Nodes (5): downgrade(), Add EOL enhancement fields for better lifecycle tracking  Revision ID: eol_enhan, Add EOL enhancement fields to asset_info table., Remove EOL enhancement fields from asset_info table., upgrade()

### Community 61 - "Community 61"
Cohesion: 0.4
Nodes (5): Screen Time Spans Endpoint - Add to server_telemetry.py  This file contains th, Receive screen time spans from agent.          Idempotent: ON CONFLICT (span_i, Validate screen time span before insertion.          Checks:     1. Duration, telemetry_screentime_spans(), validate_span()

### Community 62 - "Community 62"
Cohesion: 0.53
Nodes (4): getSelectedDate(), loadOverview(), renderCharts(), renderTop5Agents()

### Community 63 - "Community 63"
Cohesion: 0.6
Nodes (5): main(), _require_version(), _update_init_version(), _update_latest_json(), _write_agent_version_txt()

### Community 64 - "Community 64"
Cohesion: 0.4
Nodes (3): fix_agent_schema_conflicts  Revision ID: 4c19c566787a Revises: b416dc8ef37f, Upgrade schema - NEUTRALIZED to preserve agent_id UUID., upgrade()

### Community 65 - "Community 65"
Cohesion: 0.4
Nodes (3): fix_agents_id_to_string  Revision ID: b416dc8ef37f Revises: 003_add_api_key_a, Upgrade schema - NEUTRALIZED to preserve numeric ID., upgrade()

### Community 66 - "Community 66"
Cohesion: 0.7
Nodes (4): generate_certs(), generate_key(), save_cert(), save_key()

### Community 67 - "Community 67"
Cohesion: 0.5
Nodes (2): generate_integrity_manifest(), SEC-024: Generate integrity manifest after compilation

### Community 68 - "Community 68"
Cohesion: 0.5
Nodes (3): SentinelEdge Core Service - Entry Point Enhanced with secure identity, registra, Verify agent files haven't been tampered with, verify_integrity_check()

### Community 69 - "Community 69"
Cohesion: 0.5
Nodes (3): SentinelEdge Helper - Entry Point Enhanced with secure communication and replay, Verify agent files haven't been tampered with, verify_integrity_check()

### Community 70 - "Community 70"
Cohesion: 0.5
Nodes (1): Add CLI tools inventory table  Revision ID: 001_add_cli_tools_table Revises:

### Community 71 - "Community 71"
Cohesion: 0.5
Nodes (1): Initial Phase-1 database schema  Revision ID: 001_initial_migration Revises:

### Community 72 - "Community 72"
Cohesion: 0.5
Nodes (1): Add hardware drivers inventory table  Revision ID: 002_add_hardware_drivers_ta

### Community 73 - "Community 73"
Cohesion: 0.5
Nodes (1): Add DomainActiveSession and AgentPolicy tables  Revision ID: 002_add_new_table

### Community 74 - "Community 74"
Cohesion: 0.5
Nodes (1): Add VS Code extensions inventory table  Revision ID: 003_add_vscode_extensions

### Community 75 - "Community 75"
Cohesion: 0.5
Nodes (1): Add browser extensions inventory table  Revision ID: 004_add_browser_extension

### Community 76 - "Community 76"
Cohesion: 0.5
Nodes (1): add session_version to users  Revision ID: 004_session_version Revises: 003_add_

### Community 77 - "Community 77"
Cohesion: 0.5
Nodes (1): Add application plugins inventory table  Revision ID: 005_add_app_plugins Rev

### Community 78 - "Community 78"
Cohesion: 0.5
Nodes (1): Add username column to app_sessions and domain_sessions tables.  Revision ID:

### Community 79 - "Community 79"
Cohesion: 0.5
Nodes (1): Create domain_visits table for Column B (Sites Opened).  Revision ID: 006_add_

### Community 80 - "Community 80"
Cohesion: 0.5
Nodes (1): Add portable applications inventory table  Revision ID: 006_add_portable_apps

### Community 81 - "Community 81"
Cohesion: 0.5
Nodes (1): Add EOL system tables  Revision ID: 007_add_eol_system_tables Revises: 006_ad

### Community 82 - "Community 82"
Cohesion: 0.5
Nodes (1): Add foreign key cascades for agent deletion manual  Revision ID: 0c9e87d78584

### Community 83 - "Community 83"
Cohesion: 0.5
Nodes (1): Merge multiple head branches for session_version addition  Revision ID: 12b58b

### Community 84 - "Community 84"
Cohesion: 0.5
Nodes (1): merge heads  Revision ID: 1eb7f9e3f23e Revises: 20260403_fix_screentime, ddf5

### Community 85 - "Community 85"
Cohesion: 0.5
Nodes (1): add deduplication to switch events  Revision ID: 20250218_add_deduplication R

### Community 86 - "Community 86"
Cohesion: 0.5
Nodes (1): add domain duration to live status  Revision ID: 20250218_add_domain_duration

### Community 87 - "Community 87"
Cohesion: 0.5
Nodes (1): add stored procedures  Revision ID: 20250218_add_stored_procedures Revises: 8

### Community 88 - "Community 88"
Cohesion: 0.5
Nodes (1): add sync functions  Revision ID: 20250218_add_sync_functions Revises: 2025021

### Community 89 - "Community 89"
Cohesion: 0.5
Nodes (1): update screentime logic  Revision ID: 20250218_update_screentime_logic Revise

### Community 90 - "Community 90"
Cohesion: 0.5
Nodes (1): Alembic migration: Add screen time spans architecture  Revision ID: add_screen

### Community 91 - "Community 91"
Cohesion: 0.5
Nodes (1): Add session_start column and update stored procedure for reset detection  When

### Community 92 - "Community 92"
Cohesion: 0.5
Nodes (1): Add first_activity_at and enforce monotonic screentime procedure.  Revision ID:

### Community 93 - "Community 93"
Cohesion: 0.5
Nodes (1): Add email field and password reset functionality  Revision ID: 20260227_password

### Community 94 - "Community 94"
Cohesion: 0.5
Nodes (1): Add LEAST(86400) daily cap guard to process_screentime_event  Prevents any ind

### Community 95 - "Community 95"
Cohesion: 0.5
Nodes (1): Add auto-update management tables  Revision ID: 20260303_auto_update_tables R

### Community 96 - "Community 96"
Cohesion: 0.5
Nodes (1): Fix screentime locked->away reclassification on the server.  Revision ID: 2026

### Community 97 - "Community 97"
Cohesion: 0.5
Nodes (1): Make password_hash nullable for AD authentication support.  Revision ID: 2026041

### Community 98 - "Community 98"
Cohesion: 0.5
Nodes (1): Add report_schedules table  Revision ID: 20260430_report_schedules Revises: 2026

### Community 99 - "Community 99"
Cohesion: 0.5
Nodes (1): Add unified report features  Revision ID: 20260505_unified_report_features Revis

### Community 100 - "Community 100"
Cohesion: 0.5
Nodes (1): Add missing columns: recipients_json and result_pdf_path  Revision ID: 20260506_

### Community 101 - "Community 101"
Cohesion: 0.5
Nodes (1): final_schema_and_sync_fixes  Revision ID: 4c113c00dd0f Revises: 68e2644c1171

### Community 102 - "Community 102"
Cohesion: 0.5
Nodes (1): add login_audit table  Revision ID: 56bf0bd40db8 Revises: 20260505_unified_repor

### Community 103 - "Community 103"
Cohesion: 0.5
Nodes (1): add_domain_classification_rules  Revision ID: 668a1f8f863e Revises: 7204218e0

### Community 104 - "Community 104"
Cohesion: 0.5
Nodes (1): merge_heads  Revision ID: 68e2644c1171 Revises: 006_add_domain_visits, 202501

### Community 105 - "Community 105"
Cohesion: 0.5
Nodes (1): align_procedure_signatures  Revision ID: 7204218e0a8e Revises: 4c113c00dd0f

### Community 106 - "Community 106"
Cohesion: 0.5
Nodes (1): create_live_telemetry_tables  Revision ID: 87b72471d98c Revises: c15377a4441b

### Community 107 - "Community 107"
Cohesion: 0.5
Nodes (1): Merge heads  Revision ID: 931a3b58e3bc Revises: 0c9e87d78584, 20260227_passwo

### Community 108 - "Community 108"
Cohesion: 0.5
Nodes (1): Add auth_type and ad_object_guid to dashboard_users.  Revision ID: 20260415_add_

### Community 109 - "Community 109"
Cohesion: 0.5
Nodes (1): Refactor ingestion pipeline and database schema  Revision ID: c15377a4441b Re

### Community 110 - "Community 110"
Cohesion: 0.5
Nodes (1): add_agent_update_control_columns  Revision ID: c7c09b33cce8 Revises: fix_miss

### Community 111 - "Community 111"
Cohesion: 0.5
Nodes (1): merge_fix_inventory_and_app_switch_fix  Revision ID: ddf577c0e871 Revises: fi

### Community 112 - "Community 112"
Cohesion: 0.5
Nodes (1): enterprise_assets_upgrade  Revision ID: df29e57c74bb Revises: c7c09b33cce8 Creat

### Community 113 - "Community 113"
Cohesion: 0.5
Nodes (1): Fix app_inventory_changes table columns  Revision ID: fix_inventory_changes_2026

### Community 114 - "Community 114"
Cohesion: 0.5
Nodes (1): Fix missing columns in agents table  Revision ID: fix_missing_agent_columns R

### Community 115 - "Community 115"
Cohesion: 0.5
Nodes (1): Add missing fields to app_inventory and asset_info  Revision ID: inventory_and_a

### Community 116 - "Community 116"
Cohesion: 0.67
Nodes (3): main(), Run a python script and log output., run_script()

### Community 117 - "Community 117"
Cohesion: 0.83
Nodes (3): getChartColors(), getChartOptions(), getChartPalette()

### Community 118 - "Community 118"
Cohesion: 0.67
Nodes (0): 

### Community 119 - "Community 119"
Cohesion: 1.0
Nodes (0): 

### Community 120 - "Community 120"
Cohesion: 1.0
Nodes (0): 

### Community 121 - "Community 121"
Cohesion: 1.0
Nodes (0): 

### Community 122 - "Community 122"
Cohesion: 1.0
Nodes (0): 

### Community 123 - "Community 123"
Cohesion: 1.0
Nodes (0): 

### Community 124 - "Community 124"
Cohesion: 1.0
Nodes (0): 

### Community 125 - "Community 125"
Cohesion: 1.0
Nodes (0): 

### Community 126 - "Community 126"
Cohesion: 1.0
Nodes (0): 

### Community 127 - "Community 127"
Cohesion: 1.0
Nodes (1): Thread-safe connection context manager with transactions

### Community 128 - "Community 128"
Cohesion: 1.0
Nodes (1): Resolve a missing field to its default shape/value when possible.

### Community 129 - "Community 129"
Cohesion: 1.0
Nodes (1): Return current encryption method

### Community 130 - "Community 130"
Cohesion: 1.0
Nodes (1): Compare two version strings.         Returns: >0 if a > b, 0 if equal, <0 if a

### Community 131 - "Community 131"
Cohesion: 1.0
Nodes (1): Compute SHA256 hash of a file.

### Community 132 - "Community 132"
Cohesion: 1.0
Nodes (1): Safely delete a file or directory.

### Community 133 - "Community 133"
Cohesion: 1.0
Nodes (1): Get agent_id dynamically from config (may change after identity sync)

### Community 134 - "Community 134"
Cohesion: 1.0
Nodes (1): Create from persisted state

### Community 135 - "Community 135"
Cohesion: 1.0
Nodes (1): Normalize a string for CPE format (lowercase, underscores, no special chars)

### Community 136 - "Community 136"
Cohesion: 1.0
Nodes (1): Normalize a string for PURL format (lowercase, hyphens)

### Community 137 - "Community 137"
Cohesion: 1.0
Nodes (1): Normalize PowerShell JSON output that may be scalar or single-item list.

### Community 138 - "Community 138"
Cohesion: 1.0
Nodes (1): Normalize PowerShell JSON output so single-item arrays stay lists.

### Community 139 - "Community 139"
Cohesion: 1.0
Nodes (1): Number of items in batch

### Community 140 - "Community 140"
Cohesion: 1.0
Nodes (1): Check if an executable path matches common malware locations.

### Community 141 - "Community 141"
Cohesion: 1.0
Nodes (0): 

### Community 142 - "Community 142"
Cohesion: 1.0
Nodes (0): 

### Community 143 - "Community 143"
Cohesion: 1.0
Nodes (1): Generate CPE 2.3 formatted string.         Format: cpe:2.3:a:<vendor>:<product>

### Community 144 - "Community 144"
Cohesion: 1.0
Nodes (1): Check local NVD cache for known vulnerabilities matching this CPE.          Ar

### Community 145 - "Community 145"
Cohesion: 1.0
Nodes (1): Sanitize a string for CPE format

### Community 146 - "Community 146"
Cohesion: 1.0
Nodes (1): Extract best CVSS score and severity from CVE data

### Community 147 - "Community 147"
Cohesion: 1.0
Nodes (1): Extract CPE strings from CVE configuration nodes

### Community 148 - "Community 148"
Cohesion: 1.0
Nodes (1): Score EOL proximity: 0.0 = safe, 1.0 = long past EOL

### Community 149 - "Community 149"
Cohesion: 1.0
Nodes (1): Generate human-readable EOL proximity explanation

### Community 150 - "Community 150"
Cohesion: 1.0
Nodes (1): Score vulnerability exposure: 0.0 = no vulns, 1.0 = critical+exploit

### Community 151 - "Community 151"
Cohesion: 1.0
Nodes (1): Score deployment scope: 0.0 = single asset, 1.0 = entire fleet

### Community 152 - "Community 152"
Cohesion: 1.0
Nodes (1): Score compensating controls (higher = more mitigation).         This REDUCES ri

### Community 153 - "Community 153"
Cohesion: 1.0
Nodes (1): Generate actionable recommendations based on risk assessment

### Community 154 - "Community 154"
Cohesion: 1.0
Nodes (1): Check if status is stale (no update in 5 minutes)

### Community 155 - "Community 155"
Cohesion: 1.0
Nodes (0): 

### Community 156 - "Community 156"
Cohesion: 1.0
Nodes (0): 

### Community 157 - "Community 157"
Cohesion: 1.0
Nodes (1): Check if status is stale (no update in 5 minutes)

### Community 158 - "Community 158"
Cohesion: 1.0
Nodes (0): 

### Community 159 - "Community 159"
Cohesion: 1.0
Nodes (0): 

### Community 160 - "Community 160"
Cohesion: 1.0
Nodes (1): Log incoming request.

### Community 161 - "Community 161"
Cohesion: 1.0
Nodes (1): Log slow database query.

### Community 162 - "Community 162"
Cohesion: 1.0
Nodes (1): Log slow HTTP request.

### Community 163 - "Community 163"
Cohesion: 1.0
Nodes (1): Log large request/response payload.

### Community 164 - "Community 164"
Cohesion: 1.0
Nodes (1): Log agent registration.

### Community 165 - "Community 165"
Cohesion: 1.0
Nodes (1): Log agent data upload.

### Community 166 - "Community 166"
Cohesion: 1.0
Nodes (1): Log agent-related error.

### Community 167 - "Community 167"
Cohesion: 1.0
Nodes (1): Log agent status change.

### Community 168 - "Community 168"
Cohesion: 1.0
Nodes (1): Log authentication failure.

### Community 169 - "Community 169"
Cohesion: 1.0
Nodes (1): Log rate limit exceeded.

### Community 170 - "Community 170"
Cohesion: 1.0
Nodes (1): Log suspicious activity.

### Community 171 - "Community 171"
Cohesion: 1.0
Nodes (1): Log validation error.

## Knowledge Gaps
- **993 isolated node(s):** `Read default version from agent/VERSION.txt if available.`, `Resolve build version from:       1) CLI argument (python build_exe.py 2.7.0)`, `Write dist/VERSION.txt required by install_exe.bat.`, `Remove previous build artifacts`, `Common hidden imports needed by the agent.          AUDIT (2026-03-11): Verifi` (+988 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 119`** (2 nodes): `verify_buffer_health.py`, `main()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 120`** (2 nodes): `verify_runtime_syntax.py`, `main()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 121`** (2 nodes): `selectors.js`, `loadSelectors()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 122`** (2 nodes): `generate_pdf.py`, `main()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 123`** (1 nodes): `Analysis-00.toc`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 124`** (1 nodes): `EXE-00.toc`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 125`** (1 nodes): `PKG-00.toc`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 126`** (1 nodes): `PYZ-00.toc`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 127`** (1 nodes): `Thread-safe connection context manager with transactions`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 128`** (1 nodes): `Resolve a missing field to its default shape/value when possible.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 129`** (1 nodes): `Return current encryption method`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 130`** (1 nodes): `Compare two version strings.         Returns: >0 if a > b, 0 if equal, <0 if a`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 131`** (1 nodes): `Compute SHA256 hash of a file.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 132`** (1 nodes): `Safely delete a file or directory.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 133`** (1 nodes): `Get agent_id dynamically from config (may change after identity sync)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 134`** (1 nodes): `Create from persisted state`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 135`** (1 nodes): `Normalize a string for CPE format (lowercase, underscores, no special chars)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 136`** (1 nodes): `Normalize a string for PURL format (lowercase, hyphens)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 137`** (1 nodes): `Normalize PowerShell JSON output that may be scalar or single-item list.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 138`** (1 nodes): `Normalize PowerShell JSON output so single-item arrays stay lists.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 139`** (1 nodes): `Number of items in batch`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 140`** (1 nodes): `Check if an executable path matches common malware locations.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 141`** (1 nodes): `check_agents.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 142`** (1 nodes): `drop_test_db.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 143`** (1 nodes): `Generate CPE 2.3 formatted string.         Format: cpe:2.3:a:<vendor>:<product>`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 144`** (1 nodes): `Check local NVD cache for known vulnerabilities matching this CPE.          Ar`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 145`** (1 nodes): `Sanitize a string for CPE format`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 146`** (1 nodes): `Extract best CVSS score and severity from CVE data`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 147`** (1 nodes): `Extract CPE strings from CVE configuration nodes`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 148`** (1 nodes): `Score EOL proximity: 0.0 = safe, 1.0 = long past EOL`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 149`** (1 nodes): `Generate human-readable EOL proximity explanation`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 150`** (1 nodes): `Score vulnerability exposure: 0.0 = no vulns, 1.0 = critical+exploit`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 151`** (1 nodes): `Score deployment scope: 0.0 = single asset, 1.0 = entire fleet`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 152`** (1 nodes): `Score compensating controls (higher = more mitigation).         This REDUCES ri`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 153`** (1 nodes): `Generate actionable recommendations based on risk assessment`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 154`** (1 nodes): `Check if status is stale (no update in 5 minutes)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 155`** (1 nodes): `register_ad_user.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 156`** (1 nodes): `setup_path.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 157`** (1 nodes): `Check if status is stale (no update in 5 minutes)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 158`** (1 nodes): `charts.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 159`** (1 nodes): `update_user.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 160`** (1 nodes): `Log incoming request.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 161`** (1 nodes): `Log slow database query.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 162`** (1 nodes): `Log slow HTTP request.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 163`** (1 nodes): `Log large request/response payload.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 164`** (1 nodes): `Log agent registration.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 165`** (1 nodes): `Log agent data upload.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 166`** (1 nodes): `Log agent-related error.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 167`** (1 nodes): `Log agent status change.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 168`** (1 nodes): `Log authentication failure.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 169`** (1 nodes): `Log rate limit exceeded.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 170`** (1 nodes): `Log suspicious activity.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 171`** (1 nodes): `Log validation error.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DataCollector` connect `Community 3` to `Community 0`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `InventoryTracker` connect `Community 0` to `Community 3`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Why does `BufferDB` connect `Community 4` to `Community 1`, `Community 3`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Are the 176 inferred relationships involving `BufferDB` (e.g. with `HeartbeatAggregator` and `Aggregator Module Merges heartbeats into sessionized events`) actually correct?**
  _`BufferDB` has 176 INFERRED edges - model-reasoned connections that need verification._
- **Are the 134 inferred relationships involving `CoreConfig` (e.g. with `ConfigValidator` and `ReplayProtectionCache`) actually correct?**
  _`CoreConfig` has 134 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `HelperConfig` (e.g. with `DataCollector` and `Data Collector Module - ENHANCED ================================ Orchestrates`) actually correct?**
  _`HelperConfig` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 45 inferred relationships involving `AgentUpdater` (e.g. with `HelperMonitor` and `ManifestVerifier`) actually correct?**
  _`AgentUpdater` has 45 INFERRED edges - model-reasoned connections that need verification._