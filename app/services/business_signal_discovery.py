import logging
import uuid
import re
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import List, Dict, Any, Optional, Tuple, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.schemas.business_signal import (
    SignalType,
    SignalClassification,
    SignalFreshness,
    BusinessSignal,
    SignalDiscoveryQuery,
)
from app.schemas.epistemic_evidence import IdentityMatchStatus
from app.services.research.entity_resolver import (
    EntityResolver,
    TargetCompanyAnchor,
    EntityResolutionResult,
)
from app.services.providers.search import unwrap_search_redirect
from app.models.evidence import SourceResult, Evidence, EvidenceType

logger = logging.getLogger("networkos")


class BusinessSignalConfig:
    STALE_THRESHOLD_DAYS: int = 365      # Operational deficits > 1 year old are historical, not current problems
    AGING_THRESHOLD_DAYS: int = 180      # 6 months threshold for aging signals
    DUPLICATE_SIMILARITY_THRESHOLD: float = 0.80  # 80% lexical token overlap indicates syndicated duplicate


class BusinessSignalDiscoveryService:
    """
    Live Business Signal Discovery & Temporal Evidence Pipeline.
    Discovers, validates provenance, deduplicates, and classifies operational business signals.
    """

    @staticmethod
    def build_signal_queries(
        company_name: str,
        aliases: Optional[List[str]] = None,
        website_domain: Optional[str] = None
    ) -> List[SignalDiscoveryQuery]:
        """
        Builds bounded, high-value, target-company-specific queries.
        Targets explicit operational challenges, disruptions, compliance, and official announcements.
        Prevents generic query explosion.
        """
        clean_company = company_name.strip()
        if not clean_company:
            return []

        queries: List[SignalDiscoveryQuery] = []

        # 1. Operational challenges, outages, and reliability
        queries.append(SignalDiscoveryQuery(
            query_text=f'"{clean_company}" ("outage" OR "downtime" OR "latency" OR "bottleneck" OR "service disruption" OR "incident")',
            intent="OPERATIONAL_RELIABILITY",
            target_company=clean_company,
            source_type="duckduckgo"
        ))

        # 2. Scaling, technical debt, and architecture bottlenecks
        queries.append(SignalDiscoveryQuery(
            query_text=f'"{clean_company}" ("scaling challenge" OR "technical debt" OR "infrastructure migration" OR "architecture bottleneck")',
            intent="SCALING_CHALLENGE",
            target_company=clean_company,
            source_type="duckduckgo"
        ))

        # 3. Public compliance, regulatory, or audit disclosures
        queries.append(SignalDiscoveryQuery(
            query_text=f'"{clean_company}" ("regulatory" OR "compliance audit" OR "security vulnerability" OR "investigation")',
            intent="REGULATORY_COMPLIANCE",
            target_company=clean_company,
            source_type="news_public"
        ))

        # 4. Official company announcements and press releases
        queries.append(SignalDiscoveryQuery(
            query_text=f'"{clean_company}" ("press release" OR "announcement" OR "operations" OR "infrastructure update")',
            intent="OFFICIAL_ANNOUNCEMENTS",
            target_company=clean_company,
            source_type="news_public"
        ))

        # 5. Targeted engineering / practitioner job postings (reveals technical initiatives)
        queries.append(SignalDiscoveryQuery(
            query_text=f'"{clean_company}" ("careers" OR "job opening") ("infrastructure" OR "reliability" OR "systems engineer")',
            intent="HIRING_INITIATIVES",
            target_company=clean_company,
            source_type="company_web"
        ))

        return queries

    @staticmethod
    def normalize_url(url: Optional[str]) -> str:
        """
        Normalizes URLs: unwraps search redirects, strips tracking query parameters,
        and standardizes lowercase domain and path formatting.
        """
        if not url:
            return ""

        unwrapped = unwrap_search_redirect(url.strip())
        try:
            parsed = urlparse(unwrapped)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]

            # Remove standard tracking query params
            query_params = parse_qs(parsed.query, keep_blank_values=False)
            filtered_params = {
                k: v for k, v in query_params.items()
                if not (k.startswith("utm_") or k in {"ref", "source", "fbclid", "gclid", "msclkid"})
            }
            clean_query = urlencode(filtered_params, doseq=True)

            clean_path = parsed.path.rstrip("/")
            if not clean_path:
                clean_path = "/"

            normalized = urlunparse((
                parsed.scheme.lower() or "https",
                netloc,
                clean_path,
                "",
                clean_query,
                ""
            ))
            return normalized
        except Exception:
            return unwrapped

    @staticmethod
    def extract_tokens(text: str) -> Set[str]:
        """Extracts normalized alphanumeric tokens for fuzzy deduplication."""
        stopwords = {
            "the", "and", "a", "an", "in", "on", "at", "to", "for", "of", "with",
            "is", "are", "was", "were", "by", "that", "this", "from", "it", "as"
        }
        tokens = set(re.findall(r'\b[a-zA-Z0-9]{3,}\b', text.lower()))
        return tokens - stopwords

    @classmethod
    def compute_jaccard_similarity(cls, text_a: str, text_b: str) -> float:
        """Computes lexical token Jaccard similarity between two passages."""
        tokens_a = cls.extract_tokens(text_a)
        tokens_b = cls.extract_tokens(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a.intersection(tokens_b))
        union = len(tokens_a.union(tokens_b))
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def assess_freshness(
        publication_date: Optional[datetime],
        stale_threshold_days: int = BusinessSignalConfig.STALE_THRESHOLD_DAYS,
        aging_threshold_days: int = BusinessSignalConfig.AGING_THRESHOLD_DAYS,
        reference_time: Optional[datetime] = None
    ) -> Tuple[SignalFreshness, bool]:
        """
        Assesses evidence freshness based on explicit publication date.
        Never fabricates or guesses missing dates.
        Flagged stale signals are retained for historical context but disallowed as active problems.
        """
        if publication_date is None:
            return SignalFreshness.UNDATED, False

        now = reference_time or datetime.now(timezone.utc)
        if publication_date.tzinfo is None:
            pub_dt = publication_date.replace(tzinfo=timezone.utc)
        else:
            pub_dt = publication_date

        age_days = (now - pub_dt).days
        if age_days < 0:
            age_days = 0

        if age_days > stale_threshold_days:
            return SignalFreshness.STALE, True
        elif age_days > aging_threshold_days:
            return SignalFreshness.AGING, False
        else:
            return SignalFreshness.FRESH, False

    @classmethod
    def classify_signal(
        cls,
        quoted_passage: str,
        entity_status: IdentityMatchStatus,
        target_company: str,
        source_title: Optional[str] = None
    ) -> Tuple[SignalType, SignalClassification, bool, str]:
        """
        Validates provenance and cautiously classifies discovered evidence.
        Distinguishes direct problem evidence, contextual signals, and cautious inferences.
        Does NOT equate finding a signal with proving an operational problem.
        """
        # 1. Identity association gate: Unmatched or ambiguous results are rejected
        if entity_status in ["UNMATCHED", "AMBIGUOUS"]:
            return (
                SignalType.GENERAL_ANNOUNCEMENT,
                SignalClassification.UNRELIABLE_OR_MISATTRIBUTED,
                False,
                f"Identity resolution failed ({entity_status}). Excluded from problem verification."
            )

        combined_text = f"{source_title or ''} {quoted_passage}".lower()

        # 2. Check for explicit neutral announcements (expansion, hiring, funding, partnerships)
        # Expansion is not proof of scaling problems. Job postings are not proof of reliability issues.
        is_hiring_announcement = any(term in combined_text for term in [
            "we are hiring", "job opening", "seeking experienced", "careers at",
            "open positions", "join our team", "hiring senior", "looking for kubernetes"
        ])

        is_expansion_announcement = any(term in combined_text for term in [
            "expands into", "opened new office", "announces new headquarters",
            "raised series", "funding round", "new partnership", "strategic alliance",
            "celebrating expansion", "opens regional office"
        ])

        # 3. Check for explicit operational deficit statements
        has_disruption = any(term in combined_text for term in [
            "outage", "service disruption", "downtime", "incident report",
            "system outage", "unavailability", "offline for"
        ])

        has_bottleneck_or_failure = any(term in combined_text for term in [
            "bottleneck in", "struggling with", "latency issue", "performance degradation",
            "query timeout", "architectural debt", "system failure", "failing to meet slas",
            "critical defect", "operational bottleneck"
        ])

        has_regulatory_issue = any(term in combined_text for term in [
            "regulatory fine", "compliance violation", "audit failure",
            "security breach", "enforcement action", "non-compliance notice"
        ])

        # Classification decision logic
        if has_disruption:
            return (
                SignalType.SERVICE_DISRUPTION,
                SignalClassification.DIRECT_PROBLEM_EVIDENCE,
                True,
                "Source explicitly documents public service disruption or system downtime affecting target."
            )
        elif has_bottleneck_or_failure:
            return (
                SignalType.OPERATIONAL_CHALLENGE,
                SignalClassification.DIRECT_PROBLEM_EVIDENCE,
                True,
                "Source explicitly states an operational bottleneck, latency issue, or architectural failure."
            )
        elif has_regulatory_issue:
            return (
                SignalType.REGULATORY_COMPLIANCE,
                SignalClassification.DIRECT_PROBLEM_EVIDENCE,
                True,
                "Source explicitly discloses a regulatory violation, audit penalty, or compliance defect."
            )
        elif is_hiring_announcement:
            return (
                SignalType.HIRING_INITIATIVE,
                SignalClassification.CONTEXTUAL_SIGNAL,
                False,
                "Public job posting / hiring need. Provides operational context; does NOT prove operational deficiency."
            )
        elif is_expansion_announcement:
            return (
                SignalType.CORPORATE_EXPANSION,
                SignalClassification.CONTEXTUAL_SIGNAL,
                False,
                "Corporate growth or expansion announcement. Stored as business context, NOT an operational problem."
            )
        else:
            return (
                SignalType.GENERAL_ANNOUNCEMENT,
                SignalClassification.CONTEXTUAL_SIGNAL,
                False,
                "General corporate announcement or informative context without explicit operational defect."
            )

    @classmethod
    def deduplicate_signals(
        cls,
        signals: List[BusinessSignal],
        similarity_threshold: float = BusinessSignalConfig.DUPLICATE_SIMILARITY_THRESHOLD
    ) -> Tuple[List[BusinessSignal], List[BusinessSignal]]:
        """
        Deduplicates identical URLs and substantially duplicate event reporting.
        Preserves genuinely independent corroborating sources.
        """
        unique_signals: List[BusinessSignal] = []
        duplicate_signals: List[BusinessSignal] = []

        seen_canonical_urls: Set[str] = set()

        for sig in signals:
            norm_url = cls.normalize_url(sig.source_url)
            sig.canonical_url = norm_url

            # 1. Exact URL deduplication
            if norm_url and norm_url in seen_canonical_urls:
                duplicate_signals.append(sig)
                continue

            # 2. Fuzzy lexical similarity deduplication (syndicated wire reports)
            is_content_dup = False
            for existing in unique_signals:
                sim = cls.compute_jaccard_similarity(sig.quoted_passage, existing.quoted_passage)
                if sim >= similarity_threshold:
                    # Same underlying text syndicated across domains; deduplicate to avoid inflation
                    is_content_dup = True
                    duplicate_signals.append(sig)
                    break

            if not is_content_dup:
                if norm_url:
                    seen_canonical_urls.add(norm_url)
                unique_signals.append(sig)

        return unique_signals, duplicate_signals

    @classmethod
    def evaluate_candidate_signal(
        cls,
        raw_reference: str,
        raw_text: str,
        target_company: str,
        target_domain: Optional[str] = None,
        source_title: Optional[str] = None,
        publication_date: Optional[datetime] = None,
        reference_time: Optional[datetime] = None
    ) -> BusinessSignal:
        """
        End-to-end evaluation of a single raw document or search snippet into a validated BusinessSignal.
        Enforces target entity resolution, freshness assessment, and cautious classification.
        """
        anchor = TargetCompanyAnchor(
            company_name=target_company,
            website_domain=target_domain
        )

        res = EntityResolver.resolve_company(
            anchor=anchor,
            candidate_url=raw_reference,
            candidate_title=source_title,
            candidate_text=raw_text
        )

        entity_status: IdentityMatchStatus = res.status

        signal_type, classification, explicitly_states_problem, rationale = cls.classify_signal(
            quoted_passage=raw_text,
            entity_status=entity_status,
            target_company=target_company,
            source_title=source_title
        )

        freshness_status, is_stale = cls.assess_freshness(
            publication_date=publication_date,
            reference_time=reference_time
        )

        # Stale operational problems cannot be presented as current operational problems
        if is_stale and explicitly_states_problem:
            rationale += f" [STALE: Published > {BusinessSignalConfig.STALE_THRESHOLD_DAYS} days ago; historical only]"

        domain = EntityResolver._extract_domain(raw_reference) or "unknown"
        norm_url = cls.normalize_url(raw_reference)

        confidence = 80 if entity_status == "MATCH_CONFIRMED" else (65 if entity_status == "PROBABLE" else 30)
        if is_stale:
            confidence = max(20, confidence - 25)

        return BusinessSignal(
            signal_id=f"sig-{uuid.uuid4().hex[:10]}",
            signal_type=signal_type,
            classification=classification,
            factual_description=(source_title or raw_text[:120]).strip(),
            source_url=raw_reference,
            source_title=source_title,
            publisher_domain=domain,
            publication_date=publication_date,  # Never fabricated
            discovery_timestamp=datetime.now(timezone.utc),
            quoted_passage=raw_text[:800],
            target_company=target_company,
            entity_association_status=entity_status,
            confidence=confidence,
            relevance_rationale=rationale,
            explicitly_states_problem=explicitly_states_problem and not is_stale,
            freshness_status=freshness_status,
            is_stale=is_stale,
            canonical_url=norm_url,
            metadata_={
                "matched_anchors": res.matched_anchors,
                "conflict_flags": res.conflict_flags,
                "resolution_notes": res.resolution_notes
            }
        )

    @classmethod
    async def persist_signals_to_pipeline(
        cls,
        db: AsyncSession,
        signals: List[BusinessSignal],
        contact_id: Optional[str] = None,
        research_task_id: Optional[str] = None
    ) -> List[Evidence]:
        """
        Integrates discovered signals into the existing SourceResult and Evidence tables.
        Applies deduplication to prevent duplicate persistence on repeated research runs.
        """
        persisted_evidence: List[Evidence] = []
        if not signals:
            return persisted_evidence

        # Check existing source references to prevent repeated research runs from duplicating records
        existing_refs: Set[str] = set()
        if contact_id:
            res_ev = await db.execute(select(Evidence.source_reference).where(Evidence.related_entity_id == contact_id))
            for row in res_ev.scalars().all():
                if row:
                    existing_refs.add(cls.normalize_url(row))

        for sig in signals:
            # Skip unreliable signals from problem verification persistence
            if sig.classification == SignalClassification.UNRELIABLE_OR_MISATTRIBUTED:
                continue

            norm_ref = cls.normalize_url(sig.source_url)
            if norm_ref in existing_refs:
                logger.info(f"BusinessSignalDiscoveryService: Skipping duplicate source reference '{norm_ref}' for contact {contact_id}")
                continue

            existing_refs.add(norm_ref)

            # Persist SourceResult
            sr_id = f"sr-sig-{uuid.uuid4().hex[:8]}"
            sr = SourceResult(
                id=sr_id,
                source_id=f"business_signal_{sig.publisher_domain}",
                research_task_id=research_task_id,
                query=f'"{sig.target_company}" signal',
                entity_searched=sig.target_company,
                raw_reference=sig.source_url,
                status="SUCCESS",
                extracted_data={
                    "title": sig.source_title,
                    "text": sig.quoted_passage,
                    "signal_type": sig.signal_type.value,
                    "classification": sig.classification.value,
                    "explicitly_states_problem": sig.explicitly_states_problem,
                    "is_stale": sig.is_stale,
                    "freshness_status": sig.freshness_status.value
                },
                metadata_={
                    "identity_match_status": "CONFIRMED" if sig.entity_association_status == "MATCH_CONFIRMED" else sig.entity_association_status,
                    "identity_match_confidence": sig.confidence,
                    "source_domain": sig.publisher_domain,
                    "is_stale": sig.is_stale,
                    "observed_date": sig.publication_date.isoformat() if sig.publication_date else None
                }
            )
            db.add(sr)
            await db.flush()

            # Persist Evidence
            ev_type = EvidenceType.SIGNAL if sig.classification == SignalClassification.CONTEXTUAL_SIGNAL else EvidenceType.FACT
            ev = Evidence(
                id=f"ev-sig-{uuid.uuid4().hex[:8]}",
                evidence_type=ev_type,
                claim=sig.factual_description,
                source_id=f"business_signal_{sig.publisher_domain}",
                source_reference=sig.source_url,
                observed_date=sig.publication_date,  # None if undated! Never fabricated
                retrieved_date=sig.discovery_timestamp,
                confidence=sig.confidence,
                source_result_id=sr.id,
                related_entity_id=contact_id
            )
            db.add(ev)
            persisted_evidence.append(ev)

        await db.commit()
        return persisted_evidence
