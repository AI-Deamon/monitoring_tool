"""
EOL Lifecycle Scanning Engine
=============================
Server-side module for evaluating software lifecycle status.

Responsibilities:
1. Sync EOL data from endoflife.date API into local software_lifecycle table
2. Evaluate each agent's OS + installed apps against lifecycle records
3. Cache results in asset_lifecycle_status for dashboard consumption

Usage:
    from eol_engine import sync_lifecycle_data, evaluate_fleet_lifecycle
    sync_lifecycle_data()         # Pull latest EOL data
    evaluate_fleet_lifecycle()    # Re-evaluate all agents
"""

import logging
import re
import time
from datetime import datetime, timezone, timedelta

import requests
from extensions import db

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION: Products to track from endoflife.date
# ============================================================

TRACKED_PRODUCTS = {
    # === OPERATING SYSTEMS ===
    'windows': {
        'display_name': 'Windows OS',
        'match_type': 'os',
        'risk_weight': 50,       # Critical — EOL OS = highest risk
    },
    
    # === PRODUCTIVITY SUITES ===
    'office': {
        'display_name': 'Microsoft Office',
        'match_type': 'app',
        'patterns': ['Microsoft Office', 'Microsoft 365'],
        'risk_weight': 30,
    },
    'adobe-acrobat': {
        'display_name': 'Adobe Acrobat',
        'match_type': 'app',
        'patterns': ['Adobe Acrobat', 'Adobe Reader'],
        'risk_weight': 25,
    },
    'visualstudio': {
        'display_name': 'Visual Studio',
        'match_type': 'app',
        'patterns': ['Visual Studio'],
        'exclude_patterns': ['Visual Studio Code', 'VS Code'],
        'risk_weight': 20,
    },
    'vscode': {
        'display_name': 'Visual Studio Code',
        'match_type': 'app',
        'patterns': ['Visual Studio Code', 'VS Code'],
        'risk_weight': 15,
    },
    
    # === BROWSERS ===
    'chrome': {
        'display_name': 'Google Chrome',
        'match_type': 'app',
        'patterns': ['Google Chrome'],
        'risk_weight': 20,
    },
    'firefox': {
        'display_name': 'Mozilla Firefox',
        'match_type': 'app',
        'patterns': ['Mozilla Firefox'],
        'risk_weight': 20,
    },
    'msedge': {
        'display_name': 'Microsoft Edge',
        'match_type': 'app',
        'patterns': ['Microsoft Edge'],
        'risk_weight': 15,
    },
    
    # === RUNTIMES & FRAMEWORKS ===
    'java': {
        'display_name': 'Java Runtime',
        'match_type': 'app',
        'patterns': ['Java', 'JRE', 'OpenJDK', 'Adoptium', 'Temurin', 'Oracle Java'],
        'exclude_patterns': ['JavaScript'],
        'risk_weight': 35,
    },
    'dotnet': {
        'display_name': '.NET Framework',
        'match_type': 'app',
        'patterns': ['.NET Framework', 'Microsoft .NET'],
        'risk_weight': 25,
    },
    'dotnet-core': {
        'display_name': '.NET (Core)',
        'match_type': 'app',
        'patterns': ['.NET ', 'Microsoft .NET Runtime'],
        'exclude_patterns': ['.NET Framework'],
        'risk_weight': 20,
    },
    'nodejs': {
        'display_name': 'Node.js',
        'match_type': 'app',
        'patterns': ['Node.js', 'NodeJS'],
        'risk_weight': 20,
    },
    'python': {
        'display_name': 'Python',
        'match_type': 'app',
        'patterns': ['Python'],
        'exclude_patterns': ['Python Launcher'],
        'risk_weight': 15,
    },
    
    # === COLLABORATION ===
    'zoom': {
        'display_name': 'Zoom',
        'match_type': 'app',
        'patterns': ['Zoom'],
        'risk_weight': 15,
    },
    'slack': {
        'display_name': 'Slack',
        'match_type': 'app',
        'patterns': ['Slack'],
        'risk_weight': 15,
    },
    'teams': {
        'display_name': 'Microsoft Teams',
        'match_type': 'app',
        'patterns': ['Microsoft Teams', 'Teams'],
        'exclude_patterns': ['Teams Machine-Wide'],
        'risk_weight': 15,
    },
    
    # === DEVELOPER TOOLS ===
    'git': {
        'display_name': 'Git',
        'match_type': 'app',
        'patterns': ['Git for Windows', 'Git'],
        'exclude_patterns': ['GitHub', 'GitLab'],
        'risk_weight': 20,
    },
    'openssl': {
        'display_name': 'OpenSSL',
        'match_type': 'app',
        'patterns': ['OpenSSL'],
        'risk_weight': 40,
    },
    
    # === INFRASTRUCTURE & DEVOPS ===
    'go': {
        'display_name': 'Go',
        'match_type': 'app',
        'patterns': ['Go Programming Language', 'Golang'],
        'risk_weight': 15,
    },
    'rust': {
        'display_name': 'Rust',
        'match_type': 'app',
        'patterns': ['Rust', 'Rustup'],
        'exclude_patterns': ['Rust remover', 'Anti-Rust'],
        'risk_weight': 10,
    },
    'docker-engine': {
        'display_name': 'Docker',
        'match_type': 'app',
        'patterns': ['Docker Desktop', 'Docker Engine'],
        'risk_weight': 25,
    },
    'kubernetes': {
        'display_name': 'Kubernetes',
        'match_type': 'app',
        'patterns': ['kubectl', 'Kubernetes'],
        'risk_weight': 20,
    },
    'terraform': {
        'display_name': 'Terraform',
        'match_type': 'app',
        'patterns': ['Terraform', 'HashiCorp Terraform'],
        'risk_weight': 20,
    },
}

# ============================================================
# CLI TOOLS TRACKING - Additional products tracked via CLI
# ============================================================

CLI_TOOL_PRODUCTS = {
    'nodejs': {
        'display_name': 'Node.js (CLI)',
        'cli_names': ['node', 'nodejs'],
        'risk_weight': 20,
    },
    'python': {
        'display_name': 'Python (CLI)',
        'cli_names': ['python', 'python3', 'py'],
        'risk_weight': 15,
    },
    'git': {
        'display_name': 'Git (CLI)',
        'cli_names': ['git'],
        'risk_weight': 20,
    },
    'dotnet': {
        'display_name': '.NET SDK (CLI)',
        'cli_names': ['dotnet'],
        'risk_weight': 25,
    },
    'java': {
        'display_name': 'Java (CLI)',
        'cli_names': ['java', 'javac'],
        'risk_weight': 35,
    },
    'openssl': {
        'display_name': 'OpenSSL (CLI)',
        'cli_names': ['openssl'],
        'risk_weight': 40,
    },
    'go': {
        'display_name': 'Go (CLI)',
        'cli_names': ['go'],
        'risk_weight': 15,
    },
    'rust': {
        'display_name': 'Rust (CLI)',
        'cli_names': ['rustc', 'cargo'],
        'risk_weight': 10,
    },
    'docker-engine': {
        'display_name': 'Docker (CLI)',
        'cli_names': ['docker'],
        'risk_weight': 25,
    },
    'kubernetes': {
        'display_name': 'kubectl (CLI)',
        'cli_names': ['kubectl'],
        'risk_weight': 20,
    },
    'terraform': {
        'display_name': 'Terraform (CLI)',
        'cli_names': ['terraform'],
        'risk_weight': 20,
    },
}

APPROACHING_EOL_DAYS = 90  # Flag as "approaching_eol" within this window


# ============================================================
# 1. DATA SYNC — Pull from endoflife.date API
# ============================================================

def sync_lifecycle_data(products=None):
    """
    Fetch latest EOL data from endoflife.date and upsert into software_lifecycle.
    
    Args:
        products: List of product keys to sync, or None for all tracked products.
    
    Returns:
        dict with counts of synced/updated records per product.
    """
    import server_models
    
    target_products = products or list(TRACKED_PRODUCTS.keys())
    results = {}
    
    for product_key in target_products:
        if product_key not in TRACKED_PRODUCTS:
            logger.warning(f"[EOL] Unknown product key: {product_key}")
            continue
            
        try:
            url = f'https://endoflife.date/api/{product_key}.json'

            # H-18 FIX: retry with exponential backoff on rate limit (429).
            # ~23 products are synced back-to-back with no inter-request delay,
            # so a single 429 previously aborted that product's sync silently.
            max_retries = 3
            retry_delay = 1  # seconds
            cycles = None
            for attempt in range(max_retries):
                try:
                    resp = requests.get(url, timeout=15)
                    if resp.status_code == 429:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            logger.warning(f"[EOL] Rate limited on '{product_key}', waiting {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"[EOL] Rate limit exceeded for '{product_key}' after {max_retries} attempts")
                            results[product_key] = 'error: rate limit exceeded'
                            break
                    resp.raise_for_status()
                    cycles = resp.json()
                    break
                except requests.Timeout:
                    if attempt < max_retries - 1:
                        logger.warning(f"[EOL] Timeout on '{product_key}', retrying...")
                        continue
                    raise
            else:
                continue
            if cycles is None:
                continue

            synced = 0
            for cycle_data in cycles:
                cycle_id = cycle_data.get('cycle', '')
                
                # Parse dates safely
                eol_date = _parse_date(cycle_data.get('eol'))
                eos_date = _parse_date(cycle_data.get('support'))
                release_date = _parse_date(cycle_data.get('releaseDate'))
                
                # Upsert: update if exists, insert if new
                existing = server_models.SoftwareLifecycle.query.filter_by(
                    product_name=product_key, cycle=cycle_id
                ).first()
                
                if existing:
                    existing.release_label = cycle_data.get('releaseLabel', cycle_id)
                    existing.release_date = release_date
                    existing.eol_date = eol_date
                    existing.eos_date = eos_date
                    existing.is_lts = cycle_data.get('lts', False)
                    existing.latest_version = cycle_data.get('latest', '')
                    existing.reference_url = cycle_data.get('link', '')
                    existing.synced_at = datetime.now(timezone.utc)
                else:
                    record = server_models.SoftwareLifecycle(
                        product_name=product_key,
                        cycle=cycle_id,
                        release_label=cycle_data.get('releaseLabel', cycle_id),
                        release_date=release_date,
                        eol_date=eol_date,
                        eos_date=eos_date,
                        is_lts=cycle_data.get('lts', False),
                        latest_version=cycle_data.get('latest', ''),
                        reference_url=cycle_data.get('link', ''),
                        source='endoflife.date',
                        synced_at=datetime.now(timezone.utc)
                    )
                    db.session.add(record)
                synced += 1
            
            db.session.commit()
            results[product_key] = synced
            logger.info(f"[EOL] Synced {synced} cycles for '{product_key}'")
            
        except requests.RequestException as e:
            logger.error(f"[EOL] Failed to sync '{product_key}': {e}")
            results[product_key] = f'error: {e}'
        except Exception as e:
            db.session.rollback()
            logger.error(f"[EOL] Unexpected error syncing '{product_key}': {e}")
            results[product_key] = f'error: {e}'
    
    return results


# ============================================================
# 2. VERSION PARSING — Semantic comparison, not strings
# ============================================================

def _parse_date(value):
    """Parse date with robust error handling"""
    if value is None or isinstance(value, bool):
        return None
        
    try:
        value_str = str(value).strip()
        if not value_str or value_str.lower() in ['true', 'false', 'none']:
            return None
            
        return datetime.strptime(value_str, '%Y-%m-%d').date()
    except Exception as e:
        logger.debug(f"Date parsing failed: {value} - {e}")
        return None


def parse_version_tuple(version_str):
    """
    Parse version string into semantic version tuple
    Handles: "10.0.19045", "120.0.6099.130", "115", "22H2", "2019", "v1.2.3"
    Returns tuple of ints, or None if unparseable.
    """
    if not version_str:
        return None
        
    v = str(version_str).strip().lstrip('vV')
    
    # Handle Windows version labels like "22H2"
    h_match = re.match(r'^(\d{2})H(\d)$', v, re.IGNORECASE)
    if h_match:
        return (int(h_match.group(1)), int(h_match.group(2)))
        
    # Parse semantic version
    parts = re.findall(r'\d+', v)
    if not parts:
        return None
        
    # Limit to maximum 4 parts for consistency
    return tuple(int(p) for p in parts[:4])


def version_compare(installed, reference):
    """
    Compare two version strings.
    Returns:
        -1 if installed < reference
         0 if installed == reference
         1 if installed > reference
        None if comparison impossible
    """
    v_inst = parse_version_tuple(installed)
    v_ref = parse_version_tuple(reference)
    
    if v_inst is None or v_ref is None:
        return None
    
    # Pad shorter tuple with zeros for fair comparison
    max_len = max(len(v_inst), len(v_ref))
    v_inst = v_inst + (0,) * (max_len - len(v_inst))
    v_ref = v_ref + (0,) * (max_len - len(v_ref))
    
    if v_inst < v_ref:
        return -1
    elif v_inst == v_ref:
        return 0
    else:
        return 1


# ============================================================
# 3. LIFECYCLE MATCHING — OS and Application evaluation
# ============================================================

def _match_windows_lifecycle(asset_info):
    """
    Match a Windows OS build to a lifecycle cycle.
    Uses os_build (e.g. "10.0.19045") and os_version (e.g. "22H2").
    
    Returns dict: {status, matched_cycle, eol_date, severity, risk_score}
    """
    import server_models
    
    if not asset_info:
        return None
    
    os_name = asset_info.os_name or ''
    os_version = asset_info.os_version or ''
    os_build = asset_info.os_build or ''
    
    # Determine Windows major version
    if '11' in os_name:
        win_major = '11'
    elif '10' in os_name:
        win_major = '10'
    else:
        return None  # Not a tracked Windows version
    
    # Extract version label (e.g. "22H2", "23H2")
    version_label = ''
    h_match = re.search(r'(\d{2}H\d)', os_version, re.IGNORECASE)
    if h_match:
        version_label = h_match.group(1).lower()
    
    # Query lifecycle records for this Windows version
    cycles = server_models.SoftwareLifecycle.query.filter_by(
        product_name='windows'
    ).all()
    
    if not cycles:
        return {'status': 'unknown', 'matched_cycle': None, 'eol_date': None,
                'severity': 'info', 'risk_score': 0}
    
    # Try to find exact match by cycle ID
    best_match = None
    for cycle in cycles:
        cycle_id = cycle.cycle.lower()
        
        # Match pattern: "10-22h2", "11-23h2-e", "11-23h2-w"
        if f'{win_major}-{version_label}' in cycle_id:
            # Prefer non-LTSC, non-IoT variants
            if best_match is None:
                best_match = cycle
            elif '-e' not in cycle_id and '-lts' not in cycle_id and '-iot' not in cycle_id:
                best_match = cycle
    
    # Fallback: match by build number
    if not best_match and os_build:
        build_tuple = parse_version_tuple(os_build)
        if build_tuple:
            for cycle in cycles:
                if cycle.latest_version:
                    ref_tuple = parse_version_tuple(cycle.latest_version)
                    if ref_tuple and build_tuple[:3] == ref_tuple[:3]:
                        best_match = cycle
                        break
    
    if not best_match:
        return {'status': 'unknown', 'matched_cycle': None, 'eol_date': None,
                'severity': 'info', 'risk_score': 0}
    
    return _evaluate_cycle(best_match, TRACKED_PRODUCTS['windows']['risk_weight'])


def _match_app_lifecycle(app_name, app_version, product_key):
    """
    Match an installed application against lifecycle records.
    
    Returns dict: {status, matched_cycle, eol_date, severity, risk_score} or None
    """
    import server_models
    
    config = TRACKED_PRODUCTS.get(product_key)
    if not config:
        return None
    
    cycles = server_models.SoftwareLifecycle.query.filter_by(
        product_name=product_key
    ).order_by(server_models.SoftwareLifecycle.release_date.desc().nullslast()).all()
    
    if not cycles:
        return {'status': 'unknown', 'matched_cycle': None, 'eol_date': None,
                'severity': 'info', 'risk_score': 0}
    
    installed_tuple = parse_version_tuple(app_version)
    
    # For browsers: compare major version against cycles
    if product_key in ('chrome', 'firefox', 'msedge'):
        if installed_tuple:
            installed_major = installed_tuple[0] if installed_tuple else 0
            
            # Find the latest cycle — browsers use rolling releases
            latest_cycle = cycles[0] if cycles else None
            if latest_cycle:
                latest_tuple = parse_version_tuple(latest_cycle.cycle)
                if latest_tuple:
                    latest_major = latest_tuple[0]
                    gap = latest_major - installed_major
                    
                    if gap <= 2:
                        return {'status': 'supported', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'info', 'risk_score': 0}
                    elif gap <= 5:
                        return {'status': 'outdated', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'medium',
                                'risk_score': config['risk_weight'] // 2}
                    else:
                        return {'status': 'eol', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'high',
                                'risk_score': config['risk_weight']}
    
    # For Office: Match by year version (2016, 2019, 2021, 2024)
    if product_key == 'office':
        # Extract year from app name or version
        year_match = re.search(r'20\d{2}', f'{app_name} {app_version}')
        if year_match:
            office_year = year_match.group()
            for cycle in cycles:
                if cycle.cycle == office_year:
                    return _evaluate_cycle(cycle, config['risk_weight'])
        
        # Check for Microsoft 365 (always supported)
        if '365' in (app_name or ''):
            return {'status': 'supported', 'matched_cycle': '365',
                    'eol_date': None, 'severity': 'info', 'risk_score': 0}
    
    # For Java: Match by major version (8, 11, 17, 21 are LTS)
    if product_key == 'java':
        # Extract major version from version string
        # Java versions: 1.8.0_xxx, 11.0.x, 17.0.x, 21.0.x
        java_major = None
        if installed_tuple:
            if installed_tuple[0] == 1 and len(installed_tuple) > 1:
                # Old format: 1.8.0_xxx -> major is 8
                java_major = installed_tuple[1]
            else:
                java_major = installed_tuple[0]
        
        if java_major:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and java_major == cycle_tuple[0]:
                    return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For .NET Framework: Match by version
    if product_key == 'dotnet':
        # .NET Framework versions: 4.8, 4.8.1, etc.
        if installed_tuple:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple:
                    # Match major.minor
                    if len(installed_tuple) >= 2 and len(cycle_tuple) >= 2:
                        if installed_tuple[0] == cycle_tuple[0] and installed_tuple[1] == cycle_tuple[1]:
                            return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For .NET Core: Match by major.minor version
    if product_key == 'dotnet-core':
        if installed_tuple and len(installed_tuple) >= 2:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and len(cycle_tuple) >= 2:
                    if installed_tuple[0] == cycle_tuple[0] and installed_tuple[1] == cycle_tuple[1]:
                        return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For Node.js: Match by major version
    if product_key == 'nodejs':
        if installed_tuple:
            node_major = installed_tuple[0]
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and node_major == cycle_tuple[0]:
                    return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For Python: Match by major.minor version
    if product_key == 'python':
        if installed_tuple and len(installed_tuple) >= 2:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and len(cycle_tuple) >= 2:
                    if installed_tuple[0] == cycle_tuple[0] and installed_tuple[1] == cycle_tuple[1]:
                        return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For Visual Studio: Match by year version (2019, 2022)
    if product_key == 'visualstudio':
        year_match = re.search(r'20\d{2}', f'{app_name} {app_version}')
        if year_match:
            vs_year = year_match.group()
            for cycle in cycles:
                if vs_year in cycle.cycle:
                    return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For VS Code: Rolling release, check version gap
    if product_key == 'vscode':
        if installed_tuple:
            latest_cycle = cycles[0] if cycles else None
            if latest_cycle:
                latest_tuple = parse_version_tuple(latest_cycle.cycle)
                if latest_tuple:
                    gap = latest_tuple[0] - installed_tuple[0] if installed_tuple else 0
                    if gap <= 2:
                        return {'status': 'supported', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'info', 'risk_score': 0}
                    elif gap <= 5:
                        return {'status': 'outdated', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'medium',
                                'risk_score': config['risk_weight'] // 2}
                    else:
                        return {'status': 'eol', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'high',
                                'risk_score': config['risk_weight']}
    
    # For Adobe Acrobat: Match by year version (2020, 2024)
    if product_key == 'adobe-acrobat':
        year_match = re.search(r'20\d{2}', f'{app_name} {app_version}')
        if year_match:
            adobe_year = year_match.group()
            for cycle in cycles:
                if adobe_year in cycle.cycle:
                    return _evaluate_cycle(cycle, config['risk_weight'])
        # Also try continuous track version matching
        if installed_tuple:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and installed_tuple[0] == cycle_tuple[0]:
                    return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For Git: Match by major.minor version
    if product_key == 'git':
        if installed_tuple and len(installed_tuple) >= 2:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and len(cycle_tuple) >= 2:
                    if installed_tuple[0] == cycle_tuple[0] and installed_tuple[1] == cycle_tuple[1]:
                        return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For OpenSSL: Match by major.minor version (1.1.1, 3.0, 3.1)
    if product_key == 'openssl':
        if installed_tuple and len(installed_tuple) >= 2:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and len(cycle_tuple) >= 2:
                    if installed_tuple[0] == cycle_tuple[0] and installed_tuple[1] == cycle_tuple[1]:
                        return _evaluate_cycle(cycle, config['risk_weight'])
    
    # For Zoom, Slack, Teams: Rolling releases, check version gap
    if product_key in ('zoom', 'slack', 'teams'):
        if installed_tuple:
            latest_cycle = cycles[0] if cycles else None
            if latest_cycle:
                latest_tuple = parse_version_tuple(latest_cycle.cycle)
                if latest_tuple:
                    # These apps update frequently, large gaps are concerning
                    gap = latest_tuple[0] - installed_tuple[0] if installed_tuple else 0
                    if gap <= 0:
                        return {'status': 'supported', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'info', 'risk_score': 0}
                    elif gap <= 2:
                        return {'status': 'outdated', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'medium',
                                'risk_score': config['risk_weight'] // 2}
                    else:
                        return {'status': 'eol', 'matched_cycle': latest_cycle.cycle,
                                'eol_date': None, 'severity': 'high',
                                'risk_score': config['risk_weight']}
    
    # For Go, Rust, Docker, Kubernetes, Terraform: Match by major.minor version
    if product_key in ('go', 'rust', 'docker-engine', 'kubernetes', 'terraform'):
        if installed_tuple and len(installed_tuple) >= 2:
            for cycle in cycles:
                cycle_tuple = parse_version_tuple(cycle.cycle)
                if cycle_tuple and len(cycle_tuple) >= 2:
                    if installed_tuple[0] == cycle_tuple[0] and installed_tuple[1] == cycle_tuple[1]:
                        return _evaluate_cycle(cycle, config['risk_weight'])
            # Fallback: try major-only match
            if installed_tuple:
                for cycle in cycles:
                    cycle_tuple = parse_version_tuple(cycle.cycle)
                    if cycle_tuple and installed_tuple[0] == cycle_tuple[0]:
                        return _evaluate_cycle(cycle, config['risk_weight'])
    
    return {'status': 'unknown', 'matched_cycle': None, 'eol_date': None,
            'severity': 'info', 'risk_score': 0}


def _evaluate_cycle(cycle, risk_weight):
    """Evaluate a matched lifecycle cycle against today's date (UTC, matching
    the rest of the system's day-boundary handling)."""
    today = datetime.now(timezone.utc).date()
    eol = cycle.eol_date
    
    if eol is None:
        return {'status': 'unknown', 'matched_cycle': cycle.cycle,
                'eol_date': None, 'severity': 'info', 'risk_score': 0}
    
    if eol <= today:
        return {
            'status': 'eol',
            'matched_cycle': cycle.cycle,
            'eol_date': eol,
            'severity': 'critical' if risk_weight >= 50 else 'high',
            'risk_score': risk_weight
        }
    elif eol <= today + timedelta(days=APPROACHING_EOL_DAYS):
        return {
            'status': 'outdated',
            'matched_cycle': cycle.cycle,
            'eol_date': eol,
            'severity': 'medium',
            'risk_score': risk_weight // 3
        }
    else:
        return {
            'status': 'supported',
            'matched_cycle': cycle.cycle,
            'eol_date': eol,
            'severity': 'info',
            'risk_score': 0
        }


# ============================================================
# 4. FLEET EVALUATION — Background evaluation for all agents
# ============================================================

def evaluate_agent_lifecycle(agent):
    """
    Evaluate a single agent's OS + installed apps against lifecycle DB.
    Results are upserted into asset_lifecycle_status.
    """
    import server_models
    
    results = []
    
    # --- Evaluate Windows OS ---
    if agent.asset_info:
        os_result = _match_windows_lifecycle(agent.asset_info)
        if os_result:
            _upsert_status(
                agent_id=agent.agent_id,
                product_name='Windows OS',
                installed_version=f"{agent.asset_info.os_name} {agent.asset_info.os_version or ''}".strip(),
                result=os_result
            )
            results.append(('Windows OS', os_result['status']))
    
    # --- Evaluate installed applications ---
    inventory = agent.inventory.all() if hasattr(agent.inventory, 'all') else []
    
    for app in inventory:
        app_name = app.name or ''
        app_version = app.version or ''
        
        for product_key, config in TRACKED_PRODUCTS.items():
            if config['match_type'] != 'app':
                continue
            
            patterns = config.get('patterns', [])
            exclude_patterns = config.get('exclude_patterns', [])
            
            # Check if app matches any pattern
            matched = any(p.lower() in app_name.lower() for p in patterns)
            
            # Check if app should be excluded
            if matched and exclude_patterns:
                excluded = any(ex.lower() in app_name.lower() for ex in exclude_patterns)
                if excluded:
                    matched = False
            
            if matched:
                app_result = _match_app_lifecycle(app_name, app_version, product_key)
                if app_result:
                    _upsert_status(
                        agent_id=agent.agent_id,
                        product_name=config['display_name'],
                        installed_version=app_version,
                        result=app_result
                    )
                    results.append((config['display_name'], app_result['status']))
                break  # Only match first pattern per app
    
    return results


def evaluate_cli_tools_lifecycle(agent):
    """
    Evaluate CLI tools installed on an agent against lifecycle DB.
    Uses CLI_TOOL_PRODUCTS mapping for matching.
    """
    import server_models
    
    results = []
    
    # Get CLI tools for this agent
    cli_tools = agent.cli_tools.all() if hasattr(agent, 'cli_tools') else []
    
    for tool in cli_tools:
        tool_name = (tool.name or '').lower()
        tool_version = tool.version or ''
        
        for product_key, config in CLI_TOOL_PRODUCTS.items():
            cli_names = config.get('cli_names', [])
            
            # Check if tool name matches any CLI name
            if tool_name in [n.lower() for n in cli_names]:
                cli_result = _match_app_lifecycle(tool.name, tool_version, product_key)
                if cli_result:
                    _upsert_status(
                        agent_id=agent.agent_id,
                        product_name=config['display_name'],
                        installed_version=tool_version,
                        result=cli_result
                    )
                    results.append((config['display_name'], cli_result['status']))
                break  # Only match first pattern per tool
    
    return results


def evaluate_extended_inventory_lifecycle(agent):
    """
    Evaluate all extended inventory items (CLI tools, portable apps) against lifecycle DB.
    Combines CLI tools and portable applications evaluation.
    """
    results = []
    
    # Evaluate CLI tools
    try:
        cli_results = evaluate_cli_tools_lifecycle(agent)
        results.extend(cli_results)
    except Exception as e:
        logger.error(f"[EOL] Error evaluating CLI tools for agent {agent.agent_id}: {e}")
    
    # Evaluate portable applications (treat same as regular apps)
    try:
        portable_apps = agent.portable_applications.all() if hasattr(agent, 'portable_applications') else []
        
        for app in portable_apps:
            app_name = app.name or ''
            app_version = app.version or ''
            
            for product_key, config in TRACKED_PRODUCTS.items():
                if config['match_type'] != 'app':
                    continue
                
                patterns = config.get('patterns', [])
                exclude_patterns = config.get('exclude_patterns', [])
                
                matched = any(p.lower() in app_name.lower() for p in patterns)
                
                if matched and exclude_patterns:
                    excluded = any(ex.lower() in app_name.lower() for ex in exclude_patterns)
                    if excluded:
                        matched = False
                
                if matched:
                    app_result = _match_app_lifecycle(app_name, app_version, product_key)
                    if app_result:
                        _upsert_status(
                            agent_id=agent.agent_id,
                            product_name=f"{config['display_name']} (Portable)",
                            installed_version=app_version,
                            result=app_result
                        )
                        results.append((f"{config['display_name']} (Portable)", app_result['status']))
                    break
    except Exception as e:
        logger.error(f"[EOL] Error evaluating portable apps for agent {agent.agent_id}: {e}")
    
    return results


def evaluate_fleet_lifecycle(org_id=None):
    """
    Evaluate lifecycle status for all agents.
    Call after lifecycle DB sync or on schedule.
    
    Args:
        org_id: Optional organization ID to filter agents.
    
    Returns:
        dict with summary counts.
    """
    import server_models
    
    query = server_models.Agent.query
    if org_id:
        query = query.filter_by(org_id=org_id)
        
    agents = query.all()
    total = 0
    eol_count = 0
    outdated_count = 0
    
    for agent in agents:
        try:
            # Evaluate standard inventory (OS + installed apps)
            results = evaluate_agent_lifecycle(agent)
            for product, status in results:
                total += 1
                if status == 'eol':
                    eol_count += 1
                elif status == 'outdated':
                    outdated_count += 1
            
            # Evaluate extended inventory (CLI tools, portable apps)
            extended_results = evaluate_extended_inventory_lifecycle(agent)
            for product, status in extended_results:
                total += 1
                if status == 'eol':
                    eol_count += 1
                elif status == 'outdated':
                    outdated_count += 1
        except Exception as e:
            logger.error(f"[EOL] Error evaluating agent {agent.agent_id}: {e}")
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"[EOL] Failed to commit fleet evaluation: {e}")
    
    summary = {
        'agents_evaluated': len(agents),
        'total_products_checked': total,
        'eol_count': eol_count,
        'outdated_count': outdated_count,
        'supported_count': total - eol_count - outdated_count
    }
    
    logger.info(f"[EOL] Fleet evaluation complete: {summary}")
    return summary


def _upsert_status(agent_id, product_name, installed_version, result):
    """Insert or update a lifecycle status record for an agent+product."""
    import server_models
    
    existing = server_models.AssetLifecycleStatus.query.filter_by(
        agent_id=agent_id, product_name=product_name
    ).first()
    
    if existing:
        existing.installed_version = installed_version
        existing.matched_cycle = result.get('matched_cycle')
        existing.status = result['status']
        existing.eol_date = result.get('eol_date')
        existing.risk_score = result.get('risk_score', 0)
        existing.severity = result.get('severity', 'info')
        existing.evaluated_at = datetime.now(timezone.utc)
    else:
        record = server_models.AssetLifecycleStatus(
            agent_id=agent_id,
            product_name=product_name,
            installed_version=installed_version,
            matched_cycle=result.get('matched_cycle'),
            status=result['status'],
            eol_date=result.get('eol_date'),
            risk_score=result.get('risk_score', 0),
            severity=result.get('severity', 'info'),
            evaluated_at=datetime.now(timezone.utc)
        )
        db.session.add(record)


# ============================================================
# 5. FLEET SUMMARY — Aggregate statistics for dashboard
# ============================================================

def get_fleet_lifecycle_summary(org_id=None):
    """
    Get fleet-wide lifecycle risk aggregation.
    Returns dict suitable for dashboard API response.
    
    Args:
        org_id: Optional organization ID to filter stats.
    """
    import server_models
    from sqlalchemy import func
    
    # Base query for stats
    base_query = db.session.query(server_models.AssetLifecycleStatus)
    if org_id:
        base_query = base_query.join(server_models.Agent).filter(server_models.Agent.org_id == org_id)

    # Count distinct agents that have been evaluated
    total_agents = db.session.query(
        func.count(func.distinct(server_models.AssetLifecycleStatus.agent_id))
    )
    if org_id:
        total_agents = total_agents.join(server_models.Agent).filter(server_models.Agent.org_id == org_id)
    total_agents = total_agents.scalar() or 0
    
    # Count by status
    status_query = db.session.query(
        server_models.AssetLifecycleStatus.status,
        func.count(server_models.AssetLifecycleStatus.id)
    )
    if org_id:
        status_query = status_query.join(server_models.Agent).filter(server_models.Agent.org_id == org_id)
    status_counts = status_query.group_by(server_models.AssetLifecycleStatus.status).all()
    
    counts = {s: c for s, c in status_counts}
    
    eol = counts.get('eol', 0)
    outdated = counts.get('outdated', 0)
    supported = counts.get('supported', 0)
    unknown = counts.get('unknown', 0)
    total = eol + outdated + supported + unknown
    
    # Top risks: EOL products affecting most agents
    risk_query = db.session.query(
        server_models.AssetLifecycleStatus.product_name,
        server_models.AssetLifecycleStatus.installed_version,
        server_models.AssetLifecycleStatus.eol_date,
        server_models.AssetLifecycleStatus.severity,
        func.count(server_models.AssetLifecycleStatus.id).label('affected_count')
    ).filter(
        server_models.AssetLifecycleStatus.status.in_(['eol', 'outdated'])
    )
    if org_id:
        risk_query = risk_query.join(server_models.Agent).filter(server_models.Agent.org_id == org_id)
        
    top_risks = risk_query.group_by(
        server_models.AssetLifecycleStatus.product_name,
        server_models.AssetLifecycleStatus.installed_version,
        server_models.AssetLifecycleStatus.eol_date,
        server_models.AssetLifecycleStatus.severity
    ).order_by(func.count(server_models.AssetLifecycleStatus.id).desc()).limit(10).all()
    
    return {
        'total_agents_evaluated': total_agents,
        'total_products_checked': total,
        'eol_count': eol,
        'outdated_count': outdated,
        'supported_count': supported,
        'unknown_count': unknown,
        'compliance_rate': round((supported / total) * 100, 1) if total > 0 else 100.0,
        'top_risks': [{
            'product': r.product_name,
            'version': r.installed_version,
            'eol_date': r.eol_date.isoformat() if r.eol_date else None,
            'severity': r.severity,
            'affected_agents': r.affected_count
        } for r in top_risks]
    }
