from flask import Flask
from extensions import db
from server_config import get_config
import logging
import os
from datetime import timedelta

# Try to import Flask-CORS
try:
    from flask_cors import CORS
    CORS_AVAILABLE = True
except ImportError:
    CORS_AVAILABLE = False

logger = logging.getLogger(__name__)

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
    # SESSION CONFIGURATION (for dashboard auth)
    # ================================================================
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True when using HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Configure extensions
    from extensions import configure_database_pooling, setup_db_event_listeners
    configure_database_pooling(app, config)
    db.init_app(app)
    
    # ================================================================
    # Fix #11: Configure CORS for cross-origin requests
    # ================================================================
    if CORS_AVAILABLE:
        # Get allowed origins from environment (comma-separated) or allow all
        allowed_origins = os.getenv('CORS_ORIGINS', '*')
        if allowed_origins != '*':
            allowed_origins = [o.strip() for o in allowed_origins.split(',')]
        
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
        from server_api import bp as api_bp, register_root_endpoint, telemetry_bp
        from server_telemetry import bp as telemetry_bp_v1, register_root_telemetry_endpoints
        from server_dashboard import bp as dash_bp
        from admin_classification import admin_classification_bp
        from server_integrity import bp as integrity_bp, register_integrity_endpoints
        
        # ================================================================
        # AUTHENTICATION: Register auth blueprint
        # ================================================================
        from auth import auth_bp, DashboardUser, create_default_admin

        # Register Blueprints
        app.register_blueprint(api_bp, url_prefix='/api/v1')
        app.register_blueprint(telemetry_bp_v1, url_prefix='/api/v1/telemetry')
        app.register_blueprint(telemetry_bp)  # 🔴 REQUIRED: No prefix for /telemetry/event
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

        # Ensure models are loaded
        import server_models
        
        # ================================================================
        # Create auth tables and default admin
        # ================================================================
        try:
            db.create_all()  # Creates dashboard_users table if not exists
            if create_default_admin():
                logger.info("[AUTH] Default admin user created: admin / changeme123")
                logger.warning("[AUTH] ⚠️  CHANGE THE DEFAULT PASSWORD IMMEDIATELY!")
        except Exception as e:
            logger.error(f"[AUTH] Failed to initialize auth: {e}")

    # Start background scheduler (only in main process, not in testing)
    if not app.config.get('TESTING'):
        try:
            from background_tasks import start_background_tasks
            app.background_scheduler = start_background_tasks(app)
        except Exception as e:
            logger.warning(f"[SCHEDULER] Failed to start background tasks: {e}")

    return app

# No other global functions or routes should exist in this file

