"""
Authentication module for SentinelEdge Server.

Supports two authentication methods:
1. X-API-Key header (new, preferred) - Simple API key authentication
2. Authorization: Bearer (legacy) - JWT token authentication

The X-API-Key method is now the primary authentication method.
"""

import jwt
import secrets
import hashlib
import logging
import os
from functools import wraps
from datetime import datetime, timedelta
from flask import request, jsonify, current_app, g
import server_models
from extensions import db

logger = logging.getLogger(__name__)

# ============================================================================
# JWT SECRET SECURITY (Bug #4 Fix)
# ============================================================================
# Load JWT configuration directly from environment to ensure consistency
JWT_SECRET = os.getenv('JWT_SECRET') or os.getenv('SECRET_KEY')

# SECURITY: Fail-fast if secret not configured properly
INSECURE_SECRETS = {'dev-secret', 'development', 'secret', 'changeme', 'password'}
_is_dev_mode = os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_DEBUG') == '1'

if not JWT_SECRET:
    if _is_dev_mode:
        JWT_SECRET = 'dev-secret-for-local-testing-only'
        logger.warning("[JWT] ⚠️ Using insecure dev secret - DO NOT USE IN PRODUCTION!")
    else:
        raise RuntimeError(
            "CRITICAL: JWT_SECRET environment variable is not set!\n"
            "Set JWT_SECRET or SECRET_KEY to a secure random string (32+ chars).\n"
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
elif JWT_SECRET.lower() in INSECURE_SECRETS or len(JWT_SECRET) < 16:
    if _is_dev_mode:
        logger.warning(f"[JWT] ⚠️ Insecure JWT secret detected - OK for dev, NOT for production!")
    else:
        raise RuntimeError(
            f"CRITICAL: JWT_SECRET is insecure ('{JWT_SECRET[:10]}...')!\n"
            "Use a strong random secret (32+ chars) in production."
        )

JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '720'))  # 30 days

# Log JWT configuration for debugging (don't log secret!)
logger.info(f"[JWT] Initialized with algorithm: {JWT_ALGORITHM}, secret length: {len(JWT_SECRET)}")


# =============================================================================
# SEC-007: API KEY HASHING
# =============================================================================
# API keys are stored as SHA256 hashes in the database.
# Plaintext keys are returned to agents only during registration.
# =============================================================================

def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for secure storage using SHA256.
    The hash is prefixed with 'hashed_' for identification.
    """
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    return f"hashed_{key_hash}"


def is_hashed_key(stored_key: str) -> bool:
    """Check if a stored key is already hashed (vs legacy plaintext)."""
    return stored_key and stored_key.startswith('hashed_')


def generate_api_key() -> tuple:
    """
    Generate a secure API key with 'sk_live_' prefix.
    
    Returns:
        tuple: (plaintext_key, hashed_key)
        - plaintext_key: Return to agent (only given once)
        - hashed_key: Store in database
    """
    # Generate a random 32-byte token (64 hex characters)
    random_part = secrets.token_hex(32)
    plaintext_key = f"sk_live_{random_part}"
    hashed_key = hash_api_key(plaintext_key)
    
    return plaintext_key, hashed_key


def generate_api_token(agent_id: str) -> str:
    """Generate JWT token for agent (legacy method)."""
    payload = {
        'agent_id': agent_id,
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.debug(f"[JWT] Generated token for agent {agent_id} with secret length: {len(JWT_SECRET)}")
    return token


def verify_jwt_token(token: str) -> dict:
    """Verify and decode JWT token. Returns payload or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logger.debug(f"[JWT] Successfully verified token for agent: {payload.get('agent_id')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"[JWT] Invalid JWT token: {e}")
        logger.debug(f"[JWT] Secret used for verification length: {len(JWT_SECRET)}")
        return None


def verify_api_key(api_key: str, agent_id: str) -> server_models.Agent:
    """
    Verify API key against database.
    
    SEC-007: Supports both:
    - Hashed keys (new): Compare hash of incoming key with stored hash
    - Legacy plaintext keys: Compare with constant-time comparison
    
    Returns agent object if valid, None otherwise.
    """
    if not api_key or not agent_id:
        logger.debug("[AUTH] Missing API key or agent_id")
        return None
    
    try:
        # Find agent by UUID
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        
        if not agent:
            logger.warning(f"[AUTH] Agent not found: {agent_id}")
            return None
        
        # Check if agent has api_key stored
        stored_key = getattr(agent, 'api_key', None) or getattr(agent, 'api_token', None)
        
        if not stored_key:
            logger.warning(f"[AUTH] Agent {agent_id} has no API key stored")
            return None
        
        # ====================================================================
        # SEC-007: Hash-based API key verification
        # ====================================================================
        import hmac
        
        if is_hashed_key(stored_key):
            # New style: Compare hashes
            incoming_hash = hash_api_key(api_key)
            if hmac.compare_digest(stored_key, incoming_hash):
                logger.debug(f"[AUTH] Hashed API key validated for agent: {agent_id}")
                return agent
        else:
            # Legacy: Compare plaintext (for backward compatibility)
            # NOTE: New registrations will use hashed keys
            if hmac.compare_digest(str(stored_key), str(api_key)):
                logger.debug(f"[AUTH] Legacy API key validated for agent: {agent_id}")
                return agent
        
        logger.warning(f"[AUTH] API key mismatch for agent: {agent_id}")
        # NOTE: Don't log actual keys, even fragments, to prevent log-based leakage
        return None
        
    except Exception as e:
        logger.error(f"[AUTH] Error verifying API key: {e}")
        return None


def require_auth(fn):
    """
    Decorator to require API authentication.
    
    Supports two authentication methods:
    1. X-API-Key header (preferred) - Direct API key
    2. Authorization: Bearer header (legacy) - JWT token
    
    Also requires X-Agent-ID header for agent identification.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        agent_id = request.headers.get('X-Agent-ID')
        logger.debug(f"[AUTH] Request headers - X-Agent-ID: {agent_id}, X-API-Key: {request.headers.get('X-API-Key', 'None')}, Authorization: {request.headers.get('Authorization', 'None')[:50]}...")
        
        # ============================================================
        # Method 1: X-API-Key header (New, Preferred)
        # ============================================================
        api_key = request.headers.get('X-API-Key')
        
        if api_key:
            logger.debug(f"[AUTH] Using X-API-Key authentication for agent: {agent_id}")
            
            if not agent_id:
                logger.warning("[AUTH] Missing X-Agent-ID header with X-API-Key auth")
                return jsonify({'error': 'Missing X-Agent-ID header'}), 401
            
            agent = verify_api_key(api_key, agent_id)
            
            if not agent:
                logger.warning(f"[AUTH] Invalid API key for agent: {agent_id}")
                return jsonify({'error': 'Invalid API key'}), 401
            
            # Update last_seen
            try:
                agent.last_seen = datetime.utcnow()
                db.session.commit()
            except Exception as e:
                logger.error(f"[AUTH] Failed to update last_seen: {e}")
                db.session.rollback()
            
            # Store authenticated agent in Flask's g context
            g.current_agent = agent
            return fn(*args, **kwargs)
        
        # ============================================================
        # Method 2: Authorization: Bearer header (Legacy)
        # ============================================================
        auth = request.headers.get('Authorization', '')
        
        if auth.startswith('Bearer '):
            logger.debug(f"[AUTH] Using Bearer token authentication for agent: {agent_id}")
            
            token = auth.split(' ', 1)[1]
            payload = verify_jwt_token(token)
            
            # If JWT verification succeeds, extract agent_id from token if not provided in header
            if payload:
                token_agent_id = payload.get('agent_id')
                # Use agent_id from header if available, otherwise from token
                final_agent_id = agent_id or token_agent_id
                logger.debug(f"[AUTH] JWT verified, using agent_id: {final_agent_id}")
                
                agent = server_models.Agent.query.filter_by(agent_id=final_agent_id).first()
                if agent:
                    # Update last_seen
                    try:
                        agent.last_seen = datetime.utcnow()
                        db.session.commit()
                    except Exception as e:
                        logger.error(f"[AUTH] Failed to update last_seen: {e}")
                        db.session.rollback()
                    g.current_agent = agent
                    return fn(*args, **kwargs)
                else:
                    logger.warning(f"[AUTH] Agent not found: {final_agent_id}")
                    return jsonify({'error': 'Agent not found'}), 401
            
            # If JWT verification fails, try matching token directly against stored api_token
            if not payload and agent_id:
                logger.debug(f"[AUTH] JWT verification failed, trying direct token match for agent: {agent_id}")
                agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
                if agent and agent.api_token == token:
                    logger.info(f"[AUTH] Direct token match successful for agent: {agent_id}")
                    # Update last_seen
                    try:
                        agent.last_seen = datetime.utcnow()
                        db.session.commit()
                    except Exception as e:
                        logger.error(f"[AUTH] Failed to update last_seen: {e}")
                        db.session.rollback()
                    g.current_agent = agent
                    return fn(*args, **kwargs)
            
            if not payload:
                logger.debug("[AUTH] JWT verification failed, no fallback match")
                return jsonify({'status': 'error', 'message': 'Invalid token'}), 401
            
            if not agent_id or agent_id != payload.get('agent_id'):
                logger.warning(f"[AUTH] Agent ID mismatch: header={agent_id}, token={payload.get('agent_id')}")
                return jsonify({'status': 'error', 'message': 'Invalid agent_id'}), 401
            
            # Update last_seen
            try:
                agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
                if agent:
                    agent.last_seen = datetime.utcnow()
                    db.session.commit()
            except Exception as e:
                logger.error(f"[AUTH] Failed to update last_seen: {e}")
                db.session.rollback()
            
            # Store authenticated agent in Flask's g context
            g.current_agent = agent
            return fn(*args, **kwargs)
        
        # ============================================================
        # No valid authentication provided
        # ============================================================
        logger.warning("[AUTH] No valid authentication provided")
        logger.debug(f"[AUTH] Headers received: {dict(request.headers)}")
        return jsonify({'error': 'Missing authentication. Use X-API-Key or Authorization header.'}), 401
    
    return wrapper


# Alias for backward compatibility
verify_token = verify_jwt_token
