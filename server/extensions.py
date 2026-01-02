"""
Database extensions - separated to avoid circular imports.
"""
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy import event
import logging

logger = logging.getLogger(__name__)

db = SQLAlchemy()


def configure_database_pooling(app, config):
    """Configure database connection pooling for better resource management."""
    try:
        if 'sqlite' in config.DATABASE_URL:
            # SQLite doesn't benefit from pooling
            app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                'poolclass': NullPool,
            }
        else:
            # Use QueuePool for PostgreSQL/MySQL
            app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                'pool_size': config.DB_POOL_SIZE,
                'pool_recycle': config.DB_POOL_RECYCLE,
                'max_overflow': config.DB_MAX_OVERFLOW,
                'pool_timeout': config.DB_POOL_TIMEOUT,
                'pool_pre_ping': True,  # Test connections before using them
            }
        
        logger.info(f"Database pooling configured: pool_size={config.DB_POOL_SIZE}, max_overflow={config.DB_MAX_OVERFLOW}")
    except Exception as e:
        logger.error(f"Error configuring database pooling: {e}")
        raise


def setup_db_event_listeners(app):
    """Setup database event listeners. Must be called within app context."""
    try:
        @event.listens_for(db.engine, 'connect')
        def receive_connect(dbapi_conn, connection_record):
            connection_record.info['connect_time'] = __import__('time').time()
        
        @event.listens_for(db.engine, 'checkout')
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            logger.debug(f"DB connection checked out from pool")
        
        logger.debug("Database event listeners registered")
    except Exception as e:
        logger.debug(f"Note: Event listeners may have already been registered: {e}")
