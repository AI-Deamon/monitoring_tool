"""
Risk Scoring Rubric
===================
Composite 1-20 risk scoring system for EOL/lifecycle assessment.

The risk score is a weighted composite of multiple factors:
- EOL proximity (days until/since EOL)
- Vulnerability exposure (CVSS scores from NVD cache)
- Deployment scope (how many assets run this software)
- Business criticality (OS vs app, server vs workstation)
- Compensating controls (ESU, isolated network, etc.)

Score bands:
  1-5   : LOW      — Fully supported, no action needed
  6-10  : MODERATE — Approaching EOL, plan migration
  11-15 : HIGH     — Past EOL or imminent, prioritize migration
  16-20 : CRITICAL — Severe risk, unsupported + exploitable
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


# =============================================================================
# SCORING WEIGHTS — Configurable factors
# =============================================================================

DEFAULT_WEIGHTS = {
    'eol_proximity':        0.35,  # How close to/past EOL
    'vulnerability':        0.25,  # CVSS and exploit availability
    'deployment_scope':     0.15,  # Fleet impact (% of assets)
    'business_criticality': 0.15,  # OS/infra vs user app
    'compensating_controls': 0.10, # ESU, network isolation, etc.
}

# Business criticality tiers
CRITICALITY_TIERS = {
    'os':           1.0,  # Operating system — highest impact
    'server_os':    1.0,
    'runtime':      0.8,  # Runtimes (.NET, Java, Node, Python)
    'database':     0.8,
    'browser':      0.6,  # Browsers
    'office':       0.5,  # Productivity
    'agent':        0.4,  # Monitoring/management agents
    'utility':      0.3,  # Utilities and tools
    'default':      0.5,
}


@dataclass
class RiskFactors:
    """Individual risk factor scores (each 0.0-1.0)"""
    eol_proximity_score: float = 0.0
    vulnerability_score: float = 0.0
    deployment_scope_score: float = 0.0
    business_criticality_score: float = 0.0
    compensating_controls_score: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RiskAssessment:
    """Complete risk assessment result"""
    composite_score: int = 0         # 1-20 final score
    severity: str = 'low'            # low, moderate, high, critical
    factors: RiskFactors = None
    rationale: str = ''              # Human-readable explanation
    recommendations: list = None

    def __post_init__(self):
        if self.factors is None:
            self.factors = RiskFactors()
        if self.recommendations is None:
            self.recommendations = []

    def to_dict(self) -> Dict:
        return {
            'composite_score': self.composite_score,
            'severity': self.severity,
            'factors': self.factors.to_dict(),
            'rationale': self.rationale,
            'recommendations': self.recommendations,
        }


# =============================================================================
# RISK SCORING ENGINE
# =============================================================================

class RiskScoringEngine:
    """
    Computes composite risk scores for software lifecycle assessments.

    Usage:
        engine = RiskScoringEngine()
        assessment = engine.assess(
            eol_date=datetime(2024, 10, 14),
            product_type='os',
            cvss_max=7.5,
            fleet_percentage=0.45,
            has_esu=False
        )
        print(assessment.composite_score)  # e.g. 16
        print(assessment.severity)         # 'critical'
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        # Normalize weights to sum to 1.0
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            for key in self.weights:
                self.weights[key] /= total

    def assess(
        self,
        eol_date: Optional[datetime] = None,
        eos_date: Optional[datetime] = None,
        product_type: str = 'default',
        cvss_max: float = 0.0,
        cve_count: int = 0,
        exploit_available: bool = False,
        fleet_percentage: float = 0.0,
        fleet_count: int = 0,
        has_esu: bool = False,
        is_isolated: bool = False,
        has_waf: bool = False,
        custom_mitigations: int = 0,
    ) -> RiskAssessment:
        """
        Calculate a composite risk score.

        Args:
            eol_date: End of Life date (None = unknown)
            eos_date: End of Support date (None = same as eol_date)
            product_type: Key from CRITICALITY_TIERS
            cvss_max: Highest CVSS score for known vulnerabilities
            cve_count: Number of known CVEs
            exploit_available: Whether a public exploit exists
            fleet_percentage: Fraction of fleet running this (0.0-1.0)
            fleet_count: Absolute count of affected assets
            has_esu: Whether ESU is active
            is_isolated: Whether on isolated network
            has_waf: Whether behind WAF/proxy
            custom_mitigations: Number of additional mitigations

        Returns:
            RiskAssessment with composite_score (1-20) and details
        """
        factors = RiskFactors()
        rationale_parts = []

        # --- Factor 1: EOL Proximity (0.0 = fully supported, 1.0 = long past EOL)
        factors.eol_proximity_score = self._score_eol_proximity(eol_date, eos_date)
        rationale_parts.append(self._explain_eol_proximity(eol_date, factors.eol_proximity_score))

        # --- Factor 2: Vulnerability exposure
        factors.vulnerability_score = self._score_vulnerability(cvss_max, cve_count, exploit_available)
        if factors.vulnerability_score > 0.3:
            rationale_parts.append(f"CVSS {cvss_max:.1f}, {cve_count} CVEs" +
                                   (" (exploit available)" if exploit_available else ""))

        # --- Factor 3: Deployment scope
        factors.deployment_scope_score = self._score_deployment(fleet_percentage, fleet_count)
        if fleet_percentage > 0.1:
            rationale_parts.append(f"{fleet_percentage*100:.0f}% of fleet ({fleet_count} assets)")

        # --- Factor 4: Business criticality
        factors.business_criticality_score = CRITICALITY_TIERS.get(product_type, CRITICALITY_TIERS['default'])
        if factors.business_criticality_score >= 0.8:
            rationale_parts.append(f"High criticality ({product_type})")

        # --- Factor 5: Compensating controls (reduces risk)
        factors.compensating_controls_score = self._score_controls(
            has_esu, is_isolated, has_waf, custom_mitigations
        )

        # --- Compute weighted composite
        raw_score = (
            factors.eol_proximity_score * self.weights['eol_proximity'] +
            factors.vulnerability_score * self.weights['vulnerability'] +
            factors.deployment_scope_score * self.weights['deployment_scope'] +
            factors.business_criticality_score * self.weights['business_criticality'] +
            (1.0 - factors.compensating_controls_score) * self.weights['compensating_controls']
        )

        # Scale to 1-20
        composite = max(1, min(20, round(raw_score * 20)))

        # Determine severity band
        if composite <= 5:
            severity = 'low'
        elif composite <= 10:
            severity = 'moderate'
        elif composite <= 15:
            severity = 'high'
        else:
            severity = 'critical'

        # Generate recommendations
        recommendations = self._generate_recommendations(
            severity, eol_date, product_type, has_esu, factors
        )

        return RiskAssessment(
            composite_score=composite,
            severity=severity,
            factors=factors,
            rationale='; '.join(rationale_parts) if rationale_parts else 'No significant risk factors',
            recommendations=recommendations,
        )

    # =========================================================================
    # INDIVIDUAL FACTOR SCORERS
    # =========================================================================

    @staticmethod
    def _score_eol_proximity(eol_date: Optional[datetime], eos_date: Optional[datetime]) -> float:
        """Score EOL proximity: 0.0 = safe, 1.0 = long past EOL"""
        if eol_date is None:
            return 0.3  # Unknown EOL = moderate concern

        now = datetime.now(timezone.utc)
        if eol_date.tzinfo is None:
            eol_date = eol_date.replace(tzinfo=timezone.utc)

        days_until_eol = (eol_date - now).days

        if days_until_eol > 365:
            return 0.0      # 1+ year of support
        elif days_until_eol > 180:
            return 0.2      # 6-12 months
        elif days_until_eol > 90:
            return 0.4      # 3-6 months
        elif days_until_eol > 30:
            return 0.6      # 1-3 months
        elif days_until_eol > 0:
            return 0.8      # < 1 month
        elif days_until_eol > -180:
            return 0.9      # 0-6 months past EOL
        else:
            return 1.0      # 6+ months past EOL

    @staticmethod
    def _explain_eol_proximity(eol_date: Optional[datetime], score: float) -> str:
        """Generate human-readable EOL proximity explanation"""
        if eol_date is None:
            return "EOL date unknown"

        now = datetime.now(timezone.utc)
        if eol_date.tzinfo is None:
            eol_date = eol_date.replace(tzinfo=timezone.utc)

        days = (eol_date - now).days
        if days > 0:
            return f"EOL in {days} days ({eol_date.strftime('%Y-%m-%d')})"
        else:
            return f"EOL was {abs(days)} days ago ({eol_date.strftime('%Y-%m-%d')})"

    @staticmethod
    def _score_vulnerability(cvss_max: float, cve_count: int, exploit_available: bool) -> float:
        """Score vulnerability exposure: 0.0 = no vulns, 1.0 = critical+exploit"""
        if cve_count == 0 and cvss_max == 0:
            return 0.0

        base = min(cvss_max / 10.0, 1.0)  # CVSS 0-10 -> 0.0-1.0

        # Amplify for exploit availability
        if exploit_available:
            base = min(base * 1.3, 1.0)

        # Amplify for high CVE count
        if cve_count > 50:
            base = min(base + 0.2, 1.0)
        elif cve_count > 20:
            base = min(base + 0.1, 1.0)

        return round(base, 2)

    @staticmethod
    def _score_deployment(fleet_percentage: float, fleet_count: int) -> float:
        """Score deployment scope: 0.0 = single asset, 1.0 = entire fleet"""
        if fleet_percentage >= 0.75:
            return 1.0
        elif fleet_percentage >= 0.5:
            return 0.8
        elif fleet_percentage >= 0.25:
            return 0.6
        elif fleet_percentage >= 0.1:
            return 0.4
        elif fleet_percentage > 0 or fleet_count > 0:
            return 0.2
        return 0.0

    @staticmethod
    def _score_controls(has_esu: bool, is_isolated: bool, has_waf: bool, custom: int) -> float:
        """
        Score compensating controls (higher = more mitigation).
        This REDUCES risk, so it's subtracted in the composite.
        """
        score = 0.0
        if has_esu:
            score += 0.4      # ESU is significant mitigation
        if is_isolated:
            score += 0.3      # Network isolation
        if has_waf:
            score += 0.2      # WAF/proxy protection
        score += min(custom * 0.1, 0.3)  # Up to 0.3 for custom mitigations
        return min(score, 1.0)

    @staticmethod
    def _generate_recommendations(
        severity: str,
        eol_date: Optional[datetime],
        product_type: str,
        has_esu: bool,
        factors: RiskFactors,
    ) -> list:
        """Generate actionable recommendations based on risk assessment"""
        recs = []

        if severity == 'critical':
            recs.append("IMMEDIATE: Initiate emergency migration planning")
            if product_type in ('os', 'server_os') and not has_esu:
                recs.append("Consider purchasing Extended Security Updates (ESU) as interim measure")
            recs.append("Isolate affected systems from internet-facing networks if possible")

        elif severity == 'high':
            recs.append("PRIORITY: Schedule migration within 90 days")
            if factors.vulnerability_score > 0.7:
                recs.append("Apply available patches or virtual patching immediately")

        elif severity == 'moderate':
            recs.append("PLANNED: Include in next quarterly upgrade cycle")
            if eol_date:
                now = datetime.now(timezone.utc)
                if eol_date.tzinfo is None:
                    eol_date = eol_date.replace(tzinfo=timezone.utc)
                days = (eol_date - now).days
                if 0 < days <= 180:
                    recs.append(f"EOL approaching in {days} days — begin migration planning")

        elif severity == 'low':
            recs.append("MONITOR: No immediate action required")

        return recs
