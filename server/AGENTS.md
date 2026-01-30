# SentinelEdge Server - Agent Development Guidelines

## 🚀 Build & Development Commands

### Dependencies & Setup
- **Install dependencies**: `pip install -r server_requirements.txt`
- **Virtual environment**: `python -m venv venv && source venv/bin/activate`
- **Database setup**: `alembic upgrade head`
- **Apply stored procedures**: `python scripts/fixes/apply_sync_functions.py`

### Running the Server
- **Development**: `python server_main.py`
- **Production**: `gunicorn -c gunicorn_config.py server_main:application`
- **Quick start script**: `./start_server.sh`
- **Health check**: `curl http://localhost:5050/`

### Database Operations
- **Create migration**: `alembic revision --autogenerate -m "description"`
- **Apply migrations**: `alembic upgrade head`
- **Downgrade**: `alembic downgrade -1`
- **Database sync**: `python scripts/startup_checks.py`

### Testing
- **No formal test suite currently exists** - this is a gap in the codebase
- **Manual testing**: Use curl/Postman to test API endpoints
- **Recommended test framework**: Add pytest with Flask fixtures for future testing

## 📋 Code Style Guidelines

### Language & Framework
- **Python**: 3.11+ (tested with 3.11.9)
- **Web Framework**: Flask with Blueprint pattern
- **Database**: PostgreSQL via SQLAlchemy ORM
- **Validation**: Pydantic schemas for request/response validation
- **Authentication**: API key-based (X-API-Key header) + JWT legacy support

### Import Organization
```python
# Standard library imports
import logging
import os
from datetime import datetime, timedelta

# Third-party imports
from flask import Blueprint, request, jsonify
from pydantic import ValidationError
import jwt

# Local imports
from extensions import db
import server_models
from server_auth import require_auth
from schemas import ScreentimeSchema
```

### Naming Conventions
- **Variables/Functions**: `snake_case` (e.g., `process_screentime_event`)
- **Classes**: `PascalCase` (e.g., `ScreentimeSchema`, `AgentModel`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `SERVER_TIMEZONE`)
- **Database tables**: `snake_case` (e.g., `domain_visits`)
- **API endpoints**: `/api/v1/telemetry/screentime` (kebab-case)

### Database Models
```python
class Agent(db.Model):
    """Always include docstring describing the model's purpose."""
    __tablename__ = 'agents'
    
    id = db.Column(db.String(128), primary_key=True)
    agent_name = db.Column(db.String(255), nullable=True)
    
    def to_dict(self):
        """Include to_dict() method for JSON serialization."""
        return {field.name: getattr(self, field.name) for field in self.__table__.columns}
```

### API Endpoints Pattern
```python
bp = Blueprint('telemetry', __name__)

@bp.route('/api/v1/telemetry/screentime', methods=['POST'])
@require_auth  # Always use authentication decorator
def handle_screentime():
    try:
        schema = ScreentimeSchema(**request.get_json())
        # Process request...
        return jsonify({"status": "success"}), 200
    except ValidationError as e:
        return jsonify({"error": "Validation failed", "details": e.errors()}), 400
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": "Internal server error"}), 500
```

### Error Handling
- **Validation errors**: Return 400 with Pydantic error details
- **Authentication errors**: Return 401 with clear message
- **Not found**: Return 404 for missing resources
- **Server errors**: Return 500, log full error, don't expose details
- **Always log**: Use structured logging with context `[MODULE] [agent_id]`

### Logging Guidelines
```python
import logging
logger = logging.getLogger(__name__)

# Structured logging with context
logger.info(f"[TELEMETRY] {agent_id} Processed screentime delta: {delta_seconds}s")
logger.warning(f"[AUTH] Invalid API key attempt from {request.remote_addr}")
logger.error(f"[DATABASE] Failed to sync data: {e}", exc_info=True)
```

### Configuration
- **Environment variables**: Use `server_config.py` for structured config
- **Required vars**: `DATABASE_URL`, `SECRET_KEY`, `REGISTRATION_SECRET`
- **Optional vars**: `SERVER_HOST`, `SERVER_PORT`, `LOG_LEVEL`
- **Never hardcode**: Secrets, database URLs, or API keys

### Database Interactions
```python
# Always use app context
with app.app_context():
    # Use text() for raw SQL with stored procedures
    result = db.session.execute(text("SELECT * FROM sync_screen_time_from_sessions(:date)"), 
                               {"date": current_date})
    
    # Commit explicitly
    db.session.commit()
    
    # Handle exceptions gracefully
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error: {e}")
```

### Security Best Practices
- **Input validation**: Always validate with Pydantic schemas
- **SQL injection**: Use parameterized queries or ORM
- **Secrets management**: Use environment variables, never commit secrets
- **Authentication**: All telemetry endpoints require `@require_auth`
- **Rate limiting**: Use Flask-Limiter for API endpoints

### Code Organization
- **Blueprints**: Group related endpoints (telemetry, dashboard, auth)
- **Models**: Centralized in `server_models.py`
- **Schemas**: Located in `utils/schemas.py` (with backward compatibility wrapper)
- **Utilities**: Helper functions in `utils/` directory
- **Scripts**: Administrative and maintenance scripts in `scripts/`

### Time & Date Handling
- **Server timezone**: `'Asia/Kolkata'` (IST)
- **Database storage**: Store all timestamps in UTC
- **Timezone-aware**: Use `datetime.now(timezone.utc)` for current time
- **Format**: ISO 8601 strings for API responses

### Performance Considerations
- **Connection pooling**: Configure in SQLAlchemy
- **Bulk operations**: Use `db.session.bulk_insert_mappings()` for large datasets
- **Indexes**: Add database indexes for frequently queried columns
- **Background tasks**: Use threading for periodic sync/cleanup tasks

### File Structure Conventions
```
server/
├── server_main.py          # Entry point and application factory
├── server_app.py           # Flask app configuration
├── server_*.py             # Feature modules (api, telemetry, dashboard, etc.)
├── server_models.py        # SQLAlchemy models
├── server_config.py        # Configuration management
├── utils/                 # Shared utilities
├── migrations/             # Alembic database migrations
├── scripts/               # Administrative scripts
├── static/                 # CSS/JS assets
└── templates/              # Jinja2 templates
```

## 🛠️ Development Workflow

### Before Committing
1. **Test manually**: Verify API endpoints work
2. **Check imports**: No unused imports
3. **Validate schemas**: Ensure Pydantic schemas cover all fields
4. **Database changes**: Create Alembic migration if needed
5. **Error handling**: All code paths have proper error handling

### Common Patterns
- **Initialization**: Use `with app.app_context():` for DB operations
- **Authentication**: Decorate with `@require_auth` for protected endpoints
- **Validation**: Use Pydantic schemas for all request data
- **Response format**: Consistent JSON structure with status/error fields
- **Logging**: Include module and agent ID in log messages

### Security Checklist
- [ ] No hardcoded secrets or credentials
- [ ] All user inputs validated
- [ ] SQL queries parameterized
- [ ] Authentication on all sensitive endpoints
- [ ] Error messages don't leak sensitive information
- [ ] Proper session handling

## 📚 Key Documentation
- **API Reference**: `README.md` has complete endpoint documentation
- **Database Schema**: `server_models.py` contains table definitions
- **Stored Procedures**: Applied via `scripts/fixes/apply_sync_functions.py`
- **Deployment**: `DEPLOYMENT_GUIDE.md` for production setup