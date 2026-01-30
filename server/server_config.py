import os
from dotenv import load_dotenv
from types import SimpleNamespace

# Load environment variables from .env file
load_dotenv()

def get_config() -> SimpleNamespace:
    """Return runtime config from environment variables."""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL is not set in the environment.")
    
    return SimpleNamespace(
        # Database
        DATABASE_URL=database_url,
        DB_POOL_SIZE=int(os.getenv('DB_POOL_SIZE', '10')),
        DB_POOL_RECYCLE=int(os.getenv('DB_POOL_RECYCLE', '3600')),  # 1 hour
        DB_MAX_OVERFLOW=int(os.getenv('DB_MAX_OVERFLOW', '20')),
        DB_POOL_TIMEOUT=int(os.getenv('DB_POOL_TIMEOUT', '30')),
        
        # Server
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-secret'),
        HOST=os.getenv('SERVER_HOST', '0.0.0.0'),
        PORT=int(os.getenv('SERVER_PORT', '5050')),
        LOG_LEVEL=os.getenv('LOG_LEVEL', 'INFO'),
        USE_TLS=os.getenv('USE_TLS', 'false').lower() == 'true',
        
        # Security
        JWT_ALGORITHM='HS256',
        JWT_EXPIRATION_HOURS=24 * 30,  # 30 days
        MAX_REQUEST_SIZE=10 * 1024 * 1024,  # 10MB
        REQUEST_TIMEOUT=30,  # seconds
        
        # Agent Health (Optimized for 1-min uploads)
        AGENT_HEARTBEAT_TIMEOUT=120,   # 2 minutes - mark offline
        AGENT_STALE_TIMEOUT=240,       # 4 minutes - mark stale
        
        # Rate Limiting
        RATE_LIMIT_ENABLED=os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true',
        RATE_LIMIT_REQUESTS=int(os.getenv('RATE_LIMIT_REQUESTS', '100')),
        RATE_LIMIT_PERIOD=int(os.getenv('RATE_LIMIT_PERIOD', '60')),  # seconds
        
        # Data Retention
        RETENTION_DAYS=int(os.getenv('RETENTION_DAYS', '90')),  # Keep 90 days of data
        CLEANUP_INTERVAL_HOURS=int(os.getenv('CLEANUP_INTERVAL_HOURS', '24')),
    )
