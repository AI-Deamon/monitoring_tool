# SentinelEdge Server - Agent Guidelines

## Development Commands
- **Install dependencies**: `pip install -r server_requirements.txt`
- **Run development server**: `python server_main.py`
- **Run production**: `gunicorn --bind 0.0.0.0:5050 --workers 4 wsgi:app`
- **Database migrations**: `alembic upgrade head`
- **Create migration**: `alembic revision --autogenerate -m "description"`

## Code Style Guidelines
- **Language**: Python 3.11+
- **Framework**: Flask with SQLAlchemy ORM
- **Validation**: Use Pydantic schemas for request/response validation
- **Database**: PostgreSQL with Alembic migrations
- **Authentication**: API key-based auth via X-API-Key and X-Agent-ID headers
- **Logging**: Use structured logging with AgentLogger for telemetry
- **Error handling**: Return JSON responses with appropriate HTTP status codes
- **Imports**: Group imports (stdlib, third-party, local) with no unused imports
- **Naming**: snake_case for variables/functions, PascalCase for classes
- **Models**: All SQLAlchemy models inherit from db.Model and include to_dict() method
- **API endpoints**: Use Blueprint pattern, decorate with @require_auth for protected routes