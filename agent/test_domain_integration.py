"""
Integration tests for enhanced domain extraction in domain.py
Run: python test_domain_integration.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helper.domain import extract_domain_from_url_enhanced, get_base_domain, is_subdomain

def test_basic_domains():
    """Test standard domains"""
    assert extract_domain_from_url_enhanced('https://google.com') == 'google.com', "Failed: google.com"
    assert extract_domain_from_url_enhanced('https://www.google.com') == 'google.com', "Failed: www.google.com"
    assert extract_domain_from_url_enhanced('https://github.com/user/repo') == 'github.com', "Failed: github.com with path"
    assert extract_domain_from_url_enhanced('https://GITHUB.COM') == 'github.com', "Failed: uppercase domain"
    print("✅ Basic domains: PASS")

def test_subdomains():
    """Test subdomain handling"""
    assert extract_domain_from_url_enhanced('https://mail.google.com') == 'mail.google.com', "Failed: mail.google.com"
    assert extract_domain_from_url_enhanced('https://api.github.com') == 'api.github.com', "Failed: api.github.com"
    assert is_subdomain('mail.google.com') == True, "Failed: is_subdomain mail.google.com"
    assert is_subdomain('google.com') == False, "Failed: is_subdomain google.com"
    print("✅ Subdomains: PASS")

def test_ports():
    """Test port handling"""
    assert extract_domain_from_url_enhanced('http://localhost:3000') == 'localhost:3000', "Failed: localhost:3000"
    assert extract_domain_from_url_enhanced('http://localhost:8080/api') == 'localhost:8080', "Failed: localhost:8080/api"
    assert extract_domain_from_url_enhanced('https://example.com:443') == 'example.com', "Failed: example.com:443 (should strip)"
    assert extract_domain_from_url_enhanced('http://example.com:80') == 'example.com', "Failed: example.com:80 (should strip)"
    assert extract_domain_from_url_enhanced('https://example.com:8443') == 'example.com:8443', "Failed: example.com:8443 (non-standard port)"
    print("✅ Ports: PASS")

def test_ip_addresses():
    """Test IP address handling"""
    assert extract_domain_from_url_enhanced('http://192.168.1.100') == '192.168.1.100', "Failed: 192.168.1.100"
    assert extract_domain_from_url_enhanced('http://192.168.1.100:8080') == '192.168.1.100:8080', "Failed: 192.168.1.100:8080"
    assert extract_domain_from_url_enhanced('http://127.0.0.1:5000') == '127.0.0.1:5000', "Failed: 127.0.0.1:5000"
    assert extract_domain_from_url_enhanced('http://10.0.0.1') == '10.0.0.1', "Failed: 10.0.0.1"
    print("✅ IP addresses: PASS")

def test_special_protocols():
    """Test special protocol filtering"""
    assert extract_domain_from_url_enhanced('about:blank') == None, "Failed: about:blank should be None"
    assert extract_domain_from_url_enhanced('chrome://settings') == None, "Failed: chrome://settings should be None"
    assert extract_domain_from_url_enhanced('file:///C:/test.pdf') == None, "Failed: file:// should be None"
    assert extract_domain_from_url_enhanced('edge://settings') == None, "Failed: edge://settings should be None"
    assert extract_domain_from_url_enhanced('brave://settings') == None, "Failed: brave://settings should be None"
    assert extract_domain_from_url_enhanced('javascript:void(0)') == None, "Failed: javascript: should be None"
    print("✅ Special protocols: PASS")

def test_edge_cases():
    """Test edge cases"""
    assert extract_domain_from_url_enhanced('') == None, "Failed: empty string"
    assert extract_domain_from_url_enhanced(None) == None, "Failed: None input"
    assert extract_domain_from_url_enhanced('//example.com') == 'example.com', "Failed: protocol-relative URL"
    assert extract_domain_from_url_enhanced('example.com') == 'example.com', "Failed: no scheme"
    assert extract_domain_from_url_enhanced('example.com/path') == 'example.com', "Failed: no scheme with path"
    # User:pass format
    assert extract_domain_from_url_enhanced('http://user:pass@example.com') == 'example.com', "Failed: user:pass format"
    print("✅ Edge cases: PASS")

def test_base_domain():
    """Test base domain extraction"""
    assert get_base_domain('mail.google.com') == 'google.com', "Failed: get_base_domain mail.google.com"
    assert get_base_domain('api.github.com') == 'github.com', "Failed: get_base_domain api.github.com"
    assert get_base_domain('google.com') == 'google.com', "Failed: get_base_domain google.com"
    assert get_base_domain('192.168.1.1') == '192.168.1.1', "Failed: get_base_domain IP"
    assert get_base_domain('sub.sub.domain.com') == 'domain.com', "Failed: get_base_domain deep subdomain"
    print("✅ Base domain extraction: PASS")

def test_www_handling():
    """Test www prefix handling"""
    # Default behavior: strip www
    assert extract_domain_from_url_enhanced('https://www.google.com') == 'google.com', "Failed: default strip www"
    # Explicit keep_www=True
    assert extract_domain_from_url_enhanced('https://www.google.com', keep_www=True) == 'www.google.com', "Failed: keep_www=True"
    # Explicit keep_www=False
    assert extract_domain_from_url_enhanced('https://www.google.com', keep_www=False) == 'google.com', "Failed: keep_www=False"
    print("✅ WWW handling: PASS")


def test_title_extraction_bug_fix():
    """Test the critical bug fix: x.com from Cortex XDR"""
    import ctypes
    import sys
    
    # Mock ctypes.windll for Linux compatibility
    class MockWindll:
        class user32:
            pass
        class kernel32:
            pass
    
    if not hasattr(ctypes, 'windll'):
        ctypes.windll = MockWindll()
    
    from helper.domain import ActiveDomainTracker
    
    # Create tracker with mocked Windows APIs
    try:
        tracker = ActiveDomainTracker()
    except Exception:
        # If full initialization fails, create a mock instance just for method testing
        class MockTracker:
            pass
        tracker = MockTracker()
        # Manually bind the method for testing
        import types
        from helper.domain import ActiveDomainTracker as AT
        tracker._extract_domain_from_title = types.MethodType(
            AT._extract_domain_from_title, tracker
        )
        tracker._is_valid_extracted_domain = types.MethodType(
            AT._is_valid_extracted_domain, tracker
        )
    
    # CRITICAL BUG: This used to extract "x.com" incorrectly
    result = tracker._extract_domain_from_title("Use the interface • Cortex XDR")
    assert result is None, f"CRITICAL BUG: Expected None, got '{result}' from 'Cortex XDR'"
    
    # More false positive tests
    result = tracker._extract_domain_from_title("Palo Alto Networks - Security Dashboard")
    assert result is None, f"Expected None, got '{result}' from 'Palo Alto'"
    
    result = tracker._extract_domain_from_title("Index Page - My Application")
    assert result is None, f"Expected None, got '{result}' from 'Index Page'"
    
    # Valid domain extraction tests
    result = tracker._extract_domain_from_title("Welcome to github.com")
    assert result == "github.com", f"Expected github.com, got '{result}'"
    
    # Use YouTube which IS in known_sites
    result = tracker._extract_domain_from_title("Funny Video - YouTube")
    assert result == "youtube.com", f"Expected youtube.com (known site), got '{result}'"
    
    result = tracker._extract_domain_from_title("Check out example.com for more")
    assert result == "example.com", f"Expected example.com, got '{result}'"
    
    result = tracker._extract_domain_from_title("ChatGPT - OpenAI")
    assert result == "chatgpt.com", f"Expected chatgpt.com (known site), got '{result}'"
    
    # Test Gmail which IS in known_sites
    result = tracker._extract_domain_from_title("Inbox (5) - Gmail")
    assert result == "mail.google.com", f"Expected mail.google.com (known site), got '{result}'"
    
    print("✅ Title extraction bug fix: PASS")

if __name__ == '__main__':
    print("=" * 60)
    print("Running domain.py integration tests...")
    print("=" * 60)
    
    try:
        test_basic_domains()
        test_subdomains()
        test_ports()
        test_ip_addresses()
        test_special_protocols()
        test_edge_cases()
        test_base_domain()
        test_www_handling()
        test_title_extraction_bug_fix()
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except ImportError as e:
        print(f"\n❌ IMPORT ERROR: {e}")
        print("Make sure you're running from the agent directory")
        sys.exit(1)
