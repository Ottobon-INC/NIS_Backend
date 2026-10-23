import re
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.schemas.epistemic_evidence import (
    AtomicClaim,
    EvidenceRef,
    EpistemicStatus,
    ObservableAuditSignals,
    CommercialHypothesis,
    SourceAuthorityTier,
    IdentityMatchStatus,
    HiringState
)
from app.services.research.entity_resolver import EntityResolutionResult


class StoredSourceRecord(BaseModel):
    """Immutable record of an ingested source document in the Source Registry."""
    source_id: str
    url: str
    canonical_url: Optional[str] = None
    domain: str
    retrieval_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_text: str
    content_sha256: str
    authority_tier: SourceAuthorityTier = "UNVERIFIED_WEB"
    identity_resolution: Optional[EntityResolutionResult] = None


class VerificationIssue(BaseModel):
    """Specific reason why a claim was rejected or downgraded in status."""
    claim_id: str
    issue_type: str     # e.g., "QUOTE_NOT_FOUND", "SOURCE_ID_MISSING", "IDENTITY_AMBIGUOUS", "STALE_PAST_TENSE", "UNVERIFIED_TIER"
    message: str
    severity: str       # "FATAL" (forces UNSUPPORTED), "WARNING" (downgrades to PARTIALLY_SUPPORTED)


class VerifiedResearchDossier(BaseModel):
    """
    Immutable container of fully verified claims and explicitly separated hypotheses.
    Constructed anew by the verifier — never mutated from raw unvalidated LLM output.
    """
    subject_entity_id: str
    subject_type: str
    verified_claims: List[AtomicClaim] = Field(default_factory=list)
    partially_supported_claims: List[AtomicClaim] = Field(default_factory=list)
    conflicting_claims: List[AtomicClaim] = Field(default_factory=list)
    unsupported_claims: List[AtomicClaim] = Field(default_factory=list)
    unknown_claims: List[AtomicClaim] = Field(default_factory=list)
    commercial_hypotheses: List[CommercialHypothesis] = Field(default_factory=list)
    hiring_state: HiringState = "UNKNOWN"
    audit_issues: List[VerificationIssue] = Field(default_factory=list)


class ResearchVerifier:
    """
    Deterministic Epistemic Verification Engine.
    Enforces the 'Quote-is-not-Truth' standard:
    1. Verifies textual provenance (exact substring & offset validation).
    2. Enforces source authority rules (primary/reputable vs unverified web).
    3. Requires independent identity resolution (identity match != fact truth).
    4. Evaluates temporal and negation signals (e.g. 'former', 'stepped down').
    5. Reconstructs clean, immutable claims with derived epistemic status.
    """

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalizes whitespace and common unicode punctuation for robust exact matching."""
        if not text:
            return ""
        # Normalize non-breaking spaces and multi-whitespace
        t = re.sub(r'\s+', ' ', text)
        # Normalize smart quotes and dashes
        t = t.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
        t = t.replace('—', '-').replace('–', '-')
        return t.strip()

    @classmethod
    def check_quote_provenance(
        cls,
        quote: str,
        stored_text: str
    ) -> Tuple[bool, Optional[int], Optional[int]]:
        """
        Deterministically verifies that the verbatim quote exists within the stored raw text.
        Returns: (is_matched, start_offset, end_offset).
        """
        if not quote or not stored_text:
            return False, None, None

        norm_quote = cls._normalize_text(quote)
        norm_stored = cls._normalize_text(stored_text)

        if not norm_quote:
            return False, None, None

        # Try exact search
        idx = norm_stored.find(norm_quote)
        if idx != -1:
            return True, idx, idx + len(norm_quote)

        # Try case-insensitive search if exact fails
        idx_lower = norm_stored.lower().find(norm_quote.lower())
        if idx_lower != -1:
            return True, idx_lower, idx_lower + len(norm_quote)

        return False, None, None

    @classmethod
    def detect_temporal_negation(cls, predicate: str, quote: str, surrounding_context: str) -> bool:
        """
        Checks whether a quote asserting a CURRENT state is actually referring to a past/former state or expired signal.
        E.g. If predicate is CURRENT_ROLE, but text states 'Former VP', 'stepped down', or 'left in 2022'.
        If predicate is HIRING_STATUS, checks for expired postings ('closed', 'filled', 'expired').
        """
        if predicate not in ["CURRENT_ROLE", "CURRENT_COMPANY", "HIRING_STATUS"]:
            return False

        check_corpus = (quote + " " + surrounding_context).lower()
        past_indicators = [
            "former", "previously", "stepped down", "left the company",
            "served as", "prior to", "until 20", "retired", "ex-",
            "resigned", "departed", "was formerly", "transitioned from",
            "previously served", "held the role until", "past "
        ]
        if predicate == "HIRING_STATUS":
            expired_indicators = [
                "closed", "filled", "expired", "archived", "no longer accepting",
                "position filled", "requisition closed", "job closed", "inactive",
                "applications closed", "not currently hiring", "frozen"
            ] + past_indicators
            return any(ind in check_corpus for ind in expired_indicators)

        return any(ind in check_corpus for ind in past_indicators)

    @classmethod
    def check_claim_semantic_support(
        cls,
        claim: AtomicClaim,
        quote: str,
        surrounding_context: str = ""
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Deterministically verifies that the quote or surrounding sentence context
        semantically supports the claim value and does not misattribute a role to a different person.
        Returns: (is_supported, issue_type, message)
        """
        if not claim.value or not quote:
            return False, "EMPTY_CLAIM_OR_QUOTE", "Claim value or quote is empty."

        corpus = (quote + " " + surrounding_context).lower()
        val_clean = claim.value.strip().lower()

        # Stop words to filter out before token matching
        stop_words = {
            "a", "an", "the", "and", "or", "in", "at", "to", "for", "of", "with",
            "is", "as", "by", "on", "from", "that", "this", "our", "are", "was",
            "were", "been", "has", "have", "had", "will", "would", "can", "could",
            "its", "their", "into", "onto", "upon", "about"
        }

        # Generic technical and business descriptors that alone do not prove brand/product identity
        generic_descriptors = {
            "cloud", "data", "platform", "system", "solutions", "software", "services",
            "tools", "technologies", "management", "architecture", "infrastructure",
            "modern", "suite", "service", "digital", "enterprise", "global"
        }

        # Tokenize claim value into alphanumeric words
        val_tokens = [w for w in re.findall(r'[a-zA-Z0-9]+', val_clean) if len(w) > 2 and w not in stop_words]

        # Verify that essential tokens of the claimed value exist in the quote or sentence
        if val_tokens:
            matched_tokens = [t for t in val_tokens if t in corpus]
            ratio = len(matched_tokens) / len(val_tokens)

            # Check distinguishing non-generic tokens (e.g. 'snowflake' in 'Snowflake Data Cloud')
            distinguishing_tokens = [w for w in val_tokens if w not in generic_descriptors]
            if distinguishing_tokens:
                matched_dist = [t for t in distinguishing_tokens if t in corpus]
                if not matched_dist or (len(matched_dist) / len(distinguishing_tokens) < 0.5):
                    return False, "CLAIM_VALUE_NOT_IN_QUOTE", (
                        f"Verbatim quote does not mention distinguishing name '{distinguishing_tokens}' in '{claim.value}'."
                    )

            if ratio < 0.4:
                return False, "CLAIM_VALUE_NOT_IN_QUOTE", (
                    f"Verbatim quote does not mention or support claimed value '{claim.value}' "
                    f"(matched {len(matched_tokens)}/{len(val_tokens)} tokens)."
                )

        # Role specialization verification for executive roles
        if claim.predicate in ["CURRENT_ROLE", "PREVIOUS_ROLE"]:
            role_specialization_words = {
                "security", "information", "financial", "technology", "marketing",
                "operations", "operating", "revenue", "legal", "compliance",
                "people", "talent", "strategy", "commercial", "data", "engineering",
                "architect", "product", "sales", "design", "growth", "investment"
            }
            claimed_specs = [w for w in val_tokens if w in role_specialization_words]
            if claimed_specs:
                missing_specs = []
                for spec in claimed_specs:
                    # Check if spec word exists in corpus or common acronym
                    has_spec = (spec in corpus) or (spec == "technology" and ("cto" in corpus or "tech" in corpus)) or \
                               (spec == "financial" and "cfo" in corpus) or \
                               (spec == "security" and "ciso" in corpus) or \
                               (spec == "operating" and "coo" in corpus) or \
                               (spec == "revenue" and "cro" in corpus)
                    if not has_spec:
                        missing_specs.append(spec)
                if missing_specs:
                    return False, "CLAIM_VALUE_NOT_IN_QUOTE", (
                        f"Verbatim quote does not contain required functional role specialization {missing_specs} "
                        f"for claimed role '{claim.value}'."
                    )

        # Executive role misattribution check
        if claim.subject_type == "EXECUTIVE" and claim.predicate in ["CURRENT_ROLE", "PREVIOUS_ROLE", "BOARD_MEMBER", "EXECUTIVE_FACT"]:
            subj_name = claim.subject_entity_id.strip()
            subj_tokens = set(re.findall(r'[a-zA-Z]+', subj_name.lower()))

            # Words that cannot form a proper person name (pronouns, copulas, determiners, generic titles)
            grammatical_non_names = {
                "he", "she", "they", "it", "who", "whom", "whose", "this", "that",
                "the", "a", "an", "is", "was", "are", "were", "been", "has", "had", "have",
                "his", "her", "their", "its", "our", "mr", "mrs", "ms", "dr", "and", "or",
                "in", "at", "to", "for", "with", "as", "by", "from", "also", "then", "now",
                "currently", "previously", "formerly", "company", "firm", "founder", "leader"
            }

            # Check if quote mentions another person's name holding the claimed role
            escaped_role = re.escape(claim.value.strip())
            attr_pattern = re.compile(
                rf'(?:(?:named|appointed|promoted|hired|announced|is|serves as|became)\s+)?'
                rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)'
                rf'(?:,?\s+(?:as\s+)?(?:the\s+)?(?:is|was|serves as)\s+)?\s*{escaped_role}',
                re.IGNORECASE
            )
            attr_match = attr_pattern.search(quote)
            if attr_match:
                attributed_name = attr_match.group(1).strip()
                attr_tokens = set(re.findall(r'[a-zA-Z]+', attributed_name.lower()))
                substantive_tokens = attr_tokens - grammatical_non_names
                if len(substantive_tokens) >= 2 and not substantive_tokens.intersection(subj_tokens):
                    return False, "ROLE_ATTRIBUTED_TO_OTHER_PERSON", f"Role '{claim.value}' in quote is attributed to '{attributed_name}', not target executive '{subj_name}'."

        return True, None, None

    @classmethod
    def verify_single_claim(
        cls,
        claim: AtomicClaim,
        sources_registry: Dict[str, StoredSourceRecord]
    ) -> Tuple[AtomicClaim, List[VerificationIssue]]:
        """
        Recursively audits a single atomic claim against the source registry.
        Constructs a fresh AtomicClaim instance with deterministically derived epistemic status.
        """
        issues: List[VerificationIssue] = []

        # 1. Handle explicit unknown
        if claim.value is None or claim.value.strip().lower() in ["[unverified]", "unknown", "n/a", "none", "not disclosed"]:
            fresh_claim = AtomicClaim(
                claim_id=claim.claim_id,
                subject_entity_id=claim.subject_entity_id,
                subject_type=claim.subject_type,
                predicate=claim.predicate,
                value=None,
                epistemic_status="UNKNOWN",
                epistemic_rationale="Explicitly marked as unknown/not disclosed in evidence.",
                signals=ObservableAuditSignals(),
                evidence=[]
            )
            return fresh_claim, issues

        # 2. Evidence references check
        if not claim.evidence:
            issues.append(VerificationIssue(
                claim_id=claim.claim_id,
                issue_type="NO_EVIDENCE_ATTACHED",
                message=f"Claim '{claim.predicate}: {claim.value}' has zero supporting evidence references.",
                severity="FATAL"
            ))
            fresh_claim = AtomicClaim(
                claim_id=claim.claim_id,
                subject_entity_id=claim.subject_entity_id,
                subject_type=claim.subject_type,
                predicate=claim.predicate,
                value=claim.value,
                epistemic_status="UNSUPPORTED",
                epistemic_rationale="Rejected: No evidence references provided to support this claim.",
                signals=ObservableAuditSignals(),
                evidence=[]
            )
            return fresh_claim, issues

        validated_evidences: List[EvidenceRef] = []
        has_primary = False
        has_reputable = False
        identity_confirmed = True
        quote_failures = 0
        negation_detected = False

        for ev in claim.evidence:
            source = sources_registry.get(ev.source_id)
            if not source:
                issues.append(VerificationIssue(
                    claim_id=claim.claim_id,
                    issue_type="SOURCE_ID_MISSING",
                    message=f"Source ID '{ev.source_id}' does not exist in the stored source registry.",
                    severity="FATAL"
                ))
                continue

            # Verify source metadata validity (URL and domain)
            if not source.url or not (source.url.startswith("http://") or source.url.startswith("https://")) or not source.domain:
                issues.append(VerificationIssue(
                    claim_id=claim.claim_id,
                    issue_type="INVALID_SOURCE_METADATA",
                    message=f"Source {ev.source_id} has invalid or missing URL/domain metadata ('{source.url}').",
                    severity="FATAL"
                ))
                continue

            # Verify textual provenance
            matched, start_off, end_off = cls.check_quote_provenance(ev.verbatim_quote, source.raw_text)
            if not matched:
                quote_failures += 1
                issues.append(VerificationIssue(
                    claim_id=claim.claim_id,
                    issue_type="QUOTE_NOT_FOUND",
                    message=f"Verbatim quote '{ev.verbatim_quote[:60]}...' not found in stored content for source {ev.source_id}.",
                    severity="FATAL"
                ))
                continue

            # Verify quote offset alignment if offsets were explicitly provided
            if ev.char_offset_start is not None and ev.char_offset_end is not None:
                stored_slice = source.raw_text[ev.char_offset_start:ev.char_offset_end]
                if cls._normalize_text(stored_slice) != cls._normalize_text(ev.verbatim_quote):
                    issues.append(VerificationIssue(
                        claim_id=claim.claim_id,
                        issue_type="OFFSET_MISMATCH",
                        message=f"Provided character offsets [{ev.char_offset_start}:{ev.char_offset_end}] do not align with verbatim quote in source {ev.source_id}.",
                        severity="WARNING"
                    ))

            # Check semantic claim support within quote & surrounding context
            surrounding = ""
            if start_off is not None:
                ctx_start = max(0, start_off - 120)
                ctx_end = min(len(source.raw_text), (end_off or start_off) + 120)
                surrounding = source.raw_text[ctx_start:ctx_end]

            is_sem_supported, sem_issue_type, sem_msg = cls.check_claim_semantic_support(
                claim=claim,
                quote=ev.verbatim_quote,
                surrounding_context=surrounding
            )
            if not is_sem_supported:
                issues.append(VerificationIssue(
                    claim_id=claim.claim_id,
                    issue_type=sem_issue_type or "CLAIM_NOT_SUPPORTED_BY_QUOTE",
                    message=sem_msg or "Quote does not provide semantic support for claim value.",
                    severity="FATAL"
                ))
                continue

            # Check identity resolution on this source
            id_status: IdentityMatchStatus = "PROBABLE"
            if source.identity_resolution:
                id_status = source.identity_resolution.status
                if id_status in ["AMBIGUOUS", "UNMATCHED"]:
                    identity_confirmed = False
                    issues.append(VerificationIssue(
                        claim_id=claim.claim_id,
                        issue_type="IDENTITY_AMBIGUOUS",
                        message=f"Source {ev.source_id} has identity status '{id_status}', making it ineligible for factual attribution.",
                        severity="FATAL"
                    ))
                    continue

            # Check temporal negation (e.g. claimed current role, but quote says former)
            if cls.detect_temporal_negation(claim.predicate, ev.verbatim_quote, surrounding):
                negation_detected = True
                issues.append(VerificationIssue(
                    claim_id=claim.claim_id,
                    issue_type="STALE_PAST_TENSE",
                    message=f"Claim '{claim.predicate}' uses past tense or former affiliation phrasing in source {ev.source_id}.",
                    severity="WARNING"
                ))

            # Record source authority
            if source.authority_tier == "PRIMARY_OFFICIAL":
                has_primary = True
            elif source.authority_tier == "REPUTABLE_AGGREGATOR":
                has_reputable = True

            # Construct verified EvidenceRef with exact verified offsets
            validated_ev = EvidenceRef(
                source_id=ev.source_id,
                source_url=source.url,
                canonical_url=source.canonical_url or source.url,
                source_domain=source.domain,
                content_sha256=source.content_sha256,
                retrieval_timestamp=source.retrieval_timestamp,
                verbatim_quote=ev.verbatim_quote,
                char_offset_start=start_off,
                char_offset_end=end_off,
                source_authority=source.authority_tier,
                identity_status=id_status
            )
            validated_evidences.append(validated_ev)

        # Calculate de-duplicated independent corroboration
        unique_domains = set(e.source_domain.lower() for e in validated_evidences if e.source_domain)
        unique_hashes = set(e.content_sha256 for e in validated_evidences if e.content_sha256)
        independent_corroboration = min(len(unique_domains), len(unique_hashes)) if validated_evidences else 0

        if len(validated_evidences) > 1 and independent_corroboration <= 1:
            issues.append(VerificationIssue(
                claim_id=claim.claim_id,
                issue_type="SYNDICATED_OR_DUPLICATE_SOURCES",
                message=f"Claim has {len(validated_evidences)} citations, but only {independent_corroboration} independent source(s) due to shared domain or identical content hash.",
                severity="WARNING"
            ))

        # Synthesize final status based on multi-criteria policy
        if not validated_evidences:
            derived_status: EpistemicStatus = "UNSUPPORTED"
            rationale = "Rejected: Zero valid evidence references survived textual provenance, metadata, and identity checks."
        elif negation_detected:
            derived_status = "CONFLICTING"
            rationale = "Flagged CONFLICTING: Evidence text contains past-tense, expired, or former affiliation indicators."
        elif (has_primary or has_reputable) and identity_confirmed:
            derived_status = "VERIFIED"
            rationale = "VERIFIED: Provenance confirmed against authoritative/primary source with verified identity match."
        else:
            derived_status = "PARTIALLY_SUPPORTED"
            rationale = "PARTIALLY_SUPPORTED: Provenance confirmed, but source is unverified web or identity match is only probable."

        signals = ObservableAuditSignals(
            corroboration_count=independent_corroboration,
            has_primary_source=has_primary,
            has_reputable_source=has_reputable,
            identity_match_confirmed=identity_confirmed,
            freshest_evidence_date=max([e.retrieval_timestamp for e in validated_evidences]) if validated_evidences else None,
            has_contradictory_evidence=negation_detected
        )

        fresh_claim = AtomicClaim(
            claim_id=claim.claim_id,
            subject_entity_id=claim.subject_entity_id,
            subject_type=claim.subject_type,
            predicate=claim.predicate,
            value=claim.value,
            epistemic_status=derived_status,
            epistemic_rationale=rationale,
            signals=signals,
            evidence=validated_evidences
        )
        return fresh_claim, issues

    @classmethod
    def verify_dossier(
        cls,
        subject_entity_id: str,
        subject_type: str,
        raw_claims: List[AtomicClaim],
        sources_registry: Dict[str, StoredSourceRecord],
        hypotheses: Optional[List[CommercialHypothesis]] = None
    ) -> VerifiedResearchDossier:
        """
        Recursively audits a complete collection of claims and hypotheses for an executive or company.
        Constructs an immutable VerifiedResearchDossier partitioned by epistemic status.
        """
        verified: List[AtomicClaim] = []
        partially_supported: List[AtomicClaim] = []
        conflicting: List[AtomicClaim] = []
        unsupported: List[AtomicClaim] = []
        unknown: List[AtomicClaim] = []
        all_issues: List[VerificationIssue] = []

        # Track predicate values to detect inter-claim contradictions
        predicate_map: Dict[str, List[AtomicClaim]] = {}

        for raw_claim in raw_claims:
            v_claim, issues = cls.verify_single_claim(raw_claim, sources_registry)
            all_issues.extend(issues)

            if v_claim.predicate not in predicate_map:
                predicate_map[v_claim.predicate] = []
            predicate_map[v_claim.predicate].append(v_claim)

        # Detect cross-claim contradictions (e.g. two conflicting CURRENT_ROLE or CURRENT_COMPANY claims)
        for pred, claim_list in predicate_map.items():
            if pred in ["CURRENT_ROLE", "CURRENT_COMPANY", "HIRING_STATUS"]:
                valid_claims = [c for c in claim_list if c.epistemic_status in ["VERIFIED", "PARTIALLY_SUPPORTED"]]
                distinct_values = set(c.value for c in valid_claims if c.value)
                if len(distinct_values) > 1:
                    # Downgrade conflicting claims
                    for c in valid_claims:
                        c.epistemic_status = "CONFLICTING"
                        c.epistemic_rationale = f"Contradictory values detected for single-value predicate '{pred}': {distinct_values}"
                        all_issues.append(VerificationIssue(
                            claim_id=c.claim_id,
                            issue_type="CONTRADICTORY_PREDICATE_VALUES",
                            message=f"Multiple conflicting values detected for {pred}: {distinct_values}",
                            severity="WARNING"
                        ))

        # Partition claims into final containers
        for raw_claim in raw_claims:
            # retrieve audited version from map
            matching = [c for c in predicate_map[raw_claim.predicate] if c.claim_id == raw_claim.claim_id]
            if not matching:
                continue
            c = matching[0]

            if c.epistemic_status == "VERIFIED":
                verified.append(c)
            elif c.epistemic_status == "PARTIALLY_SUPPORTED":
                partially_supported.append(c)
            elif c.epistemic_status == "CONFLICTING":
                conflicting.append(c)
            elif c.epistemic_status == "UNKNOWN":
                unknown.append(c)
            else:
                unsupported.append(c)

        # Derive overall hiring state from verified claims
        hiring_state: HiringState = "UNKNOWN"
        hiring_claims = predicate_map.get("HIRING_STATUS", [])
        verified_hiring = [c for c in hiring_claims if c.epistemic_status in ["VERIFIED", "PARTIALLY_SUPPORTED"]]
        if any(c.epistemic_status == "CONFLICTING" for c in hiring_claims):
            hiring_state = "CONFLICTING"
        elif verified_hiring:
            val = (verified_hiring[0].value or "").upper()
            if "ACTIVE" in val:
                hiring_state = "ACTIVE"
            elif "INACTIVE" in val or "0" in val:
                hiring_state = "INACTIVE"
            else:
                hiring_state = "UNKNOWN"

        # Explicitly validate that hypotheses are tagged with HYPOTHESIS status
        clean_hypotheses: List[CommercialHypothesis] = []
        if hypotheses:
            for h in hypotheses:
                clean_hypotheses.append(
                    CommercialHypothesis(
                        hypothesis_id=h.hypothesis_id,
                        target_entity_id=h.target_entity_id,
                        trigger_claim_ids=h.trigger_claim_ids,
                        inferred_pain_point=h.inferred_pain_point,
                        ottobon_capability_offering=h.ottobon_capability_offering,
                        delivery_risk_assessment=h.delivery_risk_assessment,
                        estimated_effort_hours=h.effort_estimate if hasattr(h, "effort_estimate") else h.estimated_effort_hours,
                        pricing_scenario=h.pricing_scenario,
                        epistemic_status="HYPOTHESIS"
                    )
                )

        return VerifiedResearchDossier(
            subject_entity_id=subject_entity_id,
            subject_type=subject_type,
            verified_claims=verified,
            partially_supported_claims=partially_supported,
            conflicting_claims=conflicting,
            unsupported_claims=unsupported,
            unknown_claims=unknown,
            commercial_hypotheses=clean_hypotheses,
            hiring_state=hiring_state,
            audit_issues=all_issues
        )
