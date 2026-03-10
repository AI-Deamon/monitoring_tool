"""
NVD Cache — Local NIST National Vulnerability Database Cache
=============================================================
Syncs CVE/vulnerability data from NIST NVD 2.0 API for offline lookup.

This is a SUPPLEMENTARY intelligence source. The PRIMARY EOL data comes
from endoflife.date (handled by eol_engine.py). This module adds
vulnerability context (CVEs, CVSS scores) for the risk scoring rubric.

Features:
- Incremental sync using lastModStartDate/lastModEndDate
- Rate limiting (6 req/30s without API key, 50 req/30s with key)
- CPE-based vulnerability matching
- Local SQLAlchemy storage for fast lookups
"""
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"


class NVDCache:
    """
    Local cache of NIST NVD vulnerability data.

    Syncs incrementally and stores CVE entries with CVSS scores
    for lookup by CPE string during risk scoring.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Optional NVD API key for higher rate limits.
                     Without key: 6 requests per 30 seconds.
                     With key: 50 requests per 30 seconds.
        """
        self.api_key = api_key
        self.request_delay = 1.0 if api_key else 6.0  # seconds between requests

    def sync(self, days_back: int = 30, cpe_filter: Optional[str] = None) -> Dict:
        """
        Sync CVE data from NVD API into local database.

        Args:
            days_back: How many days of modified CVEs to fetch.
            cpe_filter: Optional CPE string to filter results (e.g. "cpe:2.3:a:microsoft:*:*")

        Returns:
            Dict with sync summary: {synced, errors, duration_seconds}
        """
        import server_models
        from extensions import db

        start_time = time.time()
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days_back)

        params = {
            'lastModStartDate': start_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00'),
            'lastModEndDate': now.strftime('%Y-%m-%dT%H:%M:%S.000+00:00'),
            'resultsPerPage': 200,
            'startIndex': 0,
        }

        if cpe_filter:
            params['cpeName'] = cpe_filter

        headers = {}
        if self.api_key:
            headers['apiKey'] = self.api_key

        total_synced = 0
        total_errors = 0
        total_results = None

        while True:
            try:
                resp = requests.get(
                    NVD_API_BASE,
                    params=params,
                    headers=headers,
                    timeout=30
                )

                if resp.status_code == 403:
                    logger.warning("[NVD] Rate limited, waiting 30s...")
                    time.sleep(30)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if total_results is None:
                    total_results = data.get('totalResults', 0)
                    logger.info(f"[NVD] Total CVEs to sync: {total_results}")

                vulnerabilities = data.get('vulnerabilities', [])
                if not vulnerabilities:
                    break

                for vuln_wrapper in vulnerabilities:
                    try:
                        cve = vuln_wrapper.get('cve', {})
                        cve_id = cve.get('id', '')
                        if not cve_id:
                            continue

                        # Extract CVSS score (prefer v3.1, fallback to v3.0, then v2.0)
                        cvss_score, severity = self._extract_cvss(cve)

                        # Extract affected CPEs
                        cpe_strings = self._extract_cpes(cve)

                        # Extract description
                        descriptions = cve.get('descriptions', [])
                        desc = ''
                        for d in descriptions:
                            if d.get('lang') == 'en':
                                desc = d.get('value', '')[:500]
                                break

                        published = cve.get('published', '')
                        modified = cve.get('lastModified', '')

                        # Upsert each CPE entry
                        for cpe_str in cpe_strings:
                            existing = server_models.NVDCacheEntry.query.filter_by(
                                cve_id=cve_id, cpe_string=cpe_str
                            ).first()

                            if existing:
                                existing.cvss_score = cvss_score
                                existing.severity = severity
                                existing.description = desc
                                existing.last_modified = modified
                                existing.synced_at = now
                            else:
                                entry = server_models.NVDCacheEntry(
                                    cve_id=cve_id,
                                    cpe_string=cpe_str,
                                    cvss_score=cvss_score,
                                    severity=severity,
                                    description=desc,
                                    published_date=published,
                                    last_modified=modified,
                                    synced_at=now,
                                )
                                db.session.add(entry)
                            total_synced += 1

                    except Exception as e:
                        total_errors += 1
                        logger.debug(f"[NVD] Error processing CVE: {e}")

                db.session.commit()

                # Pagination
                params['startIndex'] += len(vulnerabilities)
                if params['startIndex'] >= total_results:
                    break

                # Rate limiting
                time.sleep(self.request_delay)

            except requests.RequestException as e:
                total_errors += 1
                logger.error(f"[NVD] API request failed: {e}")
                break
            except Exception as e:
                db.session.rollback()
                total_errors += 1
                logger.error(f"[NVD] Unexpected error: {e}")
                break

        duration = time.time() - start_time
        logger.info(f"[NVD] Sync complete: {total_synced} entries, {total_errors} errors, {duration:.1f}s")

        return {
            'synced': total_synced,
            'errors': total_errors,
            'duration_seconds': round(duration, 1),
        }

    def lookup_by_cpe(self, cpe_string: str) -> Optional[Dict]:
        """
        Look up known vulnerabilities for a CPE string in the local cache.

        Args:
            cpe_string: CPE 2.3 formatted string

        Returns:
            Dict with vulnerability summary, or None
        """
        import server_models

        try:
            # Use LIKE for partial CPE matching (wildcard versions)
            cpe_base = cpe_string.replace(':*:', ':%:').rstrip(':*')
            entries = server_models.NVDCacheEntry.query.filter(
                server_models.NVDCacheEntry.cpe_string.like(f'{cpe_base}%')
            ).order_by(
                server_models.NVDCacheEntry.cvss_score.desc()
            ).limit(50).all()

            if not entries:
                return None

            return {
                'cpe': cpe_string,
                'total_cves': len(entries),
                'max_cvss': max(e.cvss_score for e in entries),
                'critical': sum(1 for e in entries if e.severity == 'CRITICAL'),
                'high': sum(1 for e in entries if e.severity == 'HIGH'),
                'medium': sum(1 for e in entries if e.severity == 'MEDIUM'),
                'low': sum(1 for e in entries if e.severity == 'LOW'),
                'top_cves': [
                    {'cve_id': e.cve_id, 'cvss': e.cvss_score, 'severity': e.severity}
                    for e in entries[:5]
                ]
            }
        except Exception as e:
            logger.error(f"[NVD] Lookup failed for {cpe_string}: {e}")
            return None

    @staticmethod
    def _extract_cvss(cve: dict) -> tuple:
        """Extract best CVSS score and severity from CVE data"""
        metrics = cve.get('metrics', {})

        # Try CVSS 3.1
        for m in metrics.get('cvssMetricV31', []):
            data = m.get('cvssData', {})
            return (data.get('baseScore', 0.0), data.get('baseSeverity', 'NONE'))

        # Try CVSS 3.0
        for m in metrics.get('cvssMetricV30', []):
            data = m.get('cvssData', {})
            return (data.get('baseScore', 0.0), data.get('baseSeverity', 'NONE'))

        # Try CVSS 2.0
        for m in metrics.get('cvssMetricV2', []):
            data = m.get('cvssData', {})
            score = data.get('baseScore', 0.0)
            # Map v2 score to severity
            if score >= 7.0:
                sev = 'HIGH'
            elif score >= 4.0:
                sev = 'MEDIUM'
            else:
                sev = 'LOW'
            return (score, sev)

        return (0.0, 'NONE')

    @staticmethod
    def _extract_cpes(cve: dict) -> List[str]:
        """Extract CPE strings from CVE configuration nodes"""
        cpes = []
        configurations = cve.get('configurations', [])

        for config in configurations:
            for node in config.get('nodes', []):
                for match in node.get('cpeMatch', []):
                    if match.get('vulnerable', False):
                        cpe_str = match.get('criteria', '')
                        if cpe_str:
                            cpes.append(cpe_str)

        return cpes[:20]  # Cap at 20 CPEs per CVE
