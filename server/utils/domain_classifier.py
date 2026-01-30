"""
Domain Session Classifier
Classifies domain sessions using rules + manual tags
"""

import re
from typing import Optional, Dict, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DomainClassifier:
    """Classify domain sessions using admin-defined rules"""

    def __init__(self, db):
        self.db = db
        self._rules_cache = None
        self._cache_time = None
        self._cache_ttl = 300  # 5 minutes

    def classify(self, raw_title: str, raw_url: str = None) -> Dict:
        """
        Classify a domain session.

        Args:
            raw_title: Original window title
            raw_url: URL from CDP (if available)

        Returns:
            {
                'domain': 'google.com' or None,
                'action': 'map' or 'ignore',
                'source': 'rule' | 'url' | 'unknown',
                'confidence': 0.0 to 1.0,
                'rule_id': ID of matched rule (if any)
            }
        """

        # Step 1: Check classification rules (admin-defined patterns)
        rule_result = self._check_rules(raw_title, raw_url)
        if rule_result:
            return rule_result

        # Step 2: Try to extract from URL (if available)
        if raw_url:
            domain = self._extract_domain_from_url(raw_url)
            if domain:
                # Validate it's not localhost
                if not self._is_localhost(domain):
                    return {
                        'domain': domain,
                        'action': 'map',
                        'source': 'url',
                        'confidence': 0.95,
                        'rule_id': None
                    }

        # Step 3: No match - mark for manual review
        return {
            'domain': None,
            'action': 'needs_review',
            'source': 'unknown',
            'confidence': 0.0,
            'rule_id': None
        }

    def _check_rules(self, title: str, url: str = None) -> Optional[Dict]:
        """Check against classification rules"""

        # Get cached rules
        rules = self._get_rules()

        if not title:
            return None

        title_lower = title.lower()
        url_lower = (url or '').lower()

        # Check each rule in priority order
        for rule in rules:
            if not rule['is_active']:
                continue

            matched = False
            pattern = rule['pattern'].lower()

            # Match against title
            if rule['pattern_type'] == 'substring':
                matched = pattern in title_lower
            elif rule['pattern_type'] == 'regex':
                try:
                    matched = bool(re.search(pattern, title_lower))
                except:
                    pass
            elif rule['pattern_type'] == 'exact':
                matched = title_lower == pattern

            # Also check URL if provided
            if not matched and url_lower:
                if rule['pattern_type'] == 'substring':
                    matched = pattern in url_lower

            if matched:
                # Update match stats
                self._update_rule_stats(rule['id'])

                logger.debug(
                    f"[CLASSIFIER] Rule matched: '{pattern}' → "
                    f"{rule['classified_as']} ({rule['action']})"
                )

                return {
                    'domain': rule['classified_as'],
                    'action': rule['action'],
                    'source': 'rule',
                    'confidence': 1.0,
                    'rule_id': rule['id']
                }

        return None

    def _get_rules(self) -> List[Dict]:
        """Get classification rules (cached)"""
        from sqlalchemy import text

        now = datetime.now()

        # Check cache
        if (self._rules_cache and self._cache_time and 
            (now - self._cache_time).total_seconds() < self._cache_ttl):
            return self._rules_cache

        # Fetch from database
        try:
            result = self.db.session.execute(text('''
                SELECT id, pattern, pattern_type, classified_as, action, 
                       priority, is_active
                FROM domain_classification_rules
                WHERE is_active = TRUE
                ORDER BY priority ASC, created_at ASC
            '''))

            rules = []
            for row in result:
                rules.append({
                    'id': row[0],
                    'pattern': row[1],
                    'pattern_type': row[2],
                    'classified_as': row[3],
                    'action': row[4],
                    'priority': row[5],
                    'is_active': row[6]
                })

            # Update cache
            self._rules_cache = rules
            self._cache_time = now

            return rules
        except Exception as e:
            logger.warning(f"[CLASSIFIER] Failed to fetch rules: {e}")
            try:
                # Rollback the failed transaction to allow future queries
                self.db.session.rollback()
            except Exception as rollback_e:
                logger.debug(f"Failed to rollback transaction: {rollback_e}")
            return []

    def _update_rule_stats(self, rule_id: int):
        """Update match stats for a rule"""
        from sqlalchemy import text
        try:
            self.db.session.execute(text('''
                UPDATE domain_classification_rules
                SET match_count = match_count + 1,
                    last_matched_at = NOW()
                WHERE id = :rule_id
            '''), {'rule_id': rule_id})
            self.db.session.commit()
        except Exception as e:
            logger.debug(f"Failed to update rule stats: {e}")

    def _extract_domain_from_url(self, url: str) -> Optional[str]:
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            netloc = parsed.netloc or ''

            # Remove port
            if ':' in netloc:
                netloc = netloc.split(':')[0]

            # Remove www
            if netloc.startswith('www.'):
                netloc = netloc[4:]

            return netloc.lower() if netloc else None
        except:
            return None

    def _is_localhost(self, domain: str) -> bool:
        """Check if domain is localhost"""
        localhost_patterns = [
            'localhost', '127.0.0.1', '0.0.0.0',
            '192.168.', '10.0.'
        ]
        domain_lower = domain.lower()
        return any(p in domain_lower for p in localhost_patterns)

    def clear_cache(self):
        """Clear rules cache (call after updating rules)"""
        self._rules_cache = None
        self._cache_time = None


# Singleton instance - initialized when imported
_classifier_instance = None


def get_classifier(db):
    """Get or create the singleton classifier instance"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = DomainClassifier(db)
    return _classifier_instance
