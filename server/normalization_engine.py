"""
Normalization Engine
====================
Canonical naming and fuzzy matching for software inventory.

This module transforms raw registry/inventory data into normalized forms
suitable for EOL matching and standardized identifier generation.

Components:
- NormalizationEngine: Regex-based canonical naming for apps and publishers
- FuzzyMatcher: Levenshtein/Jaro-Winkler matching against known products
- CPEResolver: CPE 2.3 string generation and local NVD cache lookup
"""
import re
import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

# Try to import rapidfuzz for high-performance fuzzy matching
# Falls back to difflib if not available
try:
    from rapidfuzz import fuzz, process as rf_process
    HAS_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher
    HAS_RAPIDFUZZ = False
    logger.info("[NORMALIZE] rapidfuzz not installed, using difflib fallback")


# =============================================================================
# PUBLISHER ALIASES — Map variants to canonical publisher names
# =============================================================================
PUBLISHER_ALIASES = {
    # Microsoft variants
    'microsoft corporation': 'microsoft',
    'microsoft corp': 'microsoft',
    'microsoft corp.': 'microsoft',
    'microsoft': 'microsoft',

    # Google variants
    'google llc': 'google',
    'google inc': 'google',
    'google inc.': 'google',

    # Mozilla variants
    'mozilla corporation': 'mozilla',
    'mozilla foundation': 'mozilla',

    # Adobe variants
    'adobe systems incorporated': 'adobe',
    'adobe systems': 'adobe',
    'adobe inc.': 'adobe',
    'adobe inc': 'adobe',

    # Oracle variants
    'oracle corporation': 'oracle',
    'oracle america, inc.': 'oracle',
    'sun microsystems': 'oracle',

    # Apple variants
    'apple inc.': 'apple',
    'apple inc': 'apple',
    'apple computer, inc.': 'apple',

    # Misc
    'the git development community': 'git',
    'node.js foundation': 'nodejs',
    'openjdk': 'oracle',
    'eclipse adoptium': 'adoptium',
    'jetbrains s.r.o.': 'jetbrains',
    'jetbrains': 'jetbrains',
    'slack technologies': 'slack',
    'slack technologies, inc.': 'slack',
    'zoom video communications, inc.': 'zoom',
    'zoom video communications': 'zoom',
    'docker inc.': 'docker',
    'docker inc': 'docker',
}

# =============================================================================
# NAME CLEANUP PATTERNS — Regex patterns to strip noise from app names
# =============================================================================
NAME_CLEANUP_PATTERNS = [
    # Architecture suffixes
    (r'\s*\(x86\)\s*', ''),
    (r'\s*\(x64\)\s*', ''),
    (r'\s*\(64-?bit\)\s*', ''),
    (r'\s*\(32-?bit\)\s*', ''),
    (r'\s*\(ARM64\)\s*', ''),
    (r'\s*\(amd64\)\s*', ''),

    # Version in parentheses  e.g. "(v4.5.1)"
    (r'\s*\(v?\d+[\d.]*\)\s*', ''),

    # "- update X" or "Update X"
    (r'\s*-?\s*update\s+\d+\s*', ''),

    # Common noise words at end
    (r'\s+(installer|setup|redistributable|runtime|sdk|tools?)(\s|$)', ''),

    # "for Windows" or "for x64"
    (r'\s+for\s+(windows|x64|x86|win\d+)\s*$', ''),

    # Trailing version number  e.g. "Python 3.12.1"
    (r'\s+\d+\.\d+[\d.]*\s*$', ''),

    # Microsoft prefix that's redundant for Office products
    (r'^microsoft\s+(office\s+)', r'\1'),
]


# =============================================================================
# NORMALIZATION ENGINE
# =============================================================================

class NormalizationEngine:
    """
    Transforms raw software names and publishers into canonical forms.
    Used before EOL matching and identifier generation.
    """

    def __init__(self):
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in NAME_CLEANUP_PATTERNS
        ]

    def normalize_name(self, raw_name: str) -> str:
        """
        Normalize an application name to its canonical form.

        Examples:
            "Google Chrome (x64)"       -> "google chrome"
            "Python 3.12.1 (64-bit)"    -> "python"
            "Microsoft Office Pro 2021" -> "office pro 2021"
        """
        if not raw_name:
            return ''

        name = raw_name.strip()

        for pattern, replacement in self._compiled_patterns:
            name = pattern.sub(replacement, name)

        # Final cleanup
        name = name.lower().strip()
        name = re.sub(r'\s+', ' ', name)  # collapse whitespace
        return name

    def normalize_publisher(self, raw_publisher: str) -> str:
        """
        Map publisher variants to a canonical name.

        Examples:
            "Microsoft Corporation" -> "microsoft"
            "Google LLC"            -> "google"
            "Adobe Systems Incorporated" -> "adobe"
        """
        if not raw_publisher:
            return ''

        key = raw_publisher.lower().strip()
        return PUBLISHER_ALIASES.get(key, key)

    def normalize_app(self, name: str, publisher: str = '', version: str = '') -> Dict[str, str]:
        """
        Normalize all fields of an application entry.

        Returns:
            Dict with 'name', 'publisher', 'version' (all normalized)
        """
        return {
            'name': self.normalize_name(name),
            'publisher': self.normalize_publisher(publisher),
            'version': (version or '').strip(),
        }


# =============================================================================
# FUZZY MATCHER
# =============================================================================

class FuzzyMatcher:
    """
    Fuzzy matching engine for mapping normalized app names to known products.
    Uses rapidfuzz (C++ accelerated) when available, falls back to difflib.
    """

    def __init__(self, threshold: int = 85):
        """
        Args:
            threshold: Minimum match score (0-100) to consider a match valid.
        """
        self.threshold = threshold

    def match_to_product(
        self,
        normalized_name: str,
        known_products: Dict[str, dict],
    ) -> Optional[Tuple[str, int]]:
        """
        Match a normalized app name against known product definitions.

        Args:
            normalized_name: Cleaned app name (from NormalizationEngine)
            known_products: Dict of product_key -> config (with 'patterns' list)

        Returns:
            Tuple of (product_key, score) or None if no match above threshold.
        """
        if not normalized_name:
            return None

        # Step 1: Exact pattern match (fastest)
        for product_key, config in known_products.items():
            patterns = config.get('patterns', [])
            for pattern in patterns:
                if pattern.lower() in normalized_name:
                    return (product_key, 100)

        # Step 2: Fuzzy match against all pattern strings
        all_candidates = {}
        for product_key, config in known_products.items():
            for pattern in config.get('patterns', []):
                all_candidates[pattern.lower()] = product_key

        if not all_candidates:
            return None

        if HAS_RAPIDFUZZ:
            result = rf_process.extractOne(
                normalized_name,
                list(all_candidates.keys()),
                scorer=fuzz.token_sort_ratio,
                score_cutoff=self.threshold
            )
            if result:
                matched_pattern, score, _ = result
                return (all_candidates[matched_pattern], int(score))
        else:
            # difflib fallback
            best_score = 0
            best_key = None
            for candidate, product_key in all_candidates.items():
                ratio = SequenceMatcher(None, normalized_name, candidate).ratio() * 100
                if ratio > best_score:
                    best_score = ratio
                    best_key = product_key

            if best_score >= self.threshold and best_key:
                return (best_key, int(best_score))

        return None

    def batch_match(
        self,
        apps: List[Dict],
        known_products: Dict[str, dict],
        normalizer: Optional[NormalizationEngine] = None,
    ) -> List[Dict]:
        """
        Match a batch of applications against known products.

        Args:
            apps: List of dicts with 'name' key (and optionally 'version', 'publisher')
            known_products: Product definitions from eol_engine.TRACKED_PRODUCTS
            normalizer: Optional NormalizationEngine instance (creates one if None)

        Returns:
            List of dicts: {'app_name', 'normalized_name', 'product_key', 'score'}
        """
        if normalizer is None:
            normalizer = NormalizationEngine()

        results = []
        for app in apps:
            raw_name = app.get('name', '')
            normalized = normalizer.normalize_name(raw_name)

            match = self.match_to_product(normalized, known_products)
            results.append({
                'app_name': raw_name,
                'normalized_name': normalized,
                'product_key': match[0] if match else None,
                'score': match[1] if match else 0,
            })

        return results


# =============================================================================
# CPE RESOLVER
# =============================================================================

class CPEResolver:
    """
    Generate and resolve CPE 2.3 formatted strings for software products.
    """

    @staticmethod
    def generate_cpe(name: str, version: str, publisher: str) -> str:
        """
        Generate CPE 2.3 formatted string.
        Format: cpe:2.3:a:<vendor>:<product>:<version>:*:*:*:*:*:*:*

        Args:
            name: Normalized product name
            version: Product version string
            publisher: Normalized publisher name
        """
        vendor = CPEResolver._cpe_sanitize(publisher)
        product = CPEResolver._cpe_sanitize(name)
        ver = CPEResolver._cpe_sanitize(version) if version else '*'

        if not vendor or not product:
            return ''

        return f"cpe:2.3:a:{vendor}:{product}:{ver}:*:*:*:*:*:*:*"

    @staticmethod
    def lookup_cpe(cpe_string: str, db_session=None) -> Optional[Dict]:
        """
        Check local NVD cache for known vulnerabilities matching this CPE.

        Args:
            cpe_string: CPE 2.3 formatted string
            db_session: SQLAlchemy session (optional, uses default if None)

        Returns:
            Dict with vulnerability summary or None
        """
        if not cpe_string or not db_session:
            return None

        try:
            # Import here to avoid circular imports
            import server_models

            entries = server_models.NVDCacheEntry.query.filter_by(
                cpe_string=cpe_string
            ).order_by(
                server_models.NVDCacheEntry.cvss_score.desc()
            ).limit(10).all()

            if not entries:
                return None

            return {
                'cpe': cpe_string,
                'vulnerability_count': len(entries),
                'max_cvss': max(e.cvss_score for e in entries),
                'critical_count': sum(1 for e in entries if e.severity == 'CRITICAL'),
                'high_count': sum(1 for e in entries if e.severity == 'HIGH'),
                'cves': [{'cve_id': e.cve_id, 'cvss': e.cvss_score, 'severity': e.severity}
                         for e in entries[:5]]
            }
        except Exception as e:
            logger.error(f"[CPE] Lookup failed for {cpe_string}: {e}")
            return None

    @staticmethod
    def _cpe_sanitize(value: str) -> str:
        """Sanitize a string for CPE format"""
        if not value:
            return ''
        sanitized = value.lower().strip()
        # Remove common corporate suffixes
        for suffix in ['corporation', 'inc.', 'inc', 'llc', 'ltd.', 'ltd', 'co.', 'gmbh', 's.r.o.']:
            sanitized = sanitized.replace(suffix, '')
        sanitized = re.sub(r'[^a-z0-9]', '_', sanitized)
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        return sanitized
