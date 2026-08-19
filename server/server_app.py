from flask import Flask, jsonify, send_file, request, g, session
from extensions import db
from server_config import get_config
import logging
import os
import secrets as _secrets
from datetime import timedelta
from pathlib import Path

# Try to import Flask-CORS
try:
    from flask_cors import CORS
    CORS_AVAILABLE = True
except ImportError:
    CORS_AVAILABLE = False

logger = logging.getLogger(__name__)


def resolve_cors_origins():
    """CORS allowlist from env. Default is EMPTY (same-origin only) — never
    '*'. An explicit '*' is refused in production to avoid arbitrary-origin
    trust, especially with credentialed /api/* requests."""
    raw = os.getenv('CORS_ORIGINS', '').strip()
    if not raw:
        return []
    if raw == '*':
        if os.getenv('FLASK_ENV', 'production') == 'production':
            raise RuntimeError("CORS_ORIGINS='*' is not permitted in production")
        return '*'
    return [o.strip() for o in raw.split(',') if o.strip()]


def create_app():
    """Create and configure the Flask application"""
    config = get_config()
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # ================================================================
    # DISABLE TEMPLATE CACHING FOR DEVELOPMENT
    # ================================================================
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    
    # H-17 FIX: Explicit XSS protection via Jinja autoescaping
    app.jinja_env.autoescape = True  # Enabled by default, but make it explicit

    # Feature 037, FR-007: the single canonical date presentation, registered on
    # the Flask environment so server-rendered pages match client-rendered ones.
    # A value shown by Jinja and the same value shown by DateFmt must look
    # identical, or SC-004 ("zero deviating screens") cannot hold.
    from utils.datetime_format import format_date as _fmt_date
    from utils.datetime_format import format_datetime as _fmt_datetime
    app.jinja_env.filters['fmt_date'] = _fmt_date
    app.jinja_env.filters['fmt_datetime'] = _fmt_datetime
    from utils.datetime_format import format_datetime_labelled as _fmt_dt_lbl
    app.jinja_env.filters['fmt_datetime_tz'] = _fmt_dt_lbl
    
    # H-17 FIX: Add Content-Security-Policy header for defense-in-depth
    @app.before_request
    def _make_csp_nonce():
        g.csp_nonce = _secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        return {"csp_nonce": lambda: getattr(g, "csp_nonce", "")}

    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses."""
        # Nonce-based CSP: inline <script>/<style> blocks must carry
        # nonce="{{ csp_nonce() }}". 'unsafe-inline' is confined to
        # script-src-attr (inline onclick/onchange handlers) — script-src
        # itself has no 'unsafe-inline', so attacker-injected <script>
        # tags are blocked.
        nonce = getattr(g, "csp_nonce", "")
        # Tailwind is precompiled to static/css/tailwind.css (no runtime/CDN),
        # so script-src needs no CDN host and no 'unsafe-eval'. Inline
        # <script>/<style> blocks use 'nonce-{nonce}'. 'unsafe-inline' remains
        # only where it is unavoidable:
        #   - script-src-attr : inline onclick/onchange handlers
        #   - style-src       : inline style="..." attributes in templates
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "script-src-attr 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        if config.USE_TLS:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        # Feature 037 / FR-002: authenticated pages must not survive sign-out in
        # the browser cache. Without no-store, pressing Back after signing out
        # re-renders a dashboard page from cache — the page is stale and the
        # session is dead, but a bystander still sees monitored employee data.
        #
        # Applied only to authenticated responses: static assets are cacheable
        # and making them no-store would discard that for no benefit.
        if 'user_id' in session:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    @app.before_request
    def _enforce_https():
        if os.getenv('FORCE_HTTPS', 'false').lower() == 'true' and not request.is_secure \
                and request.headers.get('X-Forwarded-Proto', 'http') != 'https':
            from flask import redirect
            return redirect(request.url.replace('http://', 'https://', 1), code=308)

    @app.before_request
    def _static_methods_guard():
        # Burp #1 (client-side desync): a POST with a smuggled second request was
        # accepted on a /static/ path. Static assets are read-only, so reject any
        # non-idempotent method before the body is processed.
        if request.path.startswith('/static/') \
                and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            from flask import abort
            abort(405)
    
    # ================================================================
    # ISSUE-001 FIX: Enforce strong SECRET_KEY in production
    # ================================================================
    flask_env = os.getenv('FLASK_ENV', 'production')
    secret_key = config.SECRET_KEY or os.getenv('SECRET_KEY')
    weak_secrets = {'dev-secret', 'development', 'secret', 'changeme', '', None}
    
    if flask_env == 'production':
        if secret_key in weak_secrets or (secret_key and len(secret_key) < 32):
            raise RuntimeError(
                "\n" + "=" * 70 + "\n"
                "CRITICAL: SECRET_KEY not set or too weak for production!\n"
                "Set SECRET_KEY environment variable to a random 32+ character string.\n"
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
                + "=" * 70
            )
        app.config['SECRET_KEY'] = secret_key
        logger.info("[SECURITY] SECRET_KEY validated for production")
    else:
        # Development mode - allow weak key with warning
        app.config['SECRET_KEY'] = secret_key or 'dev-secret-for-local-testing-only'
        if not secret_key or secret_key in weak_secrets:
            logger.warning("[SECURITY] Using weak SECRET_KEY - OK for development, NOT for production!")
    
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_REQUEST_SIZE
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

    # ================================================================
    # RESPONSE COMPRESSION (dependency-free gzip)
    # ================================================================
    # The dashboard JSON (overview bundle, top apps/domains, telemetry) is
    # highly repetitive and compresses ~80%. Done as an after_request hook
    # rather than a new dependency: gzip only text/JSON responses above a
    # size floor, only when the client advertises support, and never a
    # streamed or already-encoded response.
    import gzip as _gzip

    _COMPRESS_MIN_BYTES = 1024
    _COMPRESS_TYPES = ('application/json', 'text/html', 'text/css',
                       'application/javascript', 'text/javascript',
                       'text/plain', 'image/svg+xml')

    @app.after_request
    def _compress_response(response):
        try:
            accept = request.headers.get('Accept-Encoding', '')
            if 'gzip' not in accept.lower():
                return response
            if response.direct_passthrough or response.status_code < 200 \
                    or response.status_code >= 300:
                return response
            if response.headers.get('Content-Encoding'):
                return response
            ctype = (response.content_type or '').split(';')[0].strip()
            if ctype not in _COMPRESS_TYPES:
                return response
            data = response.get_data()
            if len(data) < _COMPRESS_MIN_BYTES:
                return response
            compressed = _gzip.compress(data, compresslevel=6)
            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(compressed)
            response.headers.add('Vary', 'Accept-Encoding')
            return response
        except Exception as e:
            logger.warning(f"[COMPRESS] Skipped compression: {e}")
            return response


    # ================================================================
    # SESSION CONFIGURATION (for dashboard auth)
    # ================================================================
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    # C-09 FIX: Enhanced cookie security
    # - Secure: Only sent over HTTPS (when USE_TLS=True)
    # - HttpOnly: Not accessible via JavaScript (XSS protection)
    # - SameSite=Strict: Prevents CSRF attacks
    app.config['SESSION_COOKIE_SECURE'] = config.USE_TLS
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'

    # ================================================================
    # CSRF TOKEN: Make available in all templates app-wide
    # ================================================================
    @app.context_processor
    def inject_csrf_token():
        from auth import generate_csrf_token
        return {"csrf_token": generate_csrf_token}

    # Configure extensions
    from extensions import configure_database_pooling, setup_db_event_listeners
    configure_database_pooling(app, config)
    db.init_app(app)
    
    # ================================================================
    # Fix #11: Configure CORS for cross-origin requests
    # ================================================================
    if CORS_AVAILABLE:
        # Get allowed origins from environment (comma-separated) or same-origin only
        allowed_origins = resolve_cors_origins()
        
        CORS(app, resources={
            r"/api/*": {
                "origins": allowed_origins,
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-API-Key", "X-Agent-ID", "X-Registration-Secret"],
                "expose_headers": ["Content-Type", "X-Total-Count", "X-Response-Time"],
                "supports_credentials": True,
                "max_age": 3600
            },
            r"/dashboard/*": {
                "origins": allowed_origins,
                "methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
                "max_age": 3600
            }
        })
        logger.info(f"[CORS] Configured for /api/* and /dashboard/* (origins: {allowed_origins})")
    else:
        logger.warning("[CORS] flask-cors not installed. Run: pip install flask-cors")
    
    # ================================================================
    # PERF-002: Performance Middleware (Compression, Caching, Timing)
    # ================================================================
    try:
        from performance import init_performance_middleware, register_cache_stats_endpoint
        init_performance_middleware(app)
        register_cache_stats_endpoint(app)
        logger.info("[PERF] Performance middleware enabled")
    except ImportError as e:
        logger.warning(f"[PERF] Performance middleware not available: {e}")
    
    with app.app_context():
        setup_db_event_listeners(app)
        
        # Register Blueprints
        from server_api import bp as api_bp, register_root_endpoint
        from server_telemetry import bp as telemetry_bp_v1, register_root_telemetry_endpoints
        from server_dashboard import bp as dash_bp
        from engines.admin_classification import admin_classification_bp
        from server_integrity import bp as integrity_bp, register_integrity_endpoints
        
        # ================================================================
        # AUTHENTICATION: Register auth blueprint
        # ================================================================
        from auth import auth_bp, DashboardUser, create_default_admin

        # Register Blueprints
        app.register_blueprint(api_bp, url_prefix='/api/v1')
        app.register_blueprint(telemetry_bp_v1, url_prefix='/api/v1/telemetry')
        app.register_blueprint(dash_bp, url_prefix='/dashboard')
        app.register_blueprint(admin_classification_bp)  # Admin classification UI
        app.register_blueprint(auth_bp)  # Auth routes at /auth/*
        app.register_blueprint(integrity_bp, url_prefix='/api/v1/integrity')

        # Register root handlers (compatibility)
        register_root_endpoint(app)
        register_root_telemetry_endpoints(app)
        register_integrity_endpoints(app)
        
        # ================================================================
        # SEC-026: Register anomaly detection endpoints
        # ================================================================
        try:
            from anomaly_detector import register_anomaly_endpoints
            register_anomaly_endpoints(app, db)
            logger.info("[SECURITY] Anomaly detection endpoints registered")
        except ImportError as e:
            logger.warning(f"[SECURITY] Anomaly detection not available: {e}")
        
        # ================================================================
        # AUTO-UPDATE: Register update endpoints (OPTIONAL)
        # Existing agents work without this - backwards compatible
        # ================================================================
        try:
            from server_updates import updates_bp
            app.register_blueprint(updates_bp)
            logger.info("[UPDATES] Auto-update endpoints registered at /api/v1/updates/*")
        except ImportError as e:
            logger.debug(f"[UPDATES] Auto-update module not available: {e}")

        # Reports blueprint
        try:
            from server_reports import reports_bp
            app.register_blueprint(reports_bp)
            logger.info("[REPORTS] Report generation endpoints registered")
        except ImportError as e:
            logger.warning(f"[REPORTS] Report module not available: {e}")


        # Ensure models are loaded
        import server_models
        
        # ================================================================
        # Create auth tables and default admin
        # ================================================================
        try:
            # Note: Schema now managed exclusively via Alembic migrations.
            # db.create_all() removed.
            if create_default_admin():
                logger.info("[AUTH] Default admin user created: admin / changeme123")
                logger.warning("[AUTH] ⚠️  CHANGE THE DEFAULT PASSWORD IMMEDIATELY!")
        except Exception as e:
            logger.error(f"[AUTH] Failed to initialize auth (tables may be missing): {e}")

    openapi_spec_path = Path(__file__).resolve().parents[2] / 'openapi.yml'

    @app.route('/openapi.yml', methods=['GET'])
    def openapi_spec():
        if not openapi_spec_path.exists():
            return jsonify({'error': 'OpenAPI spec not found'}), 404
        return send_file(openapi_spec_path, mimetype='application/yaml')

    @app.route('/api/docs', methods=['GET'])
    def api_docs():
        # Compatibility route to the canonical OpenAPI spec.
        return openapi_spec()

    # Start background scheduler (only in main process, not in testing)
    if not app.config.get('TESTING'):
        try:
            from background_tasks import start_background_tasks
            app.background_scheduler = start_background_tasks(app)
        except Exception as e:
            logger.warning(f"[SCHEDULER] Failed to start background tasks: {e}")

    return app

# No other global functions or routes should exist in this file

