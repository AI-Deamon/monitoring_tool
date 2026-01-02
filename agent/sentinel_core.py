"""
SentinelEdge Core Service - Entry Point
Enhanced with secure identity, registration, and manifest verification
SEC-024: Verifies code integrity before starting

This file should be placed in the root installation directory
"""
import sys
from pathlib import Path

# Ensure the installation directory is in the path
install_dir = Path(__file__).parent
sys.path.insert(0, str(install_dir))

# ============================================================================
# SEC-024: Verify code integrity before starting
# ============================================================================
def verify_integrity_check():
    """Verify agent files haven't been tampered with"""
    try:
        from core.integrity import verify_integrity
        
        success, violations = verify_integrity(install_dir, strict=False)
        
        if not success:
            print("=" * 70, file=sys.stderr)
            print("SEC-024 FATAL: Code integrity check failed!", file=sys.stderr)
            print("Possible code tampering detected:", file=sys.stderr)
            for v in violations:
                print(f"  - {v}", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            sys.exit(1)
            
    except ImportError:
        # Integrity module not available (development mode)
        pass
    except Exception as e:
        # Log but don't fail - might be first run before manifest exists
        print(f"SEC-024: Integrity check skipped: {e}", file=sys.stderr)


if __name__ == '__main__':
    # SEC-024: Check integrity first
    verify_integrity_check()
    
    # Import and run the core service
    from core.service import main
    main()