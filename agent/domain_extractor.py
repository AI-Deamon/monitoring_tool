"""
Domain extraction logic - this is what you're testing
"""
from urllib.parse import urlparse
import re
import ipaddress

def extract_domain(url, keep_www=None):
    """
    Extract domain from URL
    keep_www: None (auto-detect), True (always keep), False (always strip)
    """
    if not url:
        return None
    
    # Skip non-HTTP protocols
    if url.startswith(('about:', 'chrome:', 'edge:', 'file:', 'data:', 'javascript:')):
        return None
    
    try:
        # Handle protocol-relative URLs
        if url.startswith('//'):
            url = 'https:' + url
        # Add scheme if missing
        elif not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        
        parsed = urlparse(url)
        netloc = parsed.netloc
        
        if not netloc:
            return None
        
        # Handle user:pass@domain format
        if '@' in netloc:
            netloc = netloc.split('@')[1]
        
        # Handle port numbers
        if ':' in netloc:
            host, port = netloc.rsplit(':', 1)
            # Keep port for localhost and private IPs
            try:
                if is_private_or_local(host):
                    netloc = netloc  # Keep with port
                elif port in ('80', '443'):
                    netloc = host  # Strip standard ports
                # else keep non-standard port
            except:
                pass
        
        # Check if it's an IP address
        try:
            ipaddress.ip_address(netloc.split(':')[0])
            return netloc  # Return IP as-is
        except ValueError:
            pass
        
        # Handle international domain names (IDN) - only apply if actually needed
        try:
            # Only apply IDN encoding if domain contains non-ASCII characters
            if any(ord(char) > 127 for char in netloc):
                netloc = netloc.encode('idna').decode('ascii')
        except Exception:
            pass
        
# Handle www prefix based on parameter or auto-detect
        if keep_www is not None:
            # Explicit setting
            if not keep_www and netloc.startswith('www.'):
                netloc = netloc[4:]
        else:
            # Auto-detect: strip www for consistency (most common behavior)
            if netloc.startswith('www.'):
                netloc = netloc[4:]
        
        return netloc
        
        return netloc
    
    except Exception as e:
        print(f"Error parsing {url}: {e}")
        return None

def extract_domain_preserve_case(url, keep_www=None):
    """Extract domain while preserving original case from URL"""
    if not url:
        return None
    
    # For case preservation, extract manually from original URL
    if url.startswith('//'):
        url = 'https:' + url
    elif not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    
    # Find domain part manually to preserve case
    import re
    # Match scheme://domain[:port]/path
    match = re.match(r'^https?://([^/:]+)(?::[0-9]+)?(?:/.*)?$', url, re.IGNORECASE)
    if match:
        domain = match.group(1)
        
        # Handle www prefix
        if keep_www is not None:
            if not keep_www and domain.startswith('www.'):
                domain = domain[4:]
        else:
            if domain.startswith('www.'):
                domain = domain[4:]
        
        return domain
    
    return extract_domain(url, keep_www)

# For backward compatibility, create default version
def extract_domain_original(url):
    """Original version for tests that expect www stripping"""
    return extract_domain(url, keep_www=False)

def is_private_or_local(host):
    """Check if host is localhost or private IP"""
    if host in ('localhost', '127.0.0.1', '::1'):
        return True
    
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private
    except ValueError:
        return False

# Additional helper functions
def get_base_domain(domain):
    """Extract base domain (remove subdomains)"""
    if not domain:
        return None
    
    # Skip IP addresses
    try:
        ipaddress.ip_address(domain.split(':')[0])
        return domain  # Return IP as-is
    except ValueError:
        pass
    
    parts = domain.split('.')
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return domain

def is_subdomain(domain):
    """Check if domain has subdomain"""
    if not domain:
        return False
    
    # Skip IPs
    try:
        ipaddress.ip_address(domain.split(':')[0])
        return False
    except:
        pass
    
    parts = domain.split('.')
    return len(parts) > 2