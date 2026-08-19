"""
AD Authentication Module - LDAP Direct User Bind

Supports authentication against on-premise Active Directory using direct user bind.
Uses ldap3 library for pure Python LDAP operations.
"""

import os
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


AD_CONFIG = {
    "provider": os.getenv("AD_PROVIDER", "").lower(),
    "server_url": os.getenv("AD_SERVER_URL", ""),
    "base_dn": os.getenv("AD_BASE_DN", ""),
    "timeout": int(os.getenv("AD_TIMEOUT", "10")),
    "bind_dn": os.getenv("AD_BIND_DN", ""),
    "bind_password": os.getenv("AD_BIND_PASSWORD", ""),
    "verify_ssl": os.getenv("AD_VERIFY_SSL", "true").lower() == "true",
    "ca_cert_path": os.getenv("AD_CA_CERT_PATH", ""),
    "domain": os.getenv("AD_DOMAIN", ""),  # Optional: for UPN format
}

if not AD_CONFIG["verify_ssl"] and not AD_CONFIG["ca_cert_path"]:
    logger.warning(
        "[AD_AUTH] TLS certificate validation is fully disabled for LDAPS "
        "(AD_VERIFY_SSL=false with no AD_CA_CERT_PATH set). Set AD_CA_CERT_PATH "
        "to your AD server's CA certificate to validate against it instead of "
        "disabling verification entirely."
    )


def is_ad_enabled() -> bool:
    """Check if AD authentication is enabled."""
    return bool(
        AD_CONFIG["provider"] == "ldap"
        and AD_CONFIG["server_url"]
        and AD_CONFIG["base_dn"]
    )


def get_ad_config() -> dict:
    """Get current AD configuration (without passwords)."""
    return {
        "provider": AD_CONFIG["provider"],
        "server_url": AD_CONFIG["server_url"],
        "base_dn": AD_CONFIG["base_dn"],
        "timeout": AD_CONFIG["timeout"],
        "verify_ssl": AD_CONFIG["verify_ssl"],
        "enabled": is_ad_enabled(),
    }


def _extract_username_from_linked(linked_username: str) -> str:
    """
    Extract username from linked_username format.

    Examples:
        'GODDSYSTEMS\\pittalabhaskar' -> 'pittalabhaskar'
        'pittalabhaskar' -> 'pittalabhaskar'
        'pittalabhaskar@goddsyetems.co.in' -> 'pittalabhaskar'
    """
    if not linked_username:
        return ""

    # Handle DOMAIN\\username format
    if "\\" in linked_username:
        return linked_username.split("\\")[-1]

    # Handle userPrincipalName format (email)
    if "@" in linked_username:
        return linked_username.split("@")[0]

    # Already just username
    return linked_username


def authenticate_ldap(
    username: str, password: str, linked_username: str = None
) -> Tuple[bool, str]:
    """
    Authenticate user against AD using direct user bind.

    Args:
        username: Local dashboard username (NOT used for DN construction - only
            linked_username is used to build the LDAP bind DN. This parameter is
            accepted for logging/API-compat but intentionally ignored to prevent
            LDAP injection attacks.
        password: User's AD password
        linked_username: The AD username to bind with (e.g., 'GODDSYSTEMS\\pittalabhaskar')

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not is_ad_enabled():
        return False, "AD authentication is not configured"

    if not password:
        return False, "Password is required"

    # Determine which username to use for AD bind
    if linked_username:
        ad_username = _extract_username_from_linked(linked_username)
    else:
        return False, "No linked AD account configured"

    if not ad_username:
        return False, "Invalid linked username"

    try:
        from ldap3 import Server, Connection, ALL_ATTRIBUTES, Tls
        import ssl
        import re

        server_url = AD_CONFIG["server_url"]
        base_dn = AD_CONFIG["base_dn"]
        timeout = AD_CONFIG["timeout"]

        # Sanitize username for DN building (remove special chars that break DN format)
        clean_username = re.sub(r"[^a-zA-Z0-9._-]", "", ad_username)
        if not clean_username:
            return False, "Invalid AD username format"

        # Create server - handle TLS properly
        use_ssl = server_url.startswith("ldaps://")

        # Use ldap3's native TLS configuration
        server_kwargs = {
            "get_info": ALL_ATTRIBUTES,
            "connect_timeout": timeout,
        }

        # Add TLS configuration for LDAPS
        if use_ssl:
            from ldap3 import Tls

            if AD_CONFIG["ca_cert_path"]:
                # Validate against the configured CA instead of disabling
                # verification, even when AD_VERIFY_SSL is off.
                tls_config = Tls(
                    validate=ssl.CERT_REQUIRED,
                    version=ssl.PROTOCOL_TLS_CLIENT,
                    ca_certs_file=AD_CONFIG["ca_cert_path"],
                )
            else:
                tls_config = Tls(
                    validate=ssl.CERT_NONE
                    if not AD_CONFIG["verify_ssl"]
                    else ssl.CERT_REQUIRED,
                    version=ssl.PROTOCOL_TLS_CLIENT,
                )
            server_kwargs["tls"] = tls_config

        # Create server
        server = Server(server_url, use_ssl=use_ssl, **server_kwargs)

        # Build user DN - try different formats using sanitized username
        domain = (
            AD_CONFIG.get("domain", "")
            or server_url
            .replace("ldap://", "")
            .replace("ldaps://", "")
            .split(":")[0]
        )
        user_dn_variants = [
            f"cn={clean_username},cn=Users,{base_dn}",
            f"sAMAccountName={clean_username},{base_dn}",
            f"{clean_username}@{domain}" if domain else None,
            clean_username,
            # Raw/unsanitized UPN variant (ad_username may have spaces)
            f"{ad_username}@{domain}" if domain else None,
        ]
        user_dn_variants = [d for d in user_dn_variants if d]  # Remove None

        # Try each DN format
        connection = None
        for user_dn in user_dn_variants:
            try:
                connection = Connection(
                    server,
                    user=user_dn,
                    password=password,
                    auto_bind=True,
                    receive_timeout=timeout,
                )
                logger.info(f"[AD_AUTH] Successfully authenticated user: {ad_username}")
                return True, "Authentication successful"
            except Exception as e:
                continue

        # If we get here, none of the DN formats worked
        logger.warning(
            f"[AD_AUTH] Failed to authenticate user: {ad_username} - invalid credentials or DN format"
        )
        return False, "Invalid username or password"

    except ImportError:
        logger.error("[AD_AUTH] ldap3 library not installed")
        return False, "AD authentication not available"
    except Exception as e:
        logger.error(f"[AD_AUTH] AD authentication error: {e}")
        # Return generic error to not reveal internal details
        return False, "Unable to connect to authentication server"


def test_ad_connection() -> Tuple[bool, str]:
    """
    Test AD connection with current configuration.

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not is_ad_enabled():
        return False, "AD is not configured"

    try:
        from ldap3 import Server, Connection, ALL_ATTRIBUTES
        import ssl

        server_url = AD_CONFIG["server_url"]
        base_dn = AD_CONFIG["base_dn"]
        timeout = AD_CONFIG["timeout"]

        # Create server - handle TLS properly
        use_ssl = server_url.startswith("ldaps://")

        server_kwargs = {
            "get_info": ALL_ATTRIBUTES,
            "connect_timeout": timeout,
        }

        # Add TLS configuration for LDAPS
        if use_ssl:
            tls_config = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            tls_config.minimum_version = ssl.TLSVersion.TLSv1_2
            if AD_CONFIG["ca_cert_path"]:
                # Validate against the configured CA instead of disabling
                # verification, even when AD_VERIFY_SSL is off.
                tls_config.load_verify_locations(cafile=AD_CONFIG["ca_cert_path"])
                tls_config.verify_mode = ssl.CERT_REQUIRED
                server_kwargs["tls"] = tls_config
            elif not AD_CONFIG["verify_ssl"]:
                tls_config.check_hostname = False
                tls_config.verify_mode = ssl.CERT_NONE
                server_kwargs["tls"] = tls_config

        # Create server
        server = Server(server_url, use_ssl=use_ssl, **server_kwargs)

        # Try anonymous bind to test connection
        connection = Connection(server, auto_bind=True, receive_timeout=timeout)

        if connection.bound:
            logger.info("[AD_AUTH] AD connection test successful")
            return True, f"Connected to {server_url}"

        return False, "Connection failed"

    except Exception as e:
        logger.error(f"[AD_AUTH] AD connection test failed: {e}")
        return False, str(e)
