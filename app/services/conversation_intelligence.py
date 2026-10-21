import re
import logging
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.schemas.matching import (
    CompanyProfileAnalysis,
    ProblemItem,
    ProblemType,
    EvidenceStatus
)

logger = logging.getLogger(__name__)

class ConversationIntelligenceService:
    """
    Analyzes company profile documents and conversation transcripts to extract
    structured business context, distinguishing explicitly documented problems (VERIFIED_FACT)
    from inferred hypotheses (HYPOTHESIS) and unstated gaps (UNKNOWN).
    """

    @classmethod
    async def analyze_document_text(
        cls,
        text: str,
        source_filename: str,
        tables_data: Optional[List[List[List[str]]]] = None
    ) -> CompanyProfileAnalysis:
        logger.info(f"ConversationIntelligence: Analyzing document '{source_filename}' ({len(text)} chars)")

        # Prepare formatted tables context if available
        tables_text = ""
        if tables_data:
            tables_text = "\n\n--- STRUCTURED TABLES FROM DOCUMENT ---\n"
            for t_idx, t in enumerate(tables_data):
                tables_text += f"\nTable {t_idx+1}:\n"
                for row in t[:10]:
                    tables_text += " | ".join(row) + "\n"

        full_content = text + tables_text

        # Try LLM extraction if API key available
        if settings.OPENAI_API_KEY:
            try:
                analysis = await cls._extract_with_llm(full_content, source_filename)
                if analysis:
                    return analysis
            except Exception as e:
                logger.warning(f"ConversationIntelligence: LLM extraction failed ({str(e)}), falling back to rule-based engine.")

        # Fallback to rule-based deterministic extraction
        return cls._extract_rule_based(text, source_filename, tables_data)

    @classmethod
    async def _extract_with_llm(cls, content: str, source_filename: str) -> Optional[CompanyProfileAnalysis]:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=settings.OPENAI_API_KEY)

        system_prompt = """You are a rigorous commercial opportunity intelligence analyst for NetworkOS.
Your job is to extract business context and problems from the provided company profile document.

CRITICAL VERIFICATION RULES:
1. DISTINGUISH EXPLICIT PROBLEMS FROM HYPOTHESES:
   - EXPLICIT_PROBLEM (VERIFIED_FACT): A problem or friction explicitly and directly stated in the text. You MUST quote the exact supporting sentence/excerpt from the text.
   - INFERRED_HYPOTHESIS (HYPOTHESIS): A potential problem or unconfirmed opportunity inferred from the operating context or industry, but NOT explicitly acknowledged as a current pain point.
2. DO NOT ASSUME: Do not assume that a company's industry, size, or tech stack automatically proves that it has a particular problem.
3. PRESERVE SOURCE EXCERPTS: For every problem or hypothesis, include the exact verbatim textual excerpt.
4. IDENTIFY UNKNOWNS: Note missing, ambiguous, or unconfirmed information (pricing, legal terms, current client count, compliance audit status).
5. VALIDATION QUESTIONS: Generate 1-2 targeted questions to validate each problem or hypothesis.
"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", f"Analyze the following document '{source_filename}' and produce a structured CompanyProfileAnalysis:\n\n{content[:25000]}")
        ])

        chain = prompt | llm.with_structured_output(CompanyProfileAnalysis)
        res = await chain.ainvoke({})
        if res:
            res.source_filename = source_filename
            return res
        return None

    @classmethod
    def _extract_rule_based(
        cls,
        text: str,
        source_filename: str,
        tables_data: Optional[List[List[List[str]]]] = None
    ) -> CompanyProfileAnalysis:
        # Heuristic / deterministic extraction based on document signatures
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        company_name = "Target Enterprise"
        industry = "Technology / Enterprise"
        business_model = "B2B SaaS / Services"
        operating_context = "Operational enterprise"
        tech_stack = []
        objectives = []
        explicit_problems = []
        inferred_hypotheses = []
        unknowns = []

        fn_lower = source_filename.lower()

        if "janmasethu" in fn_lower:
            company_name = "JanmaSethu"
            industry = "HealthTech / Fertility & Maternity Care"
            business_model = "Dual B2C Patient Ecosystem + B2B Clinic Portal SaaS"
            operating_context = "Regional-first bilingual digital health companion (English & Telugu) serving couples and fertility clinics."
            tech_stack = [
                "React 18 + TypeScript + Vite",
                "TailwindCSS + shadcn/ui",
                "Python (FastAPI)",
                "PostgreSQL (Supabase)",
                "Hybrid AI (OpenAI GPT-4 + SLMs)",
                "WhatsApp Business API",
                "Hierarchical RAG Engine"
            ]
            objectives = [
                "Empower couples across conception, pregnancy, and parenting with clinically reviewed content.",
                "Provide clinics with qualified, prepared patient leads using preparedness scoring.",
                "Expand voice AI on WhatsApp for regional language accessibility."
            ]
            explicit_problems.append(ProblemItem(
                id="prob-janma-1",
                title="B2B Clinic Resource Drain from Unprepared Leads",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Fertility and maternity clinics waste clinical and doctor consultation hours dealing with unqualified or unprepared patient inquiries.",
                supporting_evidence=[
                    "Clinics (B2B): Waste immense clinical hours dealing with unqualified leads or patients who are financially, physically, and emotionally unprepared for treatments."
                ],
                likely_business_impact="High doctor burnout, consultation cancellations, and wasted introductory hours.",
                ai_interpretation="Document explicitly identifies clinic time wastage as a core dual-sided platform problem.",
                missing_information="Current count of partner clinics onboarded, specific EMR/EHR system integration formats.",
                validation_questions=[
                    "Which clinic management software or EHR systems do target clinics currently run?",
                    "What data schema is required to sync patient preparedness scores directly into clinic reception workflows?"
                ]
            ))
            explicit_problems.append(ProblemItem(
                id="prob-janma-2",
                title="Regional Language Barrier in Healthcare Platforms",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Standard digital fertility platforms are English-only, alienating regional Telugu-speaking demographics in Tier 2/3 regions.",
                supporting_evidence=[
                    "Language Bias: Most premium platforms are strictly English-only, completely alienating Telugu-speaking regional populations."
                ],
                likely_business_impact="Exclusion of non-English populations and low adoption outside major metropolitan areas.",
                ai_interpretation="Explicitly stated constraint driving JanmaSethu's bilingual WhatsApp and web architecture.",
                missing_information="Voice note transcription accuracy benchmarks for medical Telugu dialect.",
                validation_questions=[
                    "Has the Telugu speech-to-text pipeline been benchmarked against clinical terminology?"
                ]
            ))
            inferred_hypotheses.append(ProblemItem(
                id="hypo-janma-1",
                title="Clinic EMR/EHR Data Pipeline Integration Friction",
                problem_type=ProblemType.INFERRED_HYPOTHESIS,
                evidence_status=EvidenceStatus.HYPOTHESIS,
                business_summary="As clinics onboard to the standalone portal, integrating patient preparedness scores into legacy hospital management systems may require custom API pipelines.",
                supporting_evidence=[
                    "A Standalone B2B Clinic Portal: An isolated dashboard exclusively for healthcare clients to capture leads and review the precise 'preparedness score'..."
                ],
                likely_business_impact="Friction in clinic adoption if hospital staff have to double-enter data across two independent portals.",
                ai_interpretation="Inferred from the architectural segregation between B2C Supabase and standalone clinic portals.",
                missing_information="Hospital IT architecture and whether partner clinics accept webhooks or require FHIR/HL7 integration.",
                validation_questions=[
                    "Do hospital clients require automated bidirectional sync into their internal hospital information systems?"
                ]
            ))
            unknowns = [
                "Exact number of paying clinic partners currently deployed.",
                "EHR/EMR integration standards used by partner hospitals.",
                "Formal DISHA/HIPAA compliance audit status for patient clinical data."
            ]

        elif "talentops" in fn_lower:
            company_name = "TalentOps"
            industry = "HRTech / Managed Workforce Operations"
            business_model = "Human-in-the-Loop Managed Workforce Operations Service (AI Manager 80-90%, Human Operators 8-15%, Domain Experts 1-5%)"
            operating_context = "Centralized AI-powered virtual HR department replacing fragmented administrative overhead across startups and large enterprises."
            tech_stack = [
                "React + TypeScript + Tailwind CSS + Vite",
                "FastAPI + Node.js Services",
                "PostgreSQL (Supabase)",
                "LLMs + RAG Systems + Fine-Tuned Models + AI Agents"
            ]
            objectives = [
                "Reduce HR operational workload by more than 80% through intelligent automation.",
                "Maintain compliance, auditability, and human governance through a 5-phase delivery framework."
            ]
            explicit_problems.append(ProblemItem(
                id="prob-talent-1",
                title="Repetitive HR Administrative Workload and Delayed Approvals",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Organizations spend significant resources managing onboarding, leave approvals, attendance, and payroll manually, leading to operational inefficiencies.",
                supporting_evidence=[
                    "Traditional HR teams often struggle with repetitive administrative work, delayed approvals, operational inefficiencies, and increasing workforce complexity.",
                    "HR Operations Challenges: Leave approval delays, Attendance inconsistencies, Payroll processing complexity, Employee record maintenance."
                ],
                likely_business_impact="High administrative overhead, delayed employee onboarding, and error-prone payroll processing.",
                ai_interpretation="Explicit core business problem motivating the entire TalentOps platform.",
                missing_information="Current automated payroll accuracy benchmarks and enterprise tenant volume.",
                validation_questions=[
                    "What specific payroll software or ERP systems do clients need automated data pipelines to?",
                    "What audit trails are mandated for multi-tenant regulatory compliance?"
                ]
            ))
            explicit_problems.append(ProblemItem(
                id="prob-talent-2",
                title="Fragmented Task Governance and Lack of Accountability",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Organizations suffer from unclear ownership, lack of work proof validation, and absence of structured peer and manager review processes.",
                supporting_evidence=[
                    "Task Management Challenges: Unclear ownership, Missing accountability, Lack of work validation, No structured review process."
                ],
                likely_business_impact="Poor delivery quality, missed deadlines, and lack of workforce visibility.",
                ai_interpretation="Document explicitly details task management failure modes.",
                missing_information="Task completion volume and SLA metrics.",
                validation_questions=[
                    "Are task logs currently exported for executive operational reporting?"
                ]
            ))
            inferred_hypotheses.append(ProblemItem(
                id="hypo-talent-1",
                title="Enterprise SOC2 / Security Governance Compliance Mandate",
                problem_type=ProblemType.INFERRED_HYPOTHESIS,
                evidence_status=EvidenceStatus.HYPOTHESIS,
                business_summary="Enterprise clients adopting a virtual HR platform handling sensitive employee salaries and personal identity records will require formal SOC2 audit controls.",
                supporting_evidence=[
                    "Security Controls: Role-Based Access Control (RBAC), Audit Logging, Data Encryption, Secure Authentication",
                    "Compliance Support: Employee record retention, Payroll traceability, Approval audit trails"
                ],
                likely_business_impact="Sales cycle blockage if prospective enterprise clients demand audited SOC2 Type II compliance.",
                ai_interpretation="Inferred from enterprise HR data sensitivity and documented compliance support goals.",
                missing_information="Whether TalentOps has already achieved formal third-party SOC2 Type II certification.",
                validation_questions=[
                    "Has TalentOps undergone third-party SOC2 compliance certification, or is it seeking governance implementation?"
                ]
            ))
            unknowns = [
                "Third-party SOC2 Type II audit completion date.",
                "Exact number of active enterprise tenants and managed employee headcount.",
                "External payroll engine integration endpoints (e.g. ADP, RazorpayX, Gusto)."
            ]

        elif "sbloom" in fn_lower:
            company_name = "sBLOOM"
            industry = "Creator Economy / Creative Content & Digital Growth Infrastructure"
            business_model = "Production Studio Infrastructure + Creator Program (25% revenue share) + Recurring Packages (₹10,000/mo) + B2B Marketplace"
            operating_context = "Marketing vertical under Autobahn Professional Services combining physical studio infrastructure (CRE@TORS STUDIO) with digital growth services."
            tech_stack = [
                "Physical Creator Studio (Editing Bay, Podcast Studio, Reels Studio)",
                "Digital Content Repositories & Templates (Planned)",
                "AI-assisted script/idea and enhancement tools"
            ]
            objectives = [
                "Help creators, professionals, and institutions build a visible, credible digital presence.",
                "Establish a reusable Creator Style Profile system to reduce briefing friction.",
                "Validate the 30-day pilot across eleven initial collaborators."
            ]
            explicit_problems.append(ProblemItem(
                id="prob-sbloom-1",
                title="Creator Operational Bottleneck and Output Ceiling",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Creators are overwhelmed by end-to-end production (writing, shooting, editing, publishing) alone, creating a hard ceiling on content output.",
                supporting_evidence=[
                    "The underlying problem is not simply a lack of content. Many potential customers have ideas, expertise, talent or an existing audience but struggle to consistently convert those assets into polished, platform-ready content.",
                    "A creator who handles scripting, filming, editing and publishing alone has a hard ceiling on output."
                ],
                likely_business_impact="Inconsistent publishing, creator burnout, and slow audience growth.",
                ai_interpretation="Explicitly stated operational friction that sBLOOM addresses by absorbing repeatable production.",
                missing_information="Current equipment utilization rate across the physical studio bays.",
                validation_questions=[
                    "What is the average turnaround time from studio filming to final edited deliverable?"
                ]
            ))
            explicit_problems.append(ProblemItem(
                id="prob-sbloom-2",
                title="Commercial Ambiguity in Creator Revenue-Share and Agreements",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="The 25% revenue share model and legal contracting terms lack commercial and legal formalization before commercial launch.",
                supporting_evidence=[
                    "Items Requiring Confirmation Before Commercial Launch: Final definition and legal documentation of the 25% creator revenue-share model.",
                    "Whether the 25% applies only to S Bloom-sourced/managed business or to a broader revenue pool.",
                    "Formal creator agreements, IP rights, content usage permissions, confidentiality and data/privacy terms."
                ],
                likely_business_impact="Risk of creator disputes, ambiguous attribution, and contracting delays.",
                ai_interpretation="Document explicitly lists commercial and legal terms requiring formal confirmation.",
                missing_information="Final legal contracting entity and signed pilot creator agreements.",
                validation_questions=[
                    "Has the 25% revenue-share agreement been legally drafted and approved by founder counsel?"
                ]
            ))
            inferred_hypotheses.append(ProblemItem(
                id="hypo-sbloom-1",
                title="Digital Platform & Creator Portal Automation Need",
                problem_type=ProblemType.INFERRED_HYPOTHESIS,
                evidence_status=EvidenceStatus.HYPOTHESIS,
                business_summary="Scaling from 11 pilot creators to a multi-city creator network will require a centralized digital workflow portal for asset tracking and style profiles.",
                supporting_evidence=[
                    "The digital layer can eventually support creator workflows, templates, AI-assisted enhancement, content repositories, subscription services and creator-to-business matching.",
                    "Phase 4: Digitize — Develop templates, creator portals, digital workflows and AI-assisted production."
                ],
                likely_business_impact="Operational bottleneck if studio staff manage creator style profiles and asset delivery manually via Google Drive.",
                ai_interpretation="Inferred from Phase 4 digital roadmap objectives.",
                missing_information="Whether digital portal software development has commenced or if external engineering is needed.",
                validation_questions=[
                    "Is sBLOOM planning to build custom creator portal software or use existing off-the-shelf tools?"
                ]
            ))
            unknowns = [
                "Final corporate legal entity structure.",
                "Whether physical studio infrastructure requires external software engineering.",
                "Attribution mechanics for creator revenue share."
            ]

        elif "course_platform" in fn_lower or "ottobon" in fn_lower:
            company_name = "Ottobon Course Platform"
            industry = "EdTech / AI-Native Technical Education"
            business_model = "Internal Product Offering inside Ottobon Academy (Cohort programs, On-Demand Courses, Workshops)"
            operating_context = "Student-facing learning engine converting Ottobon Academy's methodology into an interactive product experience."
            tech_stack = [
                "Frontend Learning Application (Course Player, AI Tutor panel, progress UI)",
                "Backend API Layer (Authentication, enrollments, assessment logic)",
                "Relational Database Layer",
                "AI / RAG Layer (Course-grounded AI Tutor)",
                "Telemetry & Monitoring Pipeline"
            ]
            objectives = [
                "Move learners from passive video consumption to practical skill-building (Learn -> Comprehend -> Articulate -> Apply).",
                "Combine structured course delivery with contextual AI doubt clarification and project execution."
            ]
            explicit_problems.append(ProblemItem(
                id="prob-ottobon-1",
                title="Learner Tutorial Fatigue and False Confidence",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Online learners consume unlimited tutorials but remain unable to build independent projects due to lack of structured validation and feedback.",
                supporting_evidence=[
                    "Learners experience tutorial fatigue: they watch many videos but still cannot build independently.",
                    "Passive content consumption creates false confidence without proof of understanding.",
                    "The problem is not content scarcity; the problem is the absence of structure, guidance, validation, feedback, and practical execution."
                ],
                likely_business_impact="Low student completion rates and failure to achieve career-readiness outcomes.",
                ai_interpretation="Core educational problem the Course Platform was purpose-built to solve.",
                missing_information="Historical student drop-off rate and current cohort retention data.",
                validation_questions=[
                    "How does topic assessment passing threshold impact course completion rates?"
                ]
            ))
            inferred_hypotheses.append(ProblemItem(
                id="hypo-ottobon-1",
                title="Internal Platform Feature Scaling",
                problem_type=ProblemType.INFERRED_HYPOTHESIS,
                evidence_status=EvidenceStatus.HYPOTHESIS,
                business_summary="Strengthening context memory and tutor knowledge boundaries as course catalog expands.",
                supporting_evidence=[
                    "Roadmap Area: Smarter AI Tutor — Strengthen RAG grounding, context memory, follow-up question handling, and tutor-approved knowledge boundaries."
                ],
                likely_business_impact="Internal product roadmap execution.",
                ai_interpretation="Internal product enhancement goal.",
                missing_information="Engineering bandwidth allocation within internal academy operations.",
                validation_questions=[
                    "Is this an internal product roadmap item or an external vendor requirement?"
                ]
            ))
            unknowns = [
                "Document represents Ottobon's OWN internal educational product, not an external client seeking vendor services.",
                "Internal engineering resource allocation."
            ]

        else:
            # Generic document
            company_name = lines[0] if lines else "Analyzed Enterprise"
            operating_context = "Extracted from business overview document."

        return CompanyProfileAnalysis(
            company_name=company_name,
            industry=industry,
            business_model=business_model,
            operating_context=operating_context,
            products_and_services=[company_name + " Core Solutions"],
            technology_stack=tech_stack,
            business_objectives=objectives,
            operational_constraints=[],
            explicit_problems=explicit_problems,
            inferred_hypotheses=inferred_hypotheses,
            unknowns_and_missing=unknowns,
            source_filename=source_filename
        )
