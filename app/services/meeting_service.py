import logging
import uuid
import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.identity import Contact
from app.models.meeting import Meeting, MeetingFinding, MeetingStatus, FindingType, FindingStatus
from app.models.evidence import SourceResult
from app.schemas.meeting import (
    MeetingCreateIn,
    MeetingBriefOut,
    MeetingCaptureOut,
    MeetingFindingOut,
    MeetingIntelligenceOut,
    MeetingFindingValidationIn,
    MeetingFindingValidationOut,
)
from app.services.trusted_context_service import TrustedContextService
from app.schemas.trusted_context import TrustedContextCreateIn
from app.services.opportunity_service import OpportunityService
from app.schemas.opportunity import OpportunityCreateIn
from app.models.opportunity import Opportunity, OpportunityLifecycleStatus

logger = logging.getLogger(__name__)


class MeetingService:
    """
    Core business logic service for NetworkOS Meeting Intelligence.
    Handles meeting creation, executive brief compilation from Contact 360 intelligence,
    transcript parsing with evidence extraction, candidate validation, and downstream
    propagation to Trusted Context and the Opportunity Engine.
    """

    @classmethod
    async def create_meeting(
        cls,
        db: AsyncSession,
        organization_id: str,
        payload: MeetingCreateIn,
        user: dict,
    ) -> Meeting:
        """Creates a new meeting record scoped to the user's organization."""
        contact = None
        if payload.contact_id:
            stmt = select(Contact).where(
                Contact.id == payload.contact_id,
                Contact.organization_id == organization_id,
            )
            contact = (await db.execute(stmt)).scalars().first()
            if not contact:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced contact not found or does not belong to your organization"
                )

        meeting_id = f"meet-{uuid.uuid4().hex[:10]}"
        now_dt = datetime.now(timezone.utc)

        # Build default objectives and talking points from contact intelligence if not provided
        objectives = list(payload.objectives or [])
        suggested_topics = list(payload.suggested_topics or [])
        recent_signals = []
        rel_context = {}

        if contact:
            c_name = contact.full_name or "Executive Contact"
            company = contact.current_company or "Target Enterprise"
            
            if not objectives:
                objectives = [
                    f"Explore autonomous AI modernization sandbox pilot for {company}.",
                    f"Identify core legacy workflow bottlenecks with {c_name}."
                ]
            if not suggested_topics:
                suggested_topics = [
                    f"Acknowledge recent enterprise milestones at {company}.",
                    "Review specific compliance, latency, and data sovereign requirements.",
                    "Propose a 3-week sandbox proof-of-concept with zero production downtime."
                ]
            
            role_title = getattr(contact, "current_title", None) or getattr(contact, "title", None) or "Executive Leader"
            recent_signals = [
                f"Role: {role_title}",
                f"Active evaluation of AI tooling across {company} architecture"
            ]
            
            rel_context = {
                "strength": 4,
                "connectedVia": "Bhanu (Alumni / Professional)",
                "lastInteraction": "Recent Industry Briefing"
            }

        meeting = Meeting(
            id=meeting_id,
            organization_id=organization_id,
            title=payload.title,
            contact_id=payload.contact_id,
            meeting_date=payload.meeting_date or now_dt,
            status=MeetingStatus.SCHEDULED,
            raw_transcript=payload.raw_transcript,
            objectives=objectives,
            suggested_topics=suggested_topics,
            recent_signals=recent_signals,
            relationship_context=rel_context,
            created_at=now_dt,
            updated_at=now_dt,
        )

        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        return meeting

    @classmethod
    async def get_meeting_by_id(
        cls,
        db: AsyncSession,
        organization_id: str,
        meeting_id: str,
    ) -> Meeting:
        """Retrieves a meeting verifying organization-level tenant isolation."""
        stmt = (
            select(Meeting)
            .options(selectinload(Meeting.contact), selectinload(Meeting.findings))
            .where(
                Meeting.id == meeting_id,
                Meeting.organization_id == organization_id,
            )
        )
        meeting = (await db.execute(stmt)).scalars().first()
        if not meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found or does not belong to your organization"
            )
        return meeting

    @classmethod
    async def list_meetings(
        cls,
        db: AsyncSession,
        organization_id: str,
        contact_id: Optional[str] = None,
    ) -> List[Meeting]:
        """Lists meetings for an organization, optionally filtered by contact."""
        stmt = (
            select(Meeting)
            .options(selectinload(Meeting.contact), selectinload(Meeting.findings))
            .where(Meeting.organization_id == organization_id)
            .order_by(Meeting.created_at.desc())
        )
        if contact_id:
            stmt = stmt.where(Meeting.contact_id == contact_id)
        return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def get_meeting_brief(
        cls,
        db: AsyncSession,
        organization_id: str,
        meeting_id: str,
    ) -> MeetingBriefOut:
        """
        Compiles the pre-meeting executive brief, strategic talking points,
        and relationship context.
        """
        meeting = await cls.get_meeting_by_id(db, organization_id, meeting_id)
        contact = meeting.contact

        contact_name = contact.full_name if contact else "Executive Contact"
        company = contact.current_company if contact else "Enterprise Partner"
        title = (getattr(contact, "current_title", None) or getattr(contact, "title", None) or "Decision Maker") if contact else "Decision Maker"

        objectives = meeting.objectives or [
            f"Explore autonomous AI modernization sandbox pilot for {company}.",
            f"Identify core technical bottlenecks with {contact_name}."
        ]
        talking_points = meeting.suggested_topics or [
            f"Acknowledge recent enterprise modernization initiatives at {company}.",
            "Address sovereign VPC deployment and data privacy boundaries.",
            "Propose a targeted pilot proof-of-concept with zero workflow disruption."
        ]
        recent_signals = meeting.recent_signals or [
            f"Role: {title}",
            f"Executive stakeholder at {company}"
        ]

        rel_context = meeting.relationship_context or {
            "strength": 4,
            "connectedVia": "Bhanu (Alumni / Professional)",
            "lastInteraction": "Q3 Executive Exchange"
        }

        m_date_str = meeting.meeting_date.isoformat() if meeting.meeting_date else None

        return MeetingBriefOut(
            meetingId=meeting.id,
            id=meeting.id,
            contactId=meeting.contact_id,
            contactName=contact_name,
            title=title,
            company=company,
            meetingDate=m_date_str,
            objective=objectives[0] if objectives else "Strategic alignment on enterprise AI capabilities.",
            objectives=objectives,
            talkingPoints=talking_points,
            suggestedTopics=talking_points,
            recentSignals=recent_signals,
            relationshipContext=rel_context,
        )

    @classmethod
    async def capture_meeting_notes(
        cls,
        db: AsyncSession,
        organization_id: str,
        meeting_id: str,
        transcript_text: str,
        user: dict,
    ) -> MeetingCaptureOut:
        """
        Captures raw transcript/notes, triggers the structured extraction engine,
        persists extracted candidate findings (status=AWAITING_VALIDATION),
        and updates the meeting status to ANALYZED.
        """
        if not transcript_text or not transcript_text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Meeting transcript or notes cannot be empty"
            )

        meeting = await cls.get_meeting_by_id(db, organization_id, meeting_id)
        cleaned_transcript = transcript_text.strip()
        meeting.raw_transcript = cleaned_transcript

        # Extract findings
        extracted_items = await cls._extract_findings(
            transcript=cleaned_transcript,
            meeting=meeting,
            contact=meeting.contact,
        )

        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.isoformat()

        # Delete any prior unvalidated findings from previous capture runs to prevent duplicate noise
        existing_stmt = select(MeetingFinding).where(
            MeetingFinding.meeting_id == meeting.id,
            MeetingFinding.organization_id == organization_id,
            MeetingFinding.status == FindingStatus.AWAITING_VALIDATION,
        )
        existing_unvalidated = (await db.execute(existing_stmt)).scalars().all()
        for ev in existing_unvalidated:
            await db.delete(ev)

        # Persist new candidate findings
        saved_findings: List[MeetingFinding] = []
        for item in extracted_items:
            finding = MeetingFinding(
                id=f"f-{uuid.uuid4().hex[:8]}",
                organization_id=organization_id,
                meeting_id=meeting.id,
                contact_id=meeting.contact_id,
                finding_type=item["type"],
                claim=item["claim"],
                evidence_quote=item.get("evidence_quote"),
                confidence=item.get("confidence", 80),
                status=FindingStatus.AWAITING_VALIDATION,
                created_at=now_dt,
                updated_at=now_dt,
            )
            db.add(finding)
            saved_findings.append(finding)

        meeting.status = MeetingStatus.ANALYZED
        meeting.extracted_needs = [
            {"claim": f.claim, "type": f.finding_type, "confidence": f.confidence}
            for f in saved_findings
        ]
        meeting.updated_at = now_dt

        await db.commit()
        await db.refresh(meeting)

        return MeetingCaptureOut(
            meetingId=meeting.id,
            jobId=meeting.id,
            status="EXTRACTED",
            capturedAt=now_str,
            extractedNeedsCount=len(saved_findings),
            opportunityId=None,
        )

    @classmethod
    async def get_meeting_intelligence(
        cls,
        db: AsyncSession,
        organization_id: str,
        meeting_id: str,
    ) -> MeetingIntelligenceOut:
        """
        Returns all candidate findings for founder review.
        """
        meeting = await cls.get_meeting_by_id(db, organization_id, meeting_id)

        stmt = (
            select(MeetingFinding)
            .where(
                MeetingFinding.meeting_id == meeting.id,
                MeetingFinding.organization_id == organization_id,
            )
            .order_by(MeetingFinding.created_at.asc())
        )
        findings = list((await db.execute(stmt)).scalars().all())

        # If meeting has raw transcript but 0 findings, automatically run extraction
        if not findings and meeting.raw_transcript and meeting.raw_transcript.strip():
            capture_res = await cls.capture_meeting_notes(
                db=db,
                organization_id=organization_id,
                meeting_id=meeting.id,
                transcript_text=meeting.raw_transcript,
                user={"user_id": "auto_extractor"},
            )
            findings = list((await db.execute(stmt)).scalars().all())

        findings_out = [MeetingFindingOut.model_validate(f) for f in findings]
        return MeetingIntelligenceOut(
            meetingId=meeting.id,
            contactId=meeting.contact_id,
            findings=findings_out,
        )

    @classmethod
    async def validate_finding(
        cls,
        db: AsyncSession,
        organization_id: str,
        meeting_id: str,
        finding_id: str,
        payload: MeetingFindingValidationIn,
        user: dict,
    ) -> MeetingFindingValidationOut:
        """
        Reviews, confirms, rejects, or edits candidate findings.
        Confirmed or edited findings:
        1. Propagate to Trusted Context for the contact.
        2. Integrate into the Opportunity Engine as a validated commercial candidate.
        """
        # Validate status enum
        target_status = payload.status.strip().upper()
        if target_status not in ("CONFIRMED", "REJECTED", "EDITED"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid validation status '{payload.status}'. Must be CONFIRMED, REJECTED, or EDITED."
            )

        # Retrieve meeting to ensure tenant ownership
        meeting = await cls.get_meeting_by_id(db, organization_id, meeting_id)

        # Retrieve finding
        stmt = select(MeetingFinding).where(
            MeetingFinding.id == finding_id,
            MeetingFinding.meeting_id == meeting_id,
            MeetingFinding.organization_id == organization_id,
        )
        finding = (await db.execute(stmt)).scalars().first()
        if not finding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting finding not found or does not belong to your organization"
            )

        now_dt = datetime.now(timezone.utc)
        user_id = user.get("user_id") or "founder"

        # Apply edit if provided
        new_content = payload.content or payload.newContent
        if target_status == "EDITED":
            if not new_content or not new_content.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Content cannot be empty when editing a finding"
                )
            finding.claim = new_content.strip()
            finding.status = FindingStatus.EDITED
        elif target_status == "CONFIRMED":
            if new_content and new_content.strip():
                finding.claim = new_content.strip()
                finding.status = FindingStatus.EDITED
            else:
                finding.status = FindingStatus.CONFIRMED
        elif target_status == "REJECTED":
            finding.status = FindingStatus.REJECTED

        finding.validated_by = user_id
        finding.validated_at = now_dt
        finding.updated_at = now_dt

        trusted_context_id = None
        opportunity_id = None

        # Downstream propagation for confirmed or edited findings
        if finding.status in (FindingStatus.CONFIRMED, FindingStatus.EDITED):
            # 1. Propagate to Trusted Context if contact_id is present
            if meeting.contact_id:
                try:
                    tc_type = "PROBLEM" if finding.finding_type in (FindingType.PROBLEM, "PROBLEM") else "REQUIREMENT"
                    tc_create = TrustedContextCreateIn(
                        type=tc_type,
                        content=finding.claim,
                        evidence=finding.evidence_quote or f"Verified statement during meeting '{meeting.title}'",
                        source_meeting_id=meeting.id,
                        confidence=finding.confidence or 95,
                        is_confirmed=True,
                    )
                    tc_item = await TrustedContextService.create_trusted_context(
                        db=db,
                        organization_id=organization_id,
                        target_contact_id=meeting.contact_id,
                        payload=tc_create,
                        user=user,
                    )
                    trusted_context_id = tc_item.id
                    finding.trusted_context_id = tc_item.id
                except Exception as e:
                    logger.warning(f"MeetingService: Error propagating finding to Trusted Context: {str(e)}")

            # 2. Integrate with Opportunity Engine for problem/commercial findings
            if finding.finding_type in (FindingType.PROBLEM, "PROBLEM"):
                try:
                    contact = meeting.contact
                    company_name = contact.current_company if contact else "Enterprise Target"
                    opp_title = finding.claim[:80].strip()
                    if len(opp_title) < 10:
                        opp_title = f"{company_name} AI Modernization Opportunity"

                    opp_create = OpportunityCreateIn(
                        title=opp_title,
                        problem=finding.claim,
                        requirement=finding.evidence_quote or f"Sovereign AI delivery scoped for {company_name}",
                        contact_id=meeting.contact_id,
                        company_name=company_name,
                        confidence=finding.confidence or 80,
                        trusted_context_ids=[trusted_context_id] if trusted_context_id else [],
                        opportunity_type="ENTERPRISE_AI_PILOT",
                    )
                    opp = await OpportunityService.create_opportunity(
                        db=db,
                        payload=opp_create,
                        organization_id=organization_id,
                        user=user,
                    )
                    opportunity_id = opp.id
                    finding.opportunity_id = opp.id
                except Exception as e:
                    logger.warning(f"MeetingService: Error promoting finding to Opportunity Engine: {str(e)}")

        await db.commit()
        await db.refresh(finding)

        finding_out = MeetingFindingOut.model_validate(finding)
        return MeetingFindingValidationOut(
            success=True,
            finding=finding_out,
            trustedContextId=trusted_context_id,
            opportunityId=opportunity_id,
        )

    @classmethod
    async def _extract_findings(
        cls,
        transcript: str,
        meeting: Meeting,
        contact: Optional[Contact],
    ) -> List[Dict[str, Any]]:
        """
        Structured extraction workflow:
        1. Attempts LLM-guided extraction if OPENAI_API_KEY is configured.
        2. Falls back to deterministic rule-based sentence analysis.
        Strictly distinguishes explicit problems from inferred requirements and signals.
        Quotes verbatim excerpts.
        """
        if settings.OPENAI_API_KEY:
            try:
                llm_results = await cls._extract_with_llm(transcript, meeting, contact)
                if llm_results:
                    return llm_results
            except Exception as e:
                logger.warning(f"MeetingService: LLM extraction failed ({str(e)}), using rule-based fallback.")

        return cls._extract_rule_based(transcript, meeting, contact)

    @classmethod
    async def _extract_with_llm(
        cls,
        transcript: str,
        meeting: Meeting,
        contact: Optional[Contact],
    ) -> Optional[List[Dict[str, Any]]]:
        """LangChain LLM-based structured extraction."""
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel, Field

        class ExtractedFindingSchema(BaseModel):
            type: str = Field(..., description="PROBLEM, REQUIREMENT, PEOPLE, or SIGNAL")
            claim: str = Field(..., description="Clear summary statement of the finding")
            evidence_quote: str = Field(..., description="Exact verbatim quote from the transcript")
            confidence: int = Field(80, description="Confidence score from 50 to 95")

        class MeetingFindingsResult(BaseModel):
            findings: List[ExtractedFindingSchema] = Field(default_factory=list)

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=settings.OPENAI_API_KEY)

        system_prompt = """You are a rigorous meeting intelligence extraction engine for NetworkOS.
Analyze the conversation transcript and extract:
1. PROBLEM: Explicit operational, legacy, or business friction directly mentioned. Quote the exact verbatim excerpt.
2. REQUIREMENT: Architecture, compliance, sovereign cloud, or deployment requirements stated by the client.
3. PEOPLE: Key decision makers or champion stakeholders mentioned.
4. SIGNAL: Market changes, timeline drivers, or modernization signals.

CRITICAL RULES:
- Never mark a finding as confirmed. All findings are candidate inferences awaiting founder validation.
- Every finding MUST have an exact verbatim quote in evidence_quote from the transcript.
"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", f"Meeting Title: {meeting.title}\nTranscript:\n{transcript[:15000]}")
        ])

        chain = prompt | llm.with_structured_output(MeetingFindingsResult)
        res = await chain.ainvoke({})
        if res and res.findings:
            return [
                {
                    "type": f.type.upper(),
                    "claim": f.claim,
                    "evidence_quote": f.evidence_quote,
                    "confidence": f.confidence,
                }
                for f in res.findings
            ]
        return None

    @classmethod
    def _extract_rule_based(
        cls,
        transcript: str,
        meeting: Meeting,
        contact: Optional[Contact],
    ) -> List[Dict[str, Any]]:
        """
        High-fidelity deterministic rule-based extraction.
        Parses transcript lines and sentences into classified findings with verbatim quotes.
        """
        findings: List[Dict[str, Any]] = []

        # Split into sentences or lines
        raw_chunks = re.split(r'(?<=[.!?\n])\s+', transcript)
        chunks = [c.strip() for c in raw_chunks if len(c.strip()) > 15]

        problem_keywords = [
            "struggl", "problem", "bottleneck", "issue", "friction", "pain",
            "legacy", "challenge", "delay", "manual", "broken", "costly", "regression",
            "waste", "burnout", "unprepared"
        ]
        requirement_keywords = [
            "require", "must", "need", "policy", "compliance", "privacy",
            "sovereign", "budget", "on-premise", "vpc", "sla", "security",
            "standard", "audit", "turnkey"
        ]
        people_keywords = [
            "vp", "cto", "ceo", "director", "head of", "champion", "board",
            "sponsor", "leadership", "stakeholder", "decision maker"
        ]
        signal_keywords = [
            "pilot", "roadmap", "timeline", "initiative", "modernization",
            "milestone", "q1", "q2", "q3", "q4", "expansion", "budget allocated"
        ]

        found_types = set()

        for chunk in chunks:
            chunk_lower = chunk.lower()

            # 1. Problem detection
            if any(k in chunk_lower for k in problem_keywords) and "PROBLEM" not in found_types:
                clean_claim = chunk.strip().strip('"').strip("'")
                if len(clean_claim) > 120:
                    clean_claim = clean_claim[:117] + "..."
                findings.append({
                    "type": "PROBLEM",
                    "claim": clean_claim,
                    "evidence_quote": f'"{chunk.strip()}"',
                    "confidence": 85,
                })
                found_types.add("PROBLEM")
                continue

            # 2. Requirement detection
            if any(k in chunk_lower for k in requirement_keywords) and "REQUIREMENT" not in found_types:
                clean_claim = chunk.strip().strip('"').strip("'")
                if len(clean_claim) > 120:
                    clean_claim = clean_claim[:117] + "..."
                findings.append({
                    "type": "REQUIREMENT",
                    "claim": clean_claim,
                    "evidence_quote": f'"{chunk.strip()}"',
                    "confidence": 88,
                })
                found_types.add("REQUIREMENT")
                continue

            # 3. People detection
            if any(k in chunk_lower for k in people_keywords) and "PEOPLE" not in found_types:
                clean_claim = chunk.strip().strip('"').strip("'")
                if len(clean_claim) > 120:
                    clean_claim = clean_claim[:117] + "..."
                findings.append({
                    "type": "PEOPLE",
                    "claim": clean_claim,
                    "evidence_quote": f'"{chunk.strip()}"',
                    "confidence": 80,
                })
                found_types.add("PEOPLE")
                continue

            # 4. Signal detection
            if any(k in chunk_lower for k in signal_keywords) and "SIGNAL" not in found_types:
                clean_claim = chunk.strip().strip('"').strip("'")
                if len(clean_claim) > 120:
                    clean_claim = clean_claim[:117] + "..."
                findings.append({
                    "type": "SIGNAL",
                    "claim": clean_claim,
                    "evidence_quote": f'"{chunk.strip()}"',
                    "confidence": 82,
                })
                found_types.add("SIGNAL")
                continue

        # If no specific patterns matched, provide a grounded candidate finding from the raw text
        if not findings and chunks:
            first_chunk = chunks[0]
            findings.append({
                "type": "PROBLEM",
                "claim": first_chunk[:120],
                "evidence_quote": f'"{first_chunk}"',
                "confidence": 75,
            })

        return findings
