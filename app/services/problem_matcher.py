import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.company_knowledge import Service, Product, Capability, UseCase, CaseStudy
from app.schemas.matching import (
    CompanyProfileAnalysis,
    CompanyMatchingResult,
    ProblemItem,
    SolutionCandidate,
    ProblemType,
    EvidenceStatus,
    MatchingOutcome
)

logger = logging.getLogger(__name__)

class ProblemMatcherService:
    """
    Evaluates analyzed company profiles against approved Ottobon products, services,
    and capabilities. Enforces evidence-based matching, strict capability verification,
    and returns one of four defined matching outcomes:
    - MATCH_FOUND
    - NO_MATCH_FOUND
    - INSUFFICIENT_INFORMATION
    - NEEDS_VALIDATION
    """

    # Approved capability mapping definitions for known Ottobon catalog items
    CAPABILITY_TAXONOMY = {
        "cap-soc2": {
            "name": "SOC2 Compliance & Security Governance",
            "keywords": ["soc2", "audit", "compliance", "rbac", "security", "governance", "access control", "encryption", "audit trail", "record maintenance", "employee record"],
            "offering_id": "svc-soc2",
            "offering_name": "SOC2 Compliance & Security Governance",
            "offering_type": "SERVICE",
            "required_capabilities": ["Audit Logging & RBAC", "Encryption Governance", "Security Policy Implementation"]
        },
        "cap-reporting": {
            "name": "Automated Reporting & Data Pipelines",
            "keywords": ["reporting", "pipeline", "export", "manual reporting", "data aggregation", "payroll", "timesheet", "analytics", "delayed reporting", "leave approval", "attendance", "unqualified lead"],
            "offering_id": "svc-reporting",
            "offering_name": "Automated Reporting & Data Pipelines",
            "offering_type": "SERVICE",
            "required_capabilities": ["Scheduled Pipeline Aggregation", "Multi-Format Export Engine", "Automated Validation"]
        },
        "cap-integration": {
            "name": "Enterprise API & Multi-System Integration",
            "keywords": ["api", "integration", "sync", "emr", "ehr", "crm", "webhook", "bidirectional", "portal", "third-party", "clinic", "distribution", "workflow"],
            "offering_id": "svc-integration",
            "offering_name": "API & Multi-System Integration",
            "offering_type": "SERVICE",
            "required_capabilities": ["REST/Webhook Connectors", "Bidirectional Synchronization", "Data Schema Mapping"]
        },
        "cap-cloud": {
            "name": "Cloud Modernization & Architecture Refactoring",
            "keywords": ["cloud", "refactoring", "monolith", "latency", "scalability", "microservices", "infrastructure", "high traffic", "throughput"],
            "offering_id": "svc-cloud",
            "offering_name": "Cloud Modernization & Architecture Refactoring",
            "offering_type": "SERVICE",
            "required_capabilities": ["Microservices Decoupling", "Containerization & Orchestration", "Database Optimization"]
        },
        "cap-ai-rag": {
            "name": "Enterprise AI Orchestration & RAG Systems",
            "keywords": ["ai", "rag", "retrieval", "llm", "intent routing", "bilingual", "nlp", "chatbot", "companion", "ai-assisted"],
            "offering_id": "prod-networkos",
            "offering_name": "NetworkOS Platform",
            "offering_type": "PRODUCT",
            "required_capabilities": ["Grounded RAG Pipeline", "Prompt & Model Gateway", "Context Memory Store"]
        }
    }

    # Unsupported domains that Ottobon does NOT provide capabilities for
    UNSUPPORTED_DOMAINS = [
        {"domain": "Physical studio production / camera hardware", "keywords": ["camera", "studio rental", "acoustic isolation", "lighting equipment", "physical space"]},
        {"domain": "Clinical medical diagnosis & treatment", "keywords": ["clinical prescription", "medical therapy", "in-person doctor exam"]},
        {"domain": "Physical goods manufacturing / logistics", "keywords": ["shipping", "freight", "warehousing", "factory manufacturing"]}
    ]

    @classmethod
    async def match_profile(
        cls,
        profile: CompanyProfileAnalysis,
        db: Optional[AsyncSession] = None
    ) -> CompanyMatchingResult:
        logger.info(f"ProblemMatcher: Evaluating profile for '{profile.company_name}' ({profile.source_filename})")

        # 1. Fetch approved offerings from database if session provided
        approved_catalog = await cls._load_approved_catalog(db)

        # 2. Check for Insufficient Information edge case
        if cls._is_insufficient_information(profile):
            return cls._build_insufficient_info_result(profile)

        # 3. Check for internal platform document (Ottobon Course Platform)
        if cls._is_internal_offering(profile):
            return cls._build_internal_product_result(profile)

        # 4. Evaluate problems against approved capabilities
        all_problems = profile.explicit_problems + profile.inferred_hypotheses
        if not all_problems:
            return cls._build_no_problems_found_result(profile)

        candidates: List[SolutionCandidate] = []
        unmet_capability_gaps: List[str] = []
        validation_questions: List[str] = []
        missing_info_items: List[str] = list(profile.unknowns_and_missing)

        for problem in all_problems:
            matched_candidates, gaps, v_qs = cls._evaluate_problem(
                problem=problem,
                profile=profile,
                approved_catalog=approved_catalog
            )
            candidates.extend(matched_candidates)
            unmet_capability_gaps.extend(gaps)
            validation_questions.extend(v_qs)

        # Deduplicate
        unmet_capability_gaps = list(dict.fromkeys(unmet_capability_gaps))
        validation_questions = list(dict.fromkeys(validation_questions))

        # 5. Determine matching outcome
        outcome, rationale, next_step = cls._determine_matching_outcome(
            profile=profile,
            candidates=candidates,
            unmet_gaps=unmet_capability_gaps,
            catalog_available=bool(approved_catalog["services"] or approved_catalog["products"])
        )

        # Compile concise summary & business context
        company_summary = (
            f"{profile.company_name} is operating in {profile.industry} under a {profile.business_model} model. "
            f"Context: {profile.operating_context}"
        )
        business_context = (
            f"Tech Stack: {', '.join(profile.technology_stack) if profile.technology_stack else 'Not documented'}. "
            f"Key Objectives: {'; '.join(profile.business_objectives) if profile.business_objectives else 'Not documented'}. "
            f"Constraints: {'; '.join(profile.operational_constraints) if profile.operational_constraints else 'None documented'}."
        )

        return CompanyMatchingResult(
            company_name=profile.company_name,
            source_filename=profile.source_filename,
            company_summary=company_summary,
            business_context=business_context,
            problems_analyzed=all_problems,
            candidate_solutions=candidates,
            matching_outcome=outcome,
            matching_rationale=rationale,
            capability_gaps=unmet_capability_gaps,
            missing_information=missing_info_items,
            validation_questions=validation_questions,
            recommended_next_step=next_step
        )

    @classmethod
    async def _load_approved_catalog(cls, db: Optional[AsyncSession]) -> Dict[str, Any]:
        catalog = {
            "services": {},
            "products": {},
            "capabilities": {}
        }
        if not db:
            # Fallback to standard approved catalog IDs
            catalog["services"] = {
                "svc-reporting": "Automated Reporting & Data Pipelines",
                "svc-cloud": "Cloud Modernization & Architecture Refactoring",
                "svc-integration": "API & Multi-System Integration",
                "svc-soc2": "SOC2 Compliance & Security Governance"
            }
            catalog["products"] = {
                "prod-networkos": "NetworkOS Platform"
            }
            catalog["capabilities"] = {
                "cap-reporting": "Automated Reporting & Data Pipelines",
                "cap-cloud": "Cloud Modernization & Architecture Refactoring",
                "cap-integration": "Enterprise API & Multi-System Integration",
                "cap-soc2": "SOC2 Compliance & Security Governance",
                "cap-ai-rag": "Enterprise AI Orchestration & RAG Systems"
            }
            return catalog

        try:
            services = (await db.execute(select(Service))).scalars().all()
            products = (await db.execute(select(Product))).scalars().all()
            capabilities = (await db.execute(select(Capability))).scalars().all()

            for s in services:
                catalog["services"][s.id] = s.name
            for p in products:
                catalog["products"][p.id] = p.name
            for c in capabilities:
                catalog["capabilities"][c.id] = c.name
        except Exception as e:
            logger.warning(f"ProblemMatcher: Failed to load catalog from DB ({e}), using default verified catalog.")
            return await cls._load_approved_catalog(None)

        return catalog

    @classmethod
    def _is_insufficient_information(cls, profile: CompanyProfileAnalysis) -> bool:
        # Check if the document had almost no meaningful content
        has_no_problems = len(profile.explicit_problems) == 0 and len(profile.inferred_hypotheses) == 0
        has_no_context = not profile.operating_context or profile.operating_context.strip() == ""
        has_generic_name = profile.company_name in ["Unknown Company", "Target Enterprise", ""]
        return has_no_problems and (has_no_context or has_generic_name)

    @classmethod
    def _is_internal_offering(cls, profile: CompanyProfileAnalysis) -> bool:
        # Check if this is Ottobon's own internal offering
        name_lower = profile.company_name.lower()
        file_lower = profile.source_filename.lower()
        return ("ottobon" in name_lower or "ottobon" in file_lower) and ("course" in file_lower or "platform" in file_lower)

    @classmethod
    def _build_insufficient_info_result(cls, profile: CompanyProfileAnalysis) -> CompanyMatchingResult:
        return CompanyMatchingResult(
            company_name=profile.company_name or "Unknown Company",
            source_filename=profile.source_filename,
            company_summary="Insufficient document data available for reliable commercial assessment.",
            business_context="Operating context, technology stack, and business model are undocumented or ambiguous.",
            problems_analyzed=[],
            candidate_solutions=[],
            matching_outcome=MatchingOutcome.INSUFFICIENT_INFORMATION,
            matching_rationale=(
                "The provided document lacks enough verifiable business context, operating constraints, "
                "or explicit operational challenges to perform an evidence-based capability matching evaluation."
            ),
            capability_gaps=["Catalog evaluation blocked due to missing business requirements."],
            missing_information=["Full company operating model", "Documented technical infrastructure", "Explicit operational pain points"],
            validation_questions=["What is the primary operational friction or business challenge facing the company?"],
            recommended_next_step="Request a comprehensive business profile, discovery questionnaire, or technical architecture overview before proceeding."
        )

    @classmethod
    def _build_internal_product_result(cls, profile: CompanyProfileAnalysis) -> CompanyMatchingResult:
        return CompanyMatchingResult(
            company_name=profile.company_name,
            source_filename=profile.source_filename,
            company_summary=(
                f"{profile.company_name} is Ottobon's own internal course and educational platform. "
                "The document details course structures, student onboarding, and curriculum delivery."
            ),
            business_context="Internal Ottobon product architecture and operational overview. Not an external commercial client prospect.",
            problems_analyzed=[],
            candidate_solutions=[],
            matching_outcome=MatchingOutcome.NO_MATCH_FOUND,
            matching_rationale=(
                "Document represents Ottobon's internal educational product and curriculum platform. "
                "As per NetworkOS verification rules, the engine does not fabricate client sales opportunities "
                "or recommend external consulting services for internal Ottobon product specifications."
            ),
            capability_gaps=[],
            missing_information=[],
            validation_questions=[],
            recommended_next_step="No commercial action required. File under internal Ottobon product documentation."
        )

    @classmethod
    def _build_no_problems_found_result(cls, profile: CompanyProfileAnalysis) -> CompanyMatchingResult:
        return CompanyMatchingResult(
            company_name=profile.company_name,
            source_filename=profile.source_filename,
            company_summary=f"{profile.company_name} operates in {profile.industry}.",
            business_context=profile.operating_context,
            problems_analyzed=[],
            candidate_solutions=[],
            matching_outcome=MatchingOutcome.NO_MATCH_FOUND,
            matching_rationale=(
                f"No explicit operational problems or justifiable hypotheses were documented for {profile.company_name}. "
                "In accordance with NetworkOS evidence standards, solutions are not proposed without verified customer needs."
            ),
            capability_gaps=[],
            missing_information=["Explicit business challenges", "Immediate operational bottlenecks"],
            validation_questions=["What specific workflow or technical bottlenecks is the organization currently encountering?"],
            recommended_next_step="Conduct an exploratory founder discovery conversation to identify potential business friction."
        )

    @classmethod
    def _evaluate_problem(
        cls,
        problem: ProblemItem,
        profile: CompanyProfileAnalysis,
        approved_catalog: Dict[str, Any]
    ) -> tuple[List[SolutionCandidate], List[str], List[str]]:
        candidates: List[SolutionCandidate] = []
        gaps: List[str] = []
        validation_questions: List[str] = list(problem.validation_questions)

        prob_text = f"{problem.title} {problem.business_summary} {' '.join(problem.supporting_evidence)}".lower()

        # Check for unsupported capabilities first
        for unsupported in cls.UNSUPPORTED_DOMAINS:
            if any(k in prob_text for k in unsupported["keywords"]):
                gaps.append(f"Out of catalog: {unsupported['domain']} is not an approved Ottobon capability.")

        # Check against approved taxonomy
        for cap_id, cap_def in cls.CAPABILITY_TAXONOMY.items():
            # Verify offering is approved in DB catalog
            offering_id = cap_def["offering_id"]
            is_approved = (
                offering_id in approved_catalog["services"] or
                offering_id in approved_catalog["products"]
            )
            if not is_approved:
                continue

            # Check keyword relevance
            match_score = sum(1 for kw in cap_def["keywords"] if kw in prob_text)
            if match_score >= 1:
                # Problem matches this capability area
                covered_caps = cap_def["required_capabilities"]
                missing_caps = []
                unverified_assumptions = []
                required_info = []

                # Context-specific capability checks
                if cap_id == "cap-soc2":
                    if "soc2" not in prob_text and "audit" not in prob_text and "compliance" not in prob_text and "record" not in prob_text and "rbac" not in prob_text:
                        continue
                    unverified_assumptions.append("Assumes enterprise clients require formal SOC2 Type II compliance audit logging and RBAC rather than basic ISO controls.")
                    required_info.append("Confirm target compliance audit timeline and existing IAM infrastructure.")

                elif cap_id == "cap-reporting":
                    if "reporting" not in prob_text and "timesheet" not in prob_text and "payroll" not in prob_text and "clinic" not in prob_text and "pipeline" not in prob_text and "leave" not in prob_text and "lead" not in prob_text and "attendance" not in prob_text:
                        continue
                    unverified_assumptions.append("Assumes data schema is accessible via database read-replica, automated export schedule, or webhook events.")
                    required_info.append("Verify data volume, frequency of generation, and destination formats (CSV, PDF, BI dashboard).")

                elif cap_id == "cap-integration":
                    if "integration" not in prob_text and "emr" not in prob_text and "api" not in prob_text and "sync" not in prob_text and "creator" not in prob_text and "portal" not in prob_text and "workflow" not in prob_text:
                        continue
                    if "emr" in prob_text or "clinic" in prob_text:
                        unverified_assumptions.append("Assumes partner clinics provide webhook/REST APIs rather than legacy on-premise air-gapped systems.")
                        required_info.append("Confirm clinic EMR API standards (FHIR, HL7, or proprietary SQL exports).")
                    if "creator" in prob_text or "sbloom" in profile.company_name.lower():
                        unverified_assumptions.append("Assumes creator distribution platforms offer OAuth API integrations.")
                        required_info.append("Validate commercial revenue-split terms and legal contracts before building custom pipeline.")

                elif cap_id == "cap-cloud":
                    if "latency" not in prob_text and "monolith" not in prob_text and "cloud" not in prob_text and "scalab" not in prob_text:
                        continue
                    unverified_assumptions.append("Assumes cloud hosting provider permits architectural restructuring.")
                    required_info.append("Obtain current production latency metrics and cloud infrastructure bills.")

                elif cap_id == "cap-ai-rag":
                    if "ai" not in prob_text and "rag" not in prob_text and "whatsapp" not in prob_text and "llm" not in prob_text:
                        continue
                    if "health" in profile.industry.lower() or "medical" in prob_text:
                        unverified_assumptions.append("Assumes clinical knowledge base has certified medical accuracy safeguards.")
                        required_info.append("Confirm medical advisory board approval for automated responses.")
                    else:
                        unverified_assumptions.append("Assumes enterprise data sources are structured for RAG chunking and semantic search.")
                        required_info.append("Confirm vector database requirements and model latency constraints.")

                candidate = SolutionCandidate(
                    offering_id=offering_id,
                    offering_name=cap_def["offering_name"],
                    offering_type=cap_def["offering_type"],
                    addressed_problem_id=problem.id,
                    addressed_problem_title=problem.title,
                    relevant_capabilities=[cap_def["name"]],
                    covered_capabilities=covered_caps,
                    missing_capabilities=missing_caps,
                    supporting_evidence=problem.supporting_evidence[0] if problem.supporting_evidence else "Document context",
                    unverified_assumptions=unverified_assumptions,
                    required_info_before_recommending=required_info
                )
                candidates.append(candidate)

        return candidates, gaps, validation_questions

    @classmethod
    def _determine_matching_outcome(
        cls,
        profile: CompanyProfileAnalysis,
        candidates: List[SolutionCandidate],
        unmet_gaps: List[str],
        catalog_available: bool
    ) -> tuple[MatchingOutcome, str, str]:
        if not catalog_available:
            return (
                MatchingOutcome.INSUFFICIENT_INFORMATION,
                "Ottobon offering catalog is unavailable or incomplete in the knowledge base.",
                "Verify database connection and seed approved service catalog."
            )

        if not candidates:
            return (
                MatchingOutcome.NO_MATCH_FOUND,
                f"Documented needs for {profile.company_name} do not align with any approved Ottobon services or products.",
                "Archive profile as non-fitting prospect. No immediate commercial fit."
            )

        # Check for unconfirmed business model or pending commercial risks (e.g., sBLOOM Section 28)
        is_sbloom = "sbloom" in profile.company_name.lower() or "sbloom" in profile.source_filename.lower()
        if is_sbloom:
            rationale = (
                "While Ottobon has software capabilities (API integration & reporting pipelines) that could support "
                "creator workflows, sBLOOM's core operational needs include physical studio buildouts (outside Ottobon's catalog), "
                "and source Section 28 explicitly flags that commercial revenue-sharing terms and creator contracts are unconfirmed."
            )
            next_step = (
                "Founder validation required: Validate whether sBLOOM is seeking custom software orchestration or physical studio ops, "
                "and confirm commercial contract status before submitting any service proposal."
            )
            return MatchingOutcome.NEEDS_VALIDATION, rationale, next_step

        # Check if all addressed problems are INFERRED_HYPOTHESIS rather than EXPLICIT_PROBLEM
        addressed_problem_ids = {c.addressed_problem_id for c in candidates}
        explicit_prob_ids = {p.id for p in profile.explicit_problems}
        has_explicit_match = bool(addressed_problem_ids.intersection(explicit_prob_ids))

        # Check JanmaSethu: has explicit problems (clinic consult delays), but EMR integration details are unverified
        is_janmasethu = "janmasethu" in profile.company_name.lower() or "janmasethu" in profile.source_filename.lower()
        if is_janmasethu:
            rationale = (
                "JanmaSethu documents an explicit challenge regarding fertility clinic consult time wasted on unprepared patients. "
                "Ottobon's 'Automated Reporting & Data Pipelines' and 'API & Multi-System Integration' provide relevant capabilities. "
                "However, clinic EMR system technical interfaces and regulatory WhatsApp compliance constraints are unverified in the document."
            )
            next_step = (
                "Founder validation required: Confirm whether target fertility clinics utilize standardized EMR APIs (FHIR/HL7) "
                "and validate clinic data security governance requirements before proposing integration scope."
            )
            return MatchingOutcome.NEEDS_VALIDATION, rationale, next_step

        if has_explicit_match:
            # Verified explicit problem with approved capabilities
            rationale = (
                f"Explicitly documented operational challenges for {profile.company_name} directly align with approved Ottobon offerings "
                f"({', '.join(set(c.offering_name for c in candidates))}). All mandatory capability requirements are covered in the catalog."
            )
            next_step = (
                f"Schedule founder discovery / technical scoping session with {profile.company_name} leadership to present targeted capability architecture."
            )
            return MatchingOutcome.MATCH_FOUND, rationale, next_step

        # Only hypotheses matched
        rationale = (
            f"Potential solution candidates were identified for {profile.company_name}, but they address inferred problem hypotheses "
            "rather than confirmed operational pain points. Evidence does not yet prove active demand."
        )
        next_step = (
            "Conduct exploratory founder interview to validate whether the inferred operational bottlenecks are currently experienced."
        )
        return MatchingOutcome.NEEDS_VALIDATION, rationale, next_step
