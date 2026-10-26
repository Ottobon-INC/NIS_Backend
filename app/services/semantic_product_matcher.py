import logging
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from app.core.config import settings
from app.schemas.matching import (
    MatchingOutcome,
    ProductMatchItem,
    SemanticProductMatchResponse
)

logger = logging.getLogger("networkos.semantic_matcher")

class SemanticProductMatcherService:
    """
    Semantic Problem & Product Matching Service.
    Analyzes connection business problems and performs semantic mapping
    against our product catalog.

    If no product provides a suitable solution, explicitly returns:
    - matching_outcome: "NO_MATCH_FOUND"
    - suggested_status: "No matches found"
    with transparent rationale detailing the capability gap.
    """

    # Canonical product catalog containing ONLY our authentic application products
    PRODUCT_CATALOG: List[Dict[str, Any]] = [
        {
            "id": "prod-janmasethu",
            "name": "JanmaSethu",
            "tagline": "Bridge to Parenthood & Digital Clinic Practice Management",
            "category": "Healthtech & Digital Health Solutions",
            "description": (
                "A journey-aware healthtech platform and digital clinic management solution guiding patients and clinicians. "
                "Features clinician-reviewed knowledge, Sakhi AI bilingual companion (English & Telugu) on Web & WhatsApp, "
                "and a standalone B2B clinic portal with patient preparedness scoring, digital patient management, "
                "and structured intake pipelines for doctor consultations and specialty clinics."
            ),
            "target_audience": "Practicing doctors, specialty clinics, hospitals, and patients seeking structured healthcare guidance",
            "business_model": "B2B Clinic Patient Management SaaS & B2C Healthcare Subscriptions",
            "problem_domains": [
                "Development of a digital tool for patient management in gastroenterology and clinical specialty practices.",
                "Specialty clinics and doctors wasting clinical consultation hours dealing with unqualified or unprepared patient inquiries.",
                "Doctor-patient communication gaps, absence of patient preparedness scoring, and unintegrated clinic intake pipelines.",
                "Language bias and regional accessibility barriers where standard healthcare platforms are English-only.",
                "Need for structured digital patient management, appointment intake, and tracking workflows integrated into clinic practices."
            ],
            "semantic_keywords": [
                "patient management", "digital tool", "gastroenterology", "doctor", "clinic", "patient", "patients",
                "healthtech", "clinical", "hospital", "patient portal", "doctor consultation", "preparedness score",
                "fertility", "maternity", "healthcare lead", "prenatal", "gynecology", "bilingual", "medical tool"
            ],
            "key_features": [
                "Digital Patient Management & Clinical Practice Portal",
                "Patient Preparedness Scoring & Structured Intake Pipelines",
                "Sakhi AI Healthcare Chat Companion (Web & WhatsApp)",
                "Bilingual Experience (Native English and Regional interface)",
                "Specialized Clinical Trackers & Patient Engagement Workflows"
            ],
            "unsupported_domains": [
                "physical surgery", "clinical pharmaceutical prescription compounding", "laboratory embryology hardware",
                "in-person hospital surgical operations"
            ]
        },
        {
            "id": "prod-ottobon-courses",
            "name": "Ottobon Course Platform",
            "tagline": "Don't just watch. Build. Structured AI-native learning for practical upskilling",
            "category": "AI-Native EdTech & Upskilling",
            "description": (
                "A structured, AI-native guided course and upskilling environment inside the Ottobon Academy ecosystem "
                "converting learners from passive tutorial consumption to practical software and professional capability building. Built on "
                "the 4-stage framework: Learn -> Comprehend -> Articulate -> Apply, with live AI doubt clarification, "
                "assessment checkpoints, certification sandboxes, and cohort learning management."
            ),
            "target_audience": "Software developers, engineering students, career switchers, technical teams, professional coaches, corporate trainers, and certification institutes",
            "business_model": "Cohort Tuition, Self-Paced Course Licenses, and Enterprise Academy Tracks",
            "problem_domains": [
                "Professional training institutes, coaches, and certification academies needing structured digital delivery, AI-assisted interactive learning, and automated assessment workflows.",
                "Training programs and coaching certifications struggling with manual delivery and lacking structured, AI-guided interactive curriculum.",
                "Learners experiencing tutorial fatigue: watching endless videos but unable to build independent software projects or pass practical assessments.",
                "Passive video consumption creating false confidence without proof of practical comprehension.",
                "Absence of structured validation, immediate AI doubt clarification, and hands-on coding and practical feedback.",
                "Technical team onboarding friction and software engineering upskilling bottlenecks."
            ],
            "semantic_keywords": [
                "tutorial fatigue", "learning", "upskilling", "course", "education", "edtech", "coding",
                "software engineering", "doubt clarification", "ai tutor", "capstone", "code sandbox",
                "curriculum", "technical training", "developer education", "student", "academy", "programming",
                "coaching", "coach", "certification", "training program", "leadership training", "emotional intelligence",
                "certification program", "coach certification", "cohort", "interactive learning", "trainer"
            ],
            "key_features": [
                "4-Stage Learning Framework (Learn -> Comprehend -> Articulate -> Apply)",
                "AI-Assisted Interactive Doubt Clarification & Intelligent Tutor",
                "Automated Assessment Checkpoints & Certification Sandboxes",
                "Hands-on Project & Capstone Building Workspaces",
                "Cohort Engagement, Peer Collaboration & Learning Streaks"
            ],
            "unsupported_domains": [
                "primary school k-12 education", "physical athletics coaching", "civil service competitive exam test prep"
            ]
        },
        {
            "id": "prod-sbloom",
            "name": "sBLOOM",
            "tagline": "Bloom Your Social Footprint — Creator, Content & Digital-Growth Ecosystem",
            "category": "Creator Economy & Media Infrastructure",
            "description": (
                "A comprehensive creator, content, and digital-growth ecosystem under Autobahn Professional Services "
                "combining physical studio infrastructure (sBLOOM Cre@tors Studio) with an end-to-end digital content "
                "engine (Idea -> Plan -> Create -> Edit -> Enhance -> Distribute -> Discover -> Grow) for creators, "
                "doctors, executive coaches, corporate trainers, healthcare leaders, founders, and executives building personal brands and thought leadership."
            ),
            "target_audience": "Digital creators, doctors & healthcare specialists, executive coaches & trainers, founders & executives building authority",
            "business_model": "Studio Memberships, Managed Production Packages, and Content Retainers",
            "problem_domains": [
                "Doctor personal branding, medical content strategy, and healthcare thought leadership on LinkedIn and social media.",
                "Executive coaches, leadership trainers, and consultants struggling to produce consistent thought leadership content and build authority to attract high-ticket coaching clients.",
                "Creators, doctors, coaches, and specialists overwhelmed by end-to-end production (writing, shooting, editing, publishing) alone, creating a hard ceiling on content output.",
                "Founders, clinicians, and executives struggling to consistently produce platform-ready social video and build thought leadership authority.",
                "High friction in briefing editors and maintaining consistent Creator Style Profiles across multi-channel distribution.",
                "Need for AI-assisted repurposing of long-form interviews, clinical case discussions, and podcasts into high-impact short-form clips."
            ],
            "semantic_keywords": [
                "personal branding", "doctor personal branding", "content strategy", "medical content", "healthcare branding",
                "doctor", "creator", "content creation", "podcast", "studio", "reels", "video editing", "scripting",
                "social footprint", "thought leadership", "repurposing", "youtube", "linkedin personal brand",
                "production bottleneck", "creator burnout", "media infrastructure", "short-form video", "influencer",
                "coach", "coaching", "executive coach", "leadership development", "consultant branding"
            ],
            "key_features": [
                "Physical sBLOOM Cre@tors Studio Infrastructure (Podcast sets, reels studios, 4K cameras, editing suites)",
                "8-Stage Content Production Engine (Idea to Distribution & Growth)",
                "Doctor, Executive & Coach Thought Leadership Personal Branding Engine",
                "AI-Assisted Content Repurposing (Transcripts to short-form video hooks & articles)",
                "Cross-Platform Social Footprint Expansion & Creator Style Profiles",
                "Creator-to-Business Matching & Sponsorship Marketplace"
            ],
            "unsupported_domains": [
                "cinema feature film production", "hardware camera manufacturing", "television broadcast licensing",
                "physical printing press"
            ]
        },
        {
            "id": "prod-talentops",
            "name": "TalentOps",
            "tagline": "AI-Powered Workforce Operations Platform",
            "category": "HR Tech & Workforce Operations",
            "description": (
                "An AI-powered Managed Workforce Operations Platform transforming traditional HR management into "
                "a highly automated, intelligence-driven service model. Operates on a Human-in-the-Loop model "
                "(AI executes routine operations, human operators supervise exceptions, domain experts handle escalations), "
                "reducing operational HR overhead by over 80%."
            ),
            "target_audience": "High-growth startups, SMEs, and distributed enterprise organizations",
            "business_model": "Managed Workforce Operations Service (MWOS) Monthly Subscription",
            "problem_domains": [
                "Repetitive HR administrative workload: manual onboarding, delayed leave approvals, and attendance inconsistencies.",
                "Complex, error-prone manual payroll processing and multi-system employee record fragmentation.",
                "Unclear task ownership, missing accountability, and absence of structured peer and manager review processes.",
                "Excessive operational overhead and delayed response times for basic employee HR policy queries."
            ],
            "semantic_keywords": [
                "hr", "human resources", "workforce", "payroll", "leave approval", "attendance", "employee onboarding",
                "timesheet", "administrative workload", "hr operations", "people operations", "task management",
                "workforce operations", "human-in-the-loop", "employee records", "compliance audit", "staffing"
            ],
            "key_features": [
                "Human-in-the-Loop AI Operating Model (AI Automation + Human Oversight + Expert Escalation)",
                "80%+ Reduction in Operational HR Workload",
                "Automated Employee Onboarding & Lifecycle Records Management",
                "Intelligent Task & Attendance Tracking with Automated Leave Validation",
                "Automated Payroll Preparation & Regulatory Compliance Auditing",
                "24/7 AI Virtual HR Assistant for Employee Queries & Policy Guidance"
            ],
            "unsupported_domains": [
                "heavy industrial machinery safety", "blue-collar physical construction staffing", "labor union litigation"
            ]
        },
        {
            "id": "prod-networkos",
            "name": "NetworkOS Platform",
            "tagline": "Commercial Relationship Intelligence Operating System",
            "category": "Enterprise Relationship OS",
            "description": (
                "The foundational operating system for high-trust commercial relationship intelligence, "
                "autonomous multi-source research orchestration, evidence-based problem matching, and founder "
                "decision workflows."
            ),
            "target_audience": "Founders, Managing Partners, Enterprise Business Development Leaders",
            "business_model": "Enterprise Platform Subscription & Intelligence Tier",
            "problem_domains": [
                "Underutilized executive relationship capital and lost commercial opportunities across founder networks.",
                "Slow, fragmented manual background research and dossier preparation on prospective enterprise clients.",
                "Inability to systematically map client problems to verifiable internal products and delivery capabilities.",
                "Lack of structured founder decision queues and missed commercial outreach timing windows."
            ],
            "semantic_keywords": [
                "relationship intelligence", "network", "commercial opportunity", "founder decision",
                "executive research", "dossier", "problem matching", "trusted context", "business development",
                "deal flow", "introduction routing", "commercial pipeline"
            ],
            "key_features": [
                "Autonomous Multi-Source Research Orchestration",
                "Executive 360 Contact Intelligence & Verified Dossiers",
                "Evidence-Based Problem & Capability Matching Engine",
                "Founder Decision Queue & Relationship Capital Pipeline"
            ],
            "unsupported_domains": [
                "consumer social networking", "dating app", "direct mass email spamming"
            ]
        }
    ]

    # Global unsupported domains that are outside our entire product portfolio
    OUT_OF_PORTFOLIO_DOMAINS = [
        {"domain": "Heavy civil engineering, construction equipment, earthmoving machinery", "keywords": ["construction", "bulldozer", "excavator", "heavy machinery", "concrete", "civil engineering"]},
        {"domain": "Hardware manufacturing, silicon chip fabrication, semiconductor foundry", "keywords": ["semiconductor", "foundry", "chip fabrication", "wafer", "hardware manufacturing"]},
        {"domain": "In-person clinical surgery, pharmaceutical drug compounding", "keywords": ["surgical operation", "drug compounding", "narcotic prescription", "operating theater"]},
        {"domain": "Automotive assembly, vehicle parts manufacturing", "keywords": ["automotive assembly", "tire manufacturing", "engine casting"]}
    ]

    @classmethod
    def _classify_domain(
        cls,
        problem_text: str,
        connection_company: Optional[str] = None,
        connection_title: Optional[str] = None
    ) -> str:
        text_lower = problem_text.lower()
        company_lower = (connection_company or "").lower()
        title_lower = (connection_title or "").lower()

        if any(w in text_lower for w in ["retail", "real estate", "mall", "property", "lease", "tenant", "footfall"]):
            return "Retail & Commercial Real Estate Expansion"
        if any(w in text_lower for w in ["doctor", "clinic", "patient", "gastroenterolog", "fertility", "maternity", "hospital", "clinical"]):
            return "Healthtech & Clinical Practice Management"
        if any(w in text_lower for w in ["creator", "content", "podcast", "reels", "branding", "thought leadership", "social footprint"]):
            return "Creator Media & Executive Personal Branding"
        if any(w in text_lower for w in ["hr", "payroll", "workforce", "employee", "onboarding", "timesheet", "attendance", "staffing"]):
            return "Workforce Operations & HR Management"
        if any(w in text_lower for w in ["tutorial fatigue", "learning", "upskilling", "course", "edtech", "coding", "software engineer", "doubt clarification"]):
            return "AI-Native Developer Education & Upskilling"
        if any(w in text_lower or w in company_lower for w in ["coach", "certification", "training program", "leadership training", "emotional intelligence", "nlp training", "mentor", "trainer"]):
            return "Professional Coaching & Training Certification"
        if any(w in text_lower for w in ["relationship", "network", "investor", "deal", "commercial opportunity", "dossier", "founder"]):
            return "Commercial Relationship Intelligence & Deal Flow"
        if any(w in text_lower for w in ["construction", "excavator", "bulldozer", "heavy machinery", "civil engineering"]):
            return "Heavy Civil Engineering & Machinery"
        if any(w in text_lower for w in ["semiconductor", "foundry", "wafer", "silicon chip", "hardware manufacturing"]):
            return "Semiconductor & Hardware Fabrication"
        if any(w in text_lower for w in ["erp", "crm", "salesforce", "sap", "billing software", "reconciliation"]):
            return "Enterprise Systems & ERP Billing"
        if any(w in text_lower for w in ["monolith", "microservices", "latency", "database scaling", "cloud modernization"]):
            return "Cloud Modernization & Architecture"
        if any(w in text_lower for w in ["copilot", "azure ai", "agent compliance", "rag system", "llm validation"]):
            return "Enterprise AI & Autonomous Agents"

        # Context-based domain extraction
        if company_lower:
            return f"{connection_company} Operations"
        if title_lower:
            return f"{connection_title} Domain"
        return "Enterprise Business Operations"

    @classmethod
    def _is_vague_or_underspecified(cls, problem_text: str) -> bool:
        if not problem_text or not problem_text.strip():
            return True
        text = problem_text.strip().lower()

        # High-level strategic or expansion themes lacking concrete operational friction
        vague_patterns = [
            "expansion and growth",
            "growth and expansion",
            "market expansion",
            "expansion in the",
            "growth in the",
            "scaling in the",
            "scaling operations",
            "business expansion",
            "strategic growth",
            "explore opportunities",
            "expanding into",
            "growing our presence",
            "digital transformation initiative",
            "improve business performance",
            "scaling the business"
        ]

        # Concrete operational friction markers that give specific actionable substance
        concrete_friction_markers = [
            "bottleneck", "delay", "error", "manual", "unprepared", "fatigue",
            "overwhelmed", "inconsistency", "inconsistent", "fragmented", "friction",
            "siloed", "reconciliation", "burnout", "turnaround", "timesheet",
            "payroll", "leave approval", "attendance", "onboarding", "intake",
            "scoring", "lead management", "booking", "scripting", "editing",
            "reels", "sandbox", "code validation", "doubt clarification"
        ]

        has_vague_pattern = any(vp in text for vp in vague_patterns)
        has_concrete_friction = any(cfm in text for cfm in concrete_friction_markers)

        if has_vague_pattern and not has_concrete_friction:
            return True

        words = text.split()
        if len(words) < 6 and not has_concrete_friction:
            return True

        return False

    @classmethod
    def _is_unverified_problem(cls, problem_text: Optional[str]) -> bool:
        """
        Determines if a problem statement indicates an unverified, placeholder, or absent problem.
        If a problem is not verified, no solution should ever be suggested.
        """
        if not problem_text or not problem_text.strip():
            return True
        p_lower = problem_text.strip().lower()
        unverified_patterns = [
            "no verified",
            "unverified",
            "not verified",
            "no explicit problem",
            "no observed problem",
            "insufficient evidence",
            "conflicting evidence",
            "hypothesis only",
            "unverified hypothesis",
            "pending research",
            "unknown",
            "none",
            "n/a",
            "analyzing dossier",
            "awaiting research",
            "not specified",
            "no problem"
        ]
        if any(pat in p_lower for pat in unverified_patterns):
            return True
        # Strip all punctuation and check if remaining text is trivial
        cleaned = re.sub(r'[^a-zA-Z0-9]', '', p_lower)
        if len(cleaned) < 4:
            return True
        return False

    @classmethod
    def _generate_solution_blueprint(
        cls,
        problem_text: str,
        domain: str,
        connection_title: Optional[str] = None,
        connection_company: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generates a concrete, actionable technical/operational solution blueprint for problems
        that do not match any off-the-shelf product in the 5-product catalog.
        Returns None if the problem is unverified.
        """
        if cls._is_unverified_problem(problem_text):
            return None

        p_lower = (problem_text or "").lower()
        c_name = connection_company or "the enterprise"

        # 1. Systems scaling, architecture, infrastructure, backend, performance
        if any(w in p_lower for w in ["systems scaling", "scaling", "architecture", "microservices", "latency", "monolith", "cloud", "infrastructure", "concurrency", "throughput", "database scaling", "bottleneck"]):
            return (
                f"Architecture Modernization & Distributed Scaling Blueprint for {c_name}: "
                f"(1) Profiling & Bottleneck Isolation: Audit distributed traces, slow queries, and database locks under peak load to pinpoint compute/storage bottlenecks. "
                f"(2) Asynchronous Workload Decoupling: Offload synchronous blocking endpoints via event-driven messaging (Kafka / AWS SQS) and dedicated background worker pools. "
                f"(3) Data Tier Caching & Sharding: Implement multi-layer caching (Redis) and database read-replicas with connection pooling to eliminate database saturation. "
                f"(4) Elastic Horizontal Autoscaling: Deploy containerized microservices with Horizontal Pod Autoscaling (Kubernetes / EKS) behind load balancers. "
                f"Delivered via Ottobon Bespoke Engineering: 60-hour Architecture Review & Scaling Sprint ($10,000 sprint)."
            )

        # 2. Data engineering, pipelines, analytics, big data
        if any(w in p_lower for w in ["data", "etl", "pipeline", "warehouse", "analytics", "lakehouse"]):
            return (
                f"Modern Data Platform & Pipeline Optimization for {c_name}: "
                f"(1) Transition legacy batch ETL to event-driven streaming pipelines (dbt, Apache Airflow / Dagster). "
                f"(2) Standardize schema contracts and automated data quality validation checkpoints. "
                f"(3) Optimize analytical query performance with columnar storage and partitioned warehouses (Snowflake / BigQuery). "
                f"Delivered via Ottobon Custom Data Engineering Advisory Sprint."
            )

        # 3. Security, compliance, DevOps, CI/CD
        if any(w in p_lower for w in ["security", "compliance", "soc2", "devops", "ci/cd", "deployment"]):
            return (
                f"Automated Compliance & DevOps Pipeline Blueprint for {c_name}: "
                f"(1) Implement automated CI/CD security scanning, vulnerability gates, and secret management. "
                f"(2) Enforce infrastructure-as-code (Terraform) with policy-as-code guardrails. "
                f"(3) Streamline audit evidence collection for continuous compliance. "
                f"Delivered via Ottobon DevOps & Cloud Advisory Sprint."
            )

        # 4. Operations, workflow friction, business processes
        if any(w in p_lower for w in ["operations", "operational", "workflow", "process", "manual", "efficiency", "coordination"]):
            return (
                f"Operational Workflow Modernization & Automation for {c_name}: "
                f"(1) Process Mining: Map manual touchpoints, handoff bottlenecks, and repetitive operational tasks. "
                f"(2) Integrated Automation: Deploy low-latency webhook connectors and workflow orchestrators to automate inter-departmental handoffs. "
                f"(3) Real-Time Operational Dashboard: Unified monitoring for task SLAs, turnaround times, and exception escalation. "
                f"Delivered via Ottobon Operational Systems Sprint."
            )

        # 5. Default tailored technical & advisory blueprint
        return (
            f"Tailored Solution Architecture Blueprint for {c_name}: "
            f"(1) Comprehensive Current-State Diagnostic: Evaluate existing systems, operational friction points, and constraint thresholds. "
            f"(2) Solution Architecture Specification: Formulate a modern, decoupled target architecture with clear ROI milestones. "
            f"(3) Iterative Delivery Sprint: Execute a focused pilot implementation to resolve the core bottleneck within 4-6 weeks. "
            f"Delivered via Ottobon Bespoke Engineering & Advisory Sprint."
        )

    @classmethod
    def _build_insufficient_information_response(
        cls,
        problem_text: str,
        connection_id: Optional[str] = None,
        connection_name: Optional[str] = None,
        connection_company: Optional[str] = None,
        connection_title: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> SemanticProductMatchResponse:
        domain = cls._classify_domain(problem_text, connection_company, connection_title)

        evidence = []
        if connection_name or connection_title or connection_company:
            role_desc = f"{connection_title or 'Leader'}"
            if connection_company:
                role_desc += f" at {connection_company}"
            evidence.append(f"Connection Profile: {connection_name or 'Contact'} ({role_desc})")
        if context and context.get("industry"):
            evidence.append(f"Market Context: {context['industry']}")
        evidence.append(f"Stated Strategic Focus: \"{problem_text}\"")

        is_unverified = cls._is_unverified_problem(problem_text)
        if is_unverified:
            rationale = (
                f"No verified operational problem or business bottleneck has been identified for this contact. "
                f"Product capability matching and solution recommendations require an authentic, verified operational problem."
            )
            suggested_status = "Problem Unverified"
            proposed_sol = None
        else:
            rationale = (
                f"The stated problem describes a broad market or strategic objective ('{problem_text}') rather than a "
                f"concrete operational friction, workflow constraint, or software bottleneck. Product capability matching "
                f"evaluates documented product features against specific operational pain points. Additional discovery "
                f"is required to identify the underlying operational challenge before recommending solutions."
            )
            suggested_status = "Insufficient Information"
            proposed_sol = cls._generate_solution_blueprint(
                problem_text=problem_text,
                domain=domain,
                connection_title=connection_title,
                connection_company=connection_company,
            )

        return SemanticProductMatchResponse(
            connection_id=connection_id,
            connection_name=connection_name or "Connection",
            connection_company=connection_company,
            connection_title=connection_title,
            identified_problem=problem_text,
            problem_domain=domain,
            matching_outcome=MatchingOutcome.INSUFFICIENT_INFORMATION,
            suggested_status=suggested_status,
            matches=[],
            rationale=rationale,
            relevant_evidence=evidence,
            supported_capabilities=[],
            missing_information=[
                f"Specific operational bottlenecks or delivery friction hindering {domain.lower()}",
                "Current software systems, internal tooling, and workflow practices in active use",
                "Target department or operational function experiencing the primary constraint (e.g., Marketing, Workforce/HR, Operations, Clinical)"
            ],
            unverified_hypotheses=[
                f"Hypothesis: {connection_company or 'The organization'} may require executive thought leadership / content authority for market positioning.",
                f"Hypothesis: Rapid expansion may create distributed workforce operations, staffing, or payroll friction.",
                f"Hypothesis: Commercial growth may benefit from systematic relationship and partnership network intelligence."
            ],
            validation_questions=[
                f"What specific operational bottleneck or workflow constraint is currently slowing down {domain.lower()}?",
                "Which department is currently bearing the highest manual workload or operational overhead?",
                "Is the immediate operational priority related to workforce management, executive branding/content authority, or commercial partnership tracking?"
            ],
            recommended_next_step=(
                "Conduct an exploratory discovery interview to uncover the specific operational friction and workflow constraints "
                "before evaluating capability fit against our product portfolio."
            ),
            capability_gap=None,
            proposed_solution=proposed_sol
        )

    @classmethod
    async def match_connection_problem(
        cls,
        problem_text: str,
        connection_id: Optional[str] = None,
        connection_name: Optional[str] = None,
        connection_company: Optional[str] = None,
        connection_title: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> SemanticProductMatchResponse:
        """
        Executes evidence-based semantic matching of a connection's stated problem against our product portfolio.
        Returns one of four defined outcomes:
        - MATCH_FOUND: Documented capabilities directly solve the specific operational problem.
        - NO_MATCH_FOUND: Problem is sufficiently understood, but no product satisfies the requirements.
        - INSUFFICIENT_INFORMATION: Problem statement is too vague or underspecified to evaluate reliably.
        - NEEDS_VALIDATION: Potential capability fit exists, but critical assumptions require validation.
        """
        clean_problem = (problem_text or "").strip()
        if not clean_problem:
            return cls._build_insufficient_information_response(
                problem_text="No explicit problem documented.",
                connection_id=connection_id,
                connection_name=connection_name,
                connection_company=connection_company,
                connection_title=connection_title,
                context=context
            )

        # 1. Immediate check: Vague or underspecified problem statements -> INSUFFICIENT_INFORMATION
        if cls._is_vague_or_underspecified(clean_problem):
            return cls._build_insufficient_information_response(
                problem_text=clean_problem,
                connection_id=connection_id,
                connection_name=connection_name,
                connection_company=connection_company,
                connection_title=connection_title,
                context=context
            )

        # 2. Attempt LLM-powered semantic matching if API key is configured
        if settings.OPENAI_API_KEY:
            try:
                llm_res = await cls._match_with_llm(
                    problem_text=clean_problem,
                    connection_name=connection_name,
                    connection_company=connection_company,
                    connection_title=connection_title,
                    connection_id=connection_id
                )
                if llm_res:
                    return llm_res
            except Exception as e:
                logger.warning(f"SemanticProductMatcher: LLM matching failed ({e}), using deterministic semantic matcher.")

        # 3. Deterministic Semantic Matching Engine fallback
        return cls._match_deterministic(
            problem_text=clean_problem,
            connection_id=connection_id,
            connection_name=connection_name,
            connection_company=connection_company,
            connection_title=connection_title,
            context=context
        )

    @classmethod
    def _match_deterministic(
        cls,
        problem_text: str,
        connection_id: Optional[str] = None,
        connection_name: Optional[str] = None,
        connection_company: Optional[str] = None,
        connection_title: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> SemanticProductMatchResponse:
        prob_lower = problem_text.lower()
        domain = cls._classify_domain(problem_text, connection_company, connection_title)

        # Check if vague or underspecified
        if cls._is_vague_or_underspecified(problem_text):
            return cls._build_insufficient_information_response(
                problem_text=problem_text,
                connection_id=connection_id,
                connection_name=connection_name,
                connection_company=connection_company,
                connection_title=connection_title,
                context=context
            )

        # Check global out-of-portfolio exclusions
        for oop in cls.OUT_OF_PORTFOLIO_DOMAINS:
            if any(kw in prob_lower for kw in oop["keywords"]):
                return SemanticProductMatchResponse(
                    connection_id=connection_id,
                    connection_name=connection_name or "Connection",
                    connection_company=connection_company,
                    connection_title=connection_title,
                    identified_problem=problem_text,
                    problem_domain=oop["domain"],
                    matching_outcome=MatchingOutcome.NO_MATCH_FOUND,
                    suggested_status="No matches found",
                    matches=[],
                    rationale=(
                        f"The connection's identified problem relates to '{oop['domain']}'. "
                        f"None of our current products (JanmaSethu, Ottobon Course Platform, sBLOOM, "
                        f"TalentOps, NetworkOS Platform) operate in this space."
                    ),
                    relevant_evidence=[f"Identified Problem: \"{problem_text}\""],
                    supported_capabilities=[],
                    missing_information=[],
                    unverified_hypotheses=[],
                    validation_questions=[],
                    recommended_next_step="Acknowledge capability boundary. Do not propose existing products unless custom engineering is commissioned.",
                    capability_gap=f"Unsupported domain: {oop['domain']}",
                    proposed_solution=f"Develop a specialized partner integration or custom system for {oop['domain']} outside our standard 5-product SaaS catalog."
                )

        scored_candidates: List[ProductMatchItem] = []

        for prod in cls.PRODUCT_CATALOG:
            if any(u in prob_lower for u in prod.get("unsupported_domains", [])):
                continue

            score = 0
            matched_keywords = [kw for kw in prod["semantic_keywords"] if kw in prob_lower]
            keyword_score = min(len(matched_keywords) * 16, 60)
            score += keyword_score

            matched_domains = []
            for pd in prod["problem_domains"]:
                words_in_pd = [w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', pd)]
                overlap = sum(1 for w in words_in_pd if w in prob_lower)
                if overlap >= 2:
                    matched_domains.append(pd)
                    score += 25

            if connection_company and connection_company.lower() in str(prod["name"]).lower():
                score += 30
            if context and context.get("industry"):
                ind_lower = context["industry"].lower()
                if any(kw in ind_lower for kw in prod["semantic_keywords"]):
                    score += 15

            final_score = min(score, 96)

            if final_score >= 50:
                alignment = "STRONG" if final_score >= 75 else "MODERATE" if final_score >= 60 else "WEAK"
                relevant_features = prod["key_features"][:3]
                why_solves = (
                    f"{prod['name']} directly addresses this through its {str(prod['key_features'][0]).lower()} "
                    f"and purpose-built capabilities for {prod['category']}."
                )

                candidate = ProductMatchItem(
                    product_id=prod["id"],
                    product_name=prod["name"],
                    category=prod["category"],
                    tagline=prod["tagline"],
                    match_score=final_score,
                    alignment_level=alignment,
                    addressed_problem=problem_text,
                    why_this_product_solves_it=why_solves,
                    relevant_features=relevant_features,
                    target_audience_fit=f"Target: {prod['target_audience']}",
                    assumptions_or_prerequisites=[
                        f"Requires confirming customer adoption requirements and existing system integration with {prod['name']}."
                    ],
                    suggested_first_step=f"Schedule exploratory discovery demo presenting {prod['name']} capability fit."
                )
                scored_candidates.append(candidate)

        scored_candidates.sort(key=lambda c: c.match_score, reverse=True)
        viable_matches = [c for c in scored_candidates if c.match_score >= 50]

        evidence_list = [f"Stated Problem: \"{problem_text}\""]
        if connection_company:
            evidence_list.append(f"Company: {connection_company}")
        if connection_title:
            evidence_list.append(f"Role: {connection_title}")

        if not viable_matches:
            catalog_names = ", ".join(str(p["name"]) for p in cls.PRODUCT_CATALOG)
            proposed_sol = cls._generate_solution_blueprint(
                problem_text=problem_text,
                domain=domain,
                connection_title=connection_title,
                connection_company=connection_company,
            )
            return SemanticProductMatchResponse(
                connection_id=connection_id,
                connection_name=connection_name or "Connection",
                connection_company=connection_company,
                connection_title=connection_title,
                identified_problem=problem_text,
                problem_domain=domain,
                matching_outcome=MatchingOutcome.NO_MATCH_FOUND,
                suggested_status="No matches found",
                matches=[],
                rationale=(
                    f"No matches found. Evaluated the connection's problem against all products in our catalog "
                    f"({catalog_names}). None achieved the required commercial semantic alignment threshold. "
                    f"The problem appears to require specialized capabilities outside our current product offerings."
                ),
                relevant_evidence=evidence_list,
                supported_capabilities=[],
                missing_information=[],
                unverified_hypotheses=[],
                validation_questions=[],
                recommended_next_step="Acknowledge capability boundary. Do not propose existing products unless custom engineering is commissioned.",
                capability_gap=f"No product in the active catalog matches {domain}.",
                proposed_solution=proposed_sol
            )

        top_match = viable_matches[0]

        # Check if match is NEEDS_VALIDATION (50 <= score < 75) vs MATCH_FOUND (score >= 75)
        if top_match.match_score < 75:
            candidate_names = [m.product_name for m in viable_matches]
            return SemanticProductMatchResponse(
                connection_id=connection_id,
                connection_name=connection_name or "Connection",
                connection_company=connection_company,
                connection_title=connection_title,
                identified_problem=problem_text,
                problem_domain=top_match.category,
                matching_outcome=MatchingOutcome.NEEDS_VALIDATION,
                suggested_status=f"Needs Validation: {', '.join(candidate_names)}",
                matches=viable_matches,
                rationale=(
                    f"A potential capability match was identified with {top_match.product_name} ({top_match.match_score}% fit), "
                    f"but operational workflows, decision authority, and technical prerequisites require validation before recommendation."
                ),
                relevant_evidence=evidence_list,
                supported_capabilities=top_match.relevant_features,
                missing_information=[
                    f"Confirmation of client's current operational tooling for {top_match.category.lower()}",
                    f"Validation of specific technical scope with {top_match.product_name}"
                ],
                unverified_hypotheses=top_match.assumptions_or_prerequisites,
                validation_questions=[
                    f"Does the client currently face operational challenges that {top_match.product_name} addresses?",
                    f"Confirm decision authority and existing tooling before recommending {top_match.product_name}."
                ],
                recommended_next_step="Founder discovery interview to validate operational hypotheses before proposing a solution.",
                capability_gap=None
            )

        # High-confidence MATCH_FOUND
        product_names = [m.product_name for m in viable_matches]
        suggested_status = f"MATCH FOUND: {top_match.product_name}" if len(product_names) == 1 else f"MATCHES FOUND: {', '.join(product_names)}"
        all_supported_caps = []
        for vm in viable_matches:
            all_supported_caps.extend(vm.relevant_features)

        return SemanticProductMatchResponse(
            connection_id=connection_id,
            connection_name=connection_name or "Connection",
            connection_company=connection_company,
            connection_title=connection_title,
            identified_problem=problem_text,
            problem_domain=top_match.category,
            matching_outcome=MatchingOutcome.MATCH_FOUND,
            suggested_status=suggested_status,
            matches=viable_matches,
            rationale=(
                f"Semantic analysis identified {top_match.product_name} as a suitable solution ({top_match.match_score}% match). "
                f"{top_match.why_this_product_solves_it}"
            ),
            relevant_evidence=evidence_list,
            supported_capabilities=list(dict.fromkeys(all_supported_caps)),
            missing_information=[],
            unverified_hypotheses=[],
            validation_questions=[
                f"Confirm commercial engagement timeline and deployment prerequisites for {top_match.product_name}."
            ],
            recommended_next_step=f"Founder approval for targeted outreach presenting {top_match.product_name} capability demonstration.",
            capability_gap=None
        )

    @classmethod
    async def _match_with_llm(
        cls,
        problem_text: str,
        connection_name: Optional[str],
        connection_company: Optional[str],
        connection_title: Optional[str],
        connection_id: Optional[str]
    ) -> Optional[SemanticProductMatchResponse]:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=settings.OPENAI_API_KEY)

        catalog_summary = "\n".join([
            f"- Product: {p['name']} ({p['category']})\n"
            f"  Tagline: {p['tagline']}\n"
            f"  Description: {p['description']}\n"
            f"  Target Audience: {p['target_audience']}\n"
            f"  Problem Domains: {'; '.join(p['problem_domains'])}\n"
            f"  Key Features: {'; '.join(p['key_features'])}\n"
            for p in cls.PRODUCT_CATALOG
        ])

        system_prompt = f"""You are the Chief Solutions Architect for NetworkOS.
Your core principle:
UNDERSTAND THE CONNECTION'S PROBLEM DEEPLY:
1. IF WE HAVE A SOLUTION IN OUR PRODUCT CATALOG, SUGGEST IT:
   - Carefully evaluate how our 5 products (Ottobon Course Platform, sBLOOM, TalentOps, JanmaSethu, NetworkOS Platform) directly solve or enable their operational requirements:
     * For courses, training programs, coaching academies, or certification delivery -> Ottobon Course Platform is a direct capability solution.
     * For coaches, doctors, executives, or creators needing thought leadership, personal branding, video production, or client attraction -> sBLOOM is a direct capability solution.
     * For workforce/HR administrative friction, payroll, and timesheets -> TalentOps.
     * For clinic/patient workflow bottlenecks and digital practice intake -> JanmaSethu.
     * For commercial relationship intelligence, deal flow, and founder networks -> NetworkOS Platform.
   - When suggesting matched products, assign an accurate match_score (70-95%), alignment_level, why_this_product_solves_it, and relevant_features.

2. IF WE DO NOT HAVE A DIRECT PRODUCT MATCH, YOU MUST SAY WHAT CAN BE A SOLUTION:
   - Never stop at a dead-end rejection.
   - Populate capability_gap (what part is outside the 5 catalog products).
   - In proposed_solution: Explain what CAN be a solution — describe the concrete solution architecture, custom AI deliverable, external system integration, or tailored deliverable that solves their problem.
   - In recommended_next_step: Specific founder or discovery action to scope and validate that solution.

OUR CURRENT PRODUCT CATALOG (5 PRODUCTS ONLY):
{catalog_summary}

YOU MUST ASSIGN EXACTLY ONE OF THE FOLLOWING FOUR MATCHING OUTCOMES:

1. 'MATCH_FOUND':
   - Use when documented product capabilities directly solve or enable the specific operational problem with clear evidence.
   - Must specify: matches, relevant_features, why_this_product_solves_it, and supported_capabilities.

2. 'INSUFFICIENT_INFORMATION':
   - Use when the problem statement is a broad strategic objective, macro growth aspiration, or too vague/underspecified to evaluate capability fit reliably (e.g., "Expansion and growth in the retail and real estate market, particularly in India", "Digital transformation initiative", "Scaling operations in 2026", "Looking to improve business performance").
   - Do NOT treat an industry mismatch as an automatic rejection; classify the actual business domain (e.g. "Retail & Commercial Real Estate Expansion", NOT "Non-matching Domain").
   - Set matching_outcome='INSUFFICIENT_INFORMATION', suggested_status='Insufficient Information', matches=[].
   - Must provide: missing_information (what specific operational details are needed), validation_questions (what discovery questions to ask), and recommended_next_step.

3. 'NEEDS_VALIDATION':
   - Use when a plausible capability match exists in our 5-product catalog, but key assumptions, operational prerequisites, or technical workflows remain unverified before a recommendation can be formally made.
   - Set matching_outcome='NEEDS_VALIDATION', suggested_status='Needs Validation: [Candidate Product]'.
   - Must provide: unverified_hypotheses, validation_questions, and recommended_next_step.

4. 'NO_MATCH_FOUND':
   - Use ONLY when the specific operational problem is sufficiently understood, but none of our 5 products possess the required capabilities (e.g., enterprise ERP/CRM billing software, core banking ledger, physical civil engineering machinery, hardware manufacturing).
   - Do NOT output "Non-matching Domain". Classify the actual domain (e.g., "Enterprise ERP & Billing Systems", "Heavy Civil Construction").
   - Set matching_outcome='NO_MATCH_FOUND', suggested_status='No matches found', matches=[], and populate capability_gap.
   - AND CRITICALLY: Always populate proposed_solution with what CAN be a solution (e.g., a custom AI architecture, specialized integration, or bespoke workflow).

CRITICAL RULES:
1. STRICT CATALOG LIMIT: Our company ONLY has 5 products: JanmaSethu, sBLOOM, TalentOps, Ottobon Course Platform, and NetworkOS Platform. Under NO circumstances invent products outside these 5.
2. DO NOT TREAT INDUSTRY AS REJECTION: Understand the underlying problem and evaluate if our platform/studio/workforce capabilities apply.
3. ALWAYS PROVIDE A SOLUTION: If a product matches, suggest it. If not, say what can be a solution via proposed_solution.
4. HUMAN-IN-THE-LOOP: All recommendations are advisory and require founder approval before outreach.
"""

        user_prompt = f"""Connection Context:
Name: {connection_name or 'Unknown'}
Title: {connection_title or 'Unknown'}
Company: {connection_company or 'Unknown'}

Connection's Problem Statement:
"{problem_text}"

Evaluate whether any of our products are suitable solutions. Choose strictly one of: MATCH_FOUND, INSUFFICIENT_INFORMATION, NEEDS_VALIDATION, NO_MATCH_FOUND."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", user_prompt)
        ])

        chain = prompt | llm.with_structured_output(SemanticProductMatchResponse)
        raw_res = await chain.ainvoke({})
        if raw_res:
            res: SemanticProductMatchResponse = (
                SemanticProductMatchResponse(**raw_res) if isinstance(raw_res, dict) else raw_res
            )
            res.connection_id = connection_id
            res.connection_name = connection_name or "Connection"
            res.connection_company = connection_company
            res.connection_title = connection_title
            res.identified_problem = problem_text

            # Enforce clean domain name if LLM returned 'Non-matching Domain'
            if not res.problem_domain or "non-matching" in res.problem_domain.lower():
                res.problem_domain = cls._classify_domain(problem_text, connection_company, connection_title)

            # Standardize outcomes and statuses
            if res.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION or str(res.matching_outcome) == "INSUFFICIENT_INFORMATION":
                res.matching_outcome = MatchingOutcome.INSUFFICIENT_INFORMATION
                res.suggested_status = "Problem Unverified" if cls._is_unverified_problem(problem_text) else "Insufficient Information"
                res.matches = []
                if not res.missing_information:
                    res.missing_information = [
                        f"Specific operational bottlenecks or delivery friction hindering {res.problem_domain.lower()}",
                        "Current software systems, internal tooling, and workflow practices in active use",
                        "Target department or operational function experiencing the primary constraint"
                    ]
                if not res.validation_questions:
                    res.validation_questions = [
                        f"What specific operational bottleneck or workflow constraint is currently slowing down {res.problem_domain.lower()}?",
                        "Is the immediate operational priority related to workforce management, executive branding/content authority, or commercial partnership tracking?"
                    ]
                if not res.recommended_next_step:
                    res.recommended_next_step = "Conduct an exploratory discovery interview to uncover the specific operational friction before evaluating product capabilities."

            elif res.matching_outcome == MatchingOutcome.NEEDS_VALIDATION or str(res.matching_outcome) == "NEEDS_VALIDATION":
                res.matching_outcome = MatchingOutcome.NEEDS_VALIDATION
                candidate_names = [m.product_name for m in res.matches]
                res.suggested_status = f"Needs Validation: {', '.join(candidate_names) if candidate_names else 'Potential Fit'}"
                if not res.unverified_hypotheses and res.matches:
                    res.unverified_hypotheses = res.matches[0].assumptions_or_prerequisites
                if not res.validation_questions:
                    res.validation_questions = [
                        "Validate customer operational readiness and existing workflow integration."
                    ]
                if not res.recommended_next_step:
                    res.recommended_next_step = "Founder discovery interview to validate operational hypotheses before proposing a solution."

            elif res.matching_outcome == MatchingOutcome.MATCH_FOUND or str(res.matching_outcome) == "MATCH_FOUND":
                if not res.matches:
                    res.matching_outcome = MatchingOutcome.NO_MATCH_FOUND
                    res.suggested_status = "No matches found"
                    res.capability_gap = res.capability_gap or "No product in the active catalog matches the identified business friction."
                else:
                    res.matching_outcome = MatchingOutcome.MATCH_FOUND
                    catalog_id_map = {
                        "talentops": "prod-talentops",
                        "sbloom": "prod-sbloom",
                        "janmasethu": "prod-janmasethu",
                        "ottobon course platform": "prod-ottobon-courses",
                        "ottobon courses": "prod-ottobon-courses",
                        "networkos platform": "prod-networkos",
                        "networkos": "prod-networkos"
                    }
                    for m in res.matches:
                        if not m.product_id or m.product_id not in [p["id"] for p in cls.PRODUCT_CATALOG]:
                            norm_name = m.product_name.strip().lower()
                            if norm_name in catalog_id_map:
                                m.product_id = catalog_id_map[norm_name]
                    product_names = [m.product_name for m in res.matches]
                    res.suggested_status = f"MATCH FOUND: {res.matches[0].product_name}" if len(product_names) == 1 else f"MATCHES FOUND: {', '.join(product_names)}"
                    if not res.recommended_next_step:
                        res.recommended_next_step = f"Founder approval for targeted outreach presenting {res.matches[0].product_name} capability demonstration."

            else:
                res.matching_outcome = MatchingOutcome.NO_MATCH_FOUND
                res.suggested_status = "No matches found"
                res.matches = []
                if not res.capability_gap:
                    res.capability_gap = f"No product in the active catalog matches {res.problem_domain}."
                if not res.proposed_solution:
                    res.proposed_solution = f"Design and implement a tailored custom solution or external integration addressing {res.problem_domain.lower()} requirements."
                if not res.rationale or "suitable" not in res.rationale.lower():
                    res.rationale = f"No matches found. None of our current products are suitable for this connection's problem."
                if not res.recommended_next_step:
                    res.recommended_next_step = "Acknowledge capability boundary. Do not propose existing products unless custom engineering is commissioned."

            return res
        return None
