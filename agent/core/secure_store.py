"""
Secure Storage Module - Hybrid DPAPI + Cryptography Implementation
SEC-004 COMPLIANT: Uses Windows built-in encryption (DPAPI) with cryptography fallback

Priority:
1. Windows DPAPI (zero dependencies, built-in Windows encryption)
2. cryptography library (if DPAPI unavailable)
3. FAIL - no insecure fallback

SEC-008: Machine-level protection (DPAPI or unique salt for cryptography)
"""
import os
import hashlib
import json
import logging
import secrets
import sys
import ctypes
from ctypes import wintypes
from typing import Optional
from pathlib import Path
import base64
import platform

logger = logging.getLogger(__name__)

# ============================================================================
# DPAPI - Windows Built-in Encryption (ZERO DEPENDENCIES!)
# ============================================================================
HAS_DPAPI = False
crypt32 = None
kernel32 = None

try:
    if platform.system() == 'Windows':
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ('cbData', wintypes.DWORD),
                ('pbData', ctypes.POINTER(ctypes.c_char))
            ]
        
        # Test DPAPI availability
        test_data = b"dpapi_test"
        buffer_in = ctypes.create_string_buffer(test_data)
        blob_in = DATA_BLOB(len(test_data), buffer_in)
        blob_out = DATA_BLOB()
        
        if crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0x4, ctypes.byref(blob_out)
        ):
            kernel32.LocalFree(blob_out.pbData)
            HAS_DPAPI = True
            logger.info("SEC-004: Windows DPAPI available (zero dependencies)")
        
except Exception as e:
    logger.debug(f"DPAPI not available: {e}")
    HAS_DPAPI = False

# ============================================================================
# Cryptography Library - Fallback
# ============================================================================
HAS_CRYPTO = False
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
    logger.debug("cryptography library available as fallback")
except ImportError:
    pass


def dpapi_encrypt(data: bytes) -> bytes:
    """Encrypt using Windows DPAPI (machine-level)"""
    if not HAS_DPAPI:
        raise RuntimeError("DPAPI not available")
    
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ('cbData', wintypes.DWORD),
            ('pbData', ctypes.POINTER(ctypes.c_char))
        ]
    
    buffer_in = ctypes.create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), buffer_in)
    blob_out = DATA_BLOB()
    
    # CRYPTPROTECT_LOCAL_MACHINE flag (0x4) = machine-level encryption
    # Any process on this machine can decrypt
    if crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,  # Description
        None,  # Optional entropy
        None,  # Reserved
        None,  # Prompt struct
        0x4,   # CRYPTPROTECT_LOCAL_MACHINE
        ctypes.byref(blob_out)
    ):
        try:
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return encrypted
        finally:
            kernel32.LocalFree(blob_out.pbData)
    else:
        error_code = ctypes.get_last_error()
        raise RuntimeError(f"DPAPI encryption failed (error {error_code})")


def dpapi_decrypt(encrypted: bytes) -> bytes:
    """Decrypt using Windows DPAPI"""
    if not HAS_DPAPI:
        raise RuntimeError("DPAPI not available")
    
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ('cbData', wintypes.DWORD),
            ('pbData', ctypes.POINTER(ctypes.c_char))
        ]
    
    buffer_in = ctypes.create_string_buffer(encrypted)
    blob_in = DATA_BLOB(len(encrypted), buffer_in)
    blob_out = DATA_BLOB()
    
    if crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0x4,  # CRYPTPROTECT_LOCAL_MACHINE
        ctypes.byref(blob_out)
    ):
        try:
            decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return decrypted
        finally:
            kernel32.LocalFree(blob_out.pbData)
    else:
        error_code = ctypes.get_last_error()
        raise RuntimeError(f"DPAPI decryption failed (error {error_code})")


class DPAPIStorage:
    """Windows DPAPI-based secure storage - ZERO external dependencies"""
    
    def __init__(self):
        program_data = os.environ.get('ProgramData', r'C:\ProgramData')
        self.token_file = Path(program_data) / 'SentinelEdge' / 'token.dpapi'
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info("SEC-004: Initialized DPAPI storage (Windows built-in encryption)")
    
    def encrypt(self, value: str) -> bytes:
        """Encrypt using DPAPI"""
        return dpapi_encrypt(value.encode('utf-8'))
    
    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt using DPAPI"""
        return dpapi_decrypt(encrypted_data).decode('utf-8')
    
    def store_token_securely(self, token: str, config_path: str = None) -> bool:
        """Store API token with DPAPI encryption"""
        try:
            if not token:
                logger.error("Cannot store empty token")
                return False
            
            encrypted = self.encrypt(token)
            self.token_file.write_bytes(encrypted)
            
            # Verify by reading back
            test_read = self.token_file.read_bytes()
            test_decrypt = self.decrypt(test_read)
            
            if test_decrypt != token:
                logger.error("Token verification failed!")
                return False
            
            logger.info(f"Token stored securely with DPAPI: {self.token_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store token: {e}", exc_info=True)
            return False
    
    def load_token_securely(self, config_path: str = None) -> Optional[str]:
        """Load and decrypt API token"""
        try:
            if not self.token_file.exists():
                logger.debug("No DPAPI token file found")
                return None
            
            encrypted = self.token_file.read_bytes()
            token = self.decrypt(encrypted)
            logger.debug(f"Token loaded from DPAPI: {token[:20]}...")
            return token
            
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return None
    
    def clear_secure_token(self, config_path: str = None) -> bool:
        """Delete encrypted token file"""
        try:
            if self.token_file.exists():
                self.token_file.unlink()
                logger.info("DPAPI token file deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete token: {e}")
            return False


class CryptoStorage:
    """Cryptography library-based secure storage (fallback)"""
    
    def __init__(self):
        program_data = os.environ.get('ProgramData', r'C:\ProgramData')
        self.token_file = Path(program_data) / 'SentinelEdge' / 'token.enc'
        self.salt_file = Path(program_data) / 'SentinelEdge' / 'token.salt'
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._cipher = self._create_cipher()
        logger.info("SEC-004: Initialized cryptography storage (Fernet encryption)")
    
    def _get_machine_guid(self) -> str:
        """Get Windows machine GUID"""
        try:
            if platform.system() == 'Windows':
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r'SOFTWARE\Microsoft\Cryptography',
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                )
                guid, _ = winreg.QueryValueEx(key, 'MachineGuid')
                winreg.CloseKey(key)
                return guid
        except Exception:
            pass
        
        # Fallback
        import socket
        return socket.gethostname()
    
    def _create_cipher(self):
        """Create Fernet cipher with machine-derived key + unique salt"""
        machine_guid = self._get_machine_guid()
        
        # SEC-008: Generate or load unique salt
        if self.salt_file.exists():
            salt = self.salt_file.read_bytes()
        else:
            salt = secrets.token_bytes(16)
            self.salt_file.write_bytes(salt)
            logger.info("SEC-008: Generated new unique salt")
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_guid.encode()))
        return Fernet(key)
    
    def store_token_securely(self, token: str, config_path: str = None) -> bool:
        """Store API token with Fernet encryption"""
        try:
            if not token:
                return False
            
            encrypted = self._cipher.encrypt(token.encode('utf-8'))
            self.token_file.write_bytes(encrypted)
            
            # Verify
            test = self._cipher.decrypt(self.token_file.read_bytes()).decode('utf-8')
            if test != token:
                return False
            
            logger.info(f"Token stored with cryptography: {self.token_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store token: {e}")
            return False
    
    def load_token_securely(self, config_path: str = None) -> Optional[str]:
        """Load and decrypt API token"""
        try:
            if not self.token_file.exists():
                return None
            
            encrypted = self.token_file.read_bytes()
            return self._cipher.decrypt(encrypted).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return None
    
    def clear_secure_token(self, config_path: str = None) -> bool:
        """Delete encrypted token file"""
        try:
            for f in [self.token_file, self.salt_file]:
                if f.exists():
                    f.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to delete token: {e}")
            return False


class SecureStorage:
    """
    Hybrid Secure Storage - SEC-004 Compliant
    
    Priority:
    1. Windows DPAPI (zero dependencies, machine-level encryption)
    2. cryptography library (Fernet encryption with unique salt)
    3. FAIL (no insecure fallback allowed)
    """
    
    def __init__(self):
        if HAS_DPAPI:
            logger.info("SEC-004: Using Windows DPAPI (preferred, zero dependencies)")
            self._impl = DPAPIStorage()
            self._method = "DPAPI"
        elif HAS_CRYPTO:
            logger.warning("SEC-004: DPAPI unavailable, using cryptography library")
            self._impl = CryptoStorage()
            self._method = "cryptography"
        else:
            # FAIL - no insecure fallback
            print("=" * 70, file=sys.stderr)
            print("SEC-004 FATAL: No encryption available!", file=sys.stderr)
            print("", file=sys.stderr)
            print("Windows DPAPI: Not available (non-Windows or ctypes error)", file=sys.stderr)
            print("cryptography:  Not installed", file=sys.stderr)
            print("", file=sys.stderr)
            print("SentinelEdge CANNOT RUN without secure encryption.", file=sys.stderr)
            print("", file=sys.stderr)
            print("FIX: pip install cryptography", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            raise RuntimeError("SEC-004: No encryption method available")
    
    def store_token_securely(self, token: str, config_path: str = None) -> bool:
        """Store API token securely"""
        return self._impl.store_token_securely(token, config_path)
    
    def load_token_securely(self, config_path: str = None) -> Optional[str]:
        """Load API token securely"""
        return self._impl.load_token_securely(config_path)
    
    def clear_secure_token(self, config_path: str = None) -> bool:
        """Clear stored token"""
        return self._impl.clear_secure_token(config_path)
    
    @property
    def encryption_method(self) -> str:
        """Return current encryption method"""
        return self._method


# ============================================================================
# Global instance and factory
# ============================================================================
_secure_storage: Optional[SecureStorage] = None


def get_secure_storage() -> SecureStorage:
    """Get or create secure storage instance"""
    global _secure_storage
    if _secure_storage is None:
        _secure_storage = SecureStorage()
    return _secure_storage


# ============================================================================
# Test if run directly
# ============================================================================
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    print("Testing SecureStorage...")
    print(f"DPAPI available: {HAS_DPAPI}")
    print(f"cryptography available: {HAS_CRYPTO}")
    
    storage = get_secure_storage()
    print(f"Using: {storage.encryption_method}")
    
    # Test encrypt/decrypt
    test_token = "test_api_token_12345"
    storage.store_token_securely(test_token)
    loaded = storage.load_token_securely()
    
    if loaded == test_token:
        print("✅ Encryption test PASSED")
    else:
        print("❌ Encryption test FAILED")
    
    storage.clear_secure_token()
    print("Done!")
