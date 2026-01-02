#!/bin/bash
#
# SentinelEdge Agent - Deployment Package Preparation Script
# Run this on your development machine to create a deployment-ready folder
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="2.1.0"
BUILD_DATE=$(date +%Y%m%d)
PACKAGE_NAME="SentinelEdge-Agent-${VERSION}"
OUTPUT_DIR="../deploy"
TEMP_PKG="${OUTPUT_DIR}/${PACKAGE_NAME}"

echo ""
echo "========================================================================"
echo "  SentinelEdge Agent - Deployment Package Preparation"
echo "========================================================================"
echo ""
echo "Version: ${VERSION}"
echo "Package: ${PACKAGE_NAME}"
echo ""

# ============================================================================
# STEP 1: Check Required Files
# ============================================================================
echo "[INFO] Checking required files..."

MISSING=0

check_file() {
    if [ ! -f "$1" ] && [ ! -d "$1" ]; then
        echo "[FAIL] Missing: $1"
        MISSING=1
    fi
}

check_file "install.bat"
check_file "uninstall.bat"
check_file "update.bat"
check_file "sentinel_core.py"
check_file "sentinel_helper.py"
check_file "core/service.py"
check_file "helper/main.py"
check_file "nssm/win64/nssm.exe"

if [ "$MISSING" == "1" ]; then
    echo ""
    echo "[ERROR] Some required files are missing!"
    exit 1
fi

echo "[OK] All required files present"
echo ""

# ============================================================================
# STEP 2: Check Python Bundle
# ============================================================================
echo "[INFO] Checking Python bundle..."

if [ ! -d "python313" ]; then
    echo ""
    echo "[WARN] Python 3.13 bundle not found!"
    echo "[INFO] The Python bundle needs to be created on a Windows machine."
    echo "[INFO] Run create_python_bundle.bat on Windows first."
    echo ""
    read -p "Continue without Python bundle? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "[OK] Python 3.13 bundle found"
fi
echo ""

# ============================================================================
# STEP 3: Clean and Create Output Directory
# ============================================================================
echo "[INFO] Preparing output directory..."

mkdir -p "$OUTPUT_DIR"
rm -rf "$TEMP_PKG"
mkdir -p "$TEMP_PKG"

echo "[OK] Output directory: ${OUTPUT_DIR}"
echo ""

# ============================================================================
# STEP 4: Copy Files to Package
# ============================================================================
echo "[INFO] Copying files to package..."

# Main scripts
echo "  - Main scripts..."
cp -f install.bat "$TEMP_PKG/"
cp -f uninstall.bat "$TEMP_PKG/"
cp -f update.bat "$TEMP_PKG/"
cp -f view_logs.bat "$TEMP_PKG/"
cp -f quick_restart.bat "$TEMP_PKG/"
cp -f harden_install.py "$TEMP_PKG/"
cp -f build_package.bat "$TEMP_PKG/" 2>/dev/null || true

# Entry point scripts
echo "  - Entry points..."
cp -f sentinel_core.py "$TEMP_PKG/"
cp -f sentinel_helper.py "$TEMP_PKG/"

# Core module
echo "  - Core module..."
mkdir -p "$TEMP_PKG/core"
cp -f core/*.py "$TEMP_PKG/core/"

# Helper module
echo "  - Helper module..."
mkdir -p "$TEMP_PKG/helper"
cp -f helper/*.py "$TEMP_PKG/helper/"

# NSSM (service manager)
echo "  - NSSM service manager..."
cp -rf nssm "$TEMP_PKG/"

# Python bundle (if exists)
if [ -d "python313" ]; then
    echo "  - Python 3.13 bundle (this may take a moment)..."
    cp -rf python313 "$TEMP_PKG/"
fi

# Documentation
echo "  - Documentation..."
cp -f README.md "$TEMP_PKG/" 2>/dev/null || true
cp -f INSTALL_INSTRUCTIONS.md "$TEMP_PKG/" 2>/dev/null || true

echo "[OK] Files copied"
echo ""

# ============================================================================
# STEP 5: Remove Unnecessary Files
# ============================================================================
echo "[INFO] Cleaning package..."

# Remove __pycache__ directories
find "$TEMP_PKG" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Remove .pyc files (we'll compile on install)
find "$TEMP_PKG" -name "*.pyc" -delete 2>/dev/null || true

# Remove test files
find "$TEMP_PKG" -name "test_*.py" -delete 2>/dev/null || true

# Remove .git directory if present
rm -rf "$TEMP_PKG/.git" 2>/dev/null || true

# Convert line endings to Windows format
echo "[INFO] Converting line endings to Windows format..."
find "$TEMP_PKG" -name "*.bat" -exec sed -i 's/$/\r/' {} \; 2>/dev/null || true

echo "[OK] Package cleaned"
echo ""

# ============================================================================
# STEP 6: Create VERSION File
# ============================================================================
echo "[INFO] Creating version file..."

cat > "$TEMP_PKG/VERSION.txt" << EOF
SentinelEdge Agent
Version: ${VERSION}
Build Date: ${BUILD_DATE}

Installation:
  1. Extract all files
  2. Right-click install.bat, Run as Administrator
  3. Enter server URL and registration secret

Requirements:
  - Windows 10/11 (x64)
  - Administrator privileges
  - Network access to server
EOF

echo "[OK] Version file created"
echo ""

# ============================================================================
# STEP 7: Create ZIP Package
# ============================================================================
echo "[INFO] Creating ZIP package..."

ZIP_FILE="${OUTPUT_DIR}/${PACKAGE_NAME}.zip"
rm -f "$ZIP_FILE" 2>/dev/null || true

if command -v zip &> /dev/null; then
    cd "$OUTPUT_DIR"
    zip -rq "${PACKAGE_NAME}.zip" "${PACKAGE_NAME}/"
    cd "$SCRIPT_DIR"
    
    ZIP_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
    echo "[OK] ZIP package created: ${ZIP_FILE} (${ZIP_SIZE})"
else
    echo "[WARN] zip command not available, using tar..."
    cd "$OUTPUT_DIR"
    tar -czf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}/"
    cd "$SCRIPT_DIR"
    echo "[OK] TAR package created: ${OUTPUT_DIR}/${PACKAGE_NAME}.tar.gz"
fi

echo ""

# ============================================================================
# STEP 8: Summary
# ============================================================================
echo "========================================================================"
echo "  Deployment Package Ready!"
echo "========================================================================"
echo ""
echo "  Package Name:      ${PACKAGE_NAME}"
echo "  Package Location:  ${OUTPUT_DIR}/"

if [ -f "$ZIP_FILE" ]; then
    echo "  ZIP File:          ${PACKAGE_NAME}.zip"
fi
echo "  Folder:            ${PACKAGE_NAME}/"
echo ""
echo "  Contents:"
echo "    - install.bat      (Main installer)"
echo "    - uninstall.bat    (Clean removal)"
echo "    - update.bat       (In-place update)"
echo "    - sentinel_core.py (Core service entry)"
echo "    - sentinel_helper.py (Helper entry)"
echo "    - core/            (Core module)"
echo "    - helper/          (Helper module)"
echo "    - nssm/            (Service manager)"
if [ -d "$TEMP_PKG/python313" ]; then
    echo "    - python313/       (Bundled Python 3.13)"
fi
echo ""
echo "========================================================================"
echo "  Next Steps"
echo "========================================================================"
echo ""
echo "  1. Copy ${OUTPUT_DIR}/${PACKAGE_NAME}.zip to Windows machine"
echo "  2. Extract all files"
echo "  3. Run install.bat as Administrator"
echo ""
echo "========================================================================"
echo ""
