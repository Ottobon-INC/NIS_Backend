import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from app.db.session import get_db
from sqlalchemy import select
from app.models.identity import Contact
from app.models.evidence import SourceResult
from app.models.orchestration import ResearchRun
from app.services.conversation_intelligence import ConversationIntelligenceService
from app.services.problem_matcher import ProblemMatcherService
from app.services.semantic_product_matcher import SemanticProductMatcherService
from app.schemas.matching import (
    CompanyProfileAnalysis,
    CompanyMatchingResult,
    MatchingOutcome,
    SemanticProblemMatchRequest,
    SemanticProductMatchResponse
)

router = APIRouter()

class ProfileAnalysisRequest(BaseModel):
    text: str
    source_filename: Optional[str] = "custom_profile.txt"
    tables_data: Optional[List[List[List[str]]]] = None

class BatchAnalysisRequest(BaseModel):
    documents: List[ProfileAnalysisRequest]

def extract_docx_text(file_path: str) -> tuple[str, List[List[List[str]]]]:
    try:
        import docx
    except ImportError:
        raise HTTPException(status_code=500, detail="python-docx is not installed in the environment")

    doc = docx.Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():
            full_text.append(para.text)

    tables_data = []
    for table in doc.tables:
        t_data = []
        for row in table.rows:
            r_data = [cell.text.strip() for cell in row.cells]
            t_data.append(r_data)
        if t_data:
            tables_data.append(t_data)

    return "\n".join(full_text), tables_data

def extract_pdf_text(file_path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise HTTPException(status_code=500, detail="pypdf is not installed in the environment")

    reader = PdfReader(file_path)
    full_text = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            full_text.append(t)
    return "\n".join(full_text)

DUMMY_FILES = [
    r"c:\Users\poorv\OneDrive\Desktop\NetworkOS\TalentOps Business Overview.pdf",
    r"c:\Users\poorv\OneDrive\Desktop\NetworkOS\Business Overview Janmasethu U (1).docx",
    r"c:\Users\poorv\OneDrive\Desktop\NetworkOS\sBLOOM_Detailed_Business_Proposal_Overview.docx",
    r"c:\Users\poorv\OneDrive\Desktop\NetworkOS\ottobon_course_platform_business_overview.docx"
]

@router.post("/analyze-profile", response_model=CompanyMatchingResult)
async def analyze_profile(
    req: ProfileAnalysisRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Analyzes raw profile or conversation text, extracts structured business context & problems,
    and maps them to approved Ottobon offerings.
    """
    analysis = await ConversationIntelligenceService.analyze_document_text(
        text=req.text,
        source_filename=req.source_filename or "document.txt",
        tables_data=req.tables_data
    )
    result = await ProblemMatcherService.match_profile(analysis, db=db)
    return result

@router.get("/dummy-profiles", response_model=List[CompanyMatchingResult])
async def analyze_dummy_profiles(
    db: AsyncSession = Depends(get_db)
):
    """
    Executes the complete NetworkOS Intelligence & Matching pipeline on all 4 dummy
    company profile documents located in the workspace.
    """
    results: List[CompanyMatchingResult] = []

    for file_path in DUMMY_FILES:
        if not os.path.exists(file_path):
            continue

        filename = os.path.basename(file_path)
        tables_data = None
        if file_path.lower().endswith(".docx"):
            text, tables_data = extract_docx_text(file_path)
        elif file_path.lower().endswith(".pdf"):
            text = extract_pdf_text(file_path)
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        analysis = await ConversationIntelligenceService.analyze_document_text(
            text=text,
            source_filename=filename,
            tables_data=tables_data
        )
        res = await ProblemMatcherService.match_profile(analysis, db=db)
        results.append(res)

    return results

@router.post("/semantic-product-match", response_model=SemanticProductMatchResponse)
async def semantic_match_problem(req: SemanticProblemMatchRequest):
    """
    Semantically evaluates an explicit problem description against our product catalog.
    If none of our products are suitable, returns 'No matches found'.
    """
    return await SemanticProductMatcherService.match_connection_problem(
        problem_text=req.problem_text,
        connection_id=req.connection_id,
        connection_name=req.connection_name,
        connection_company=req.connection_company,
        connection_title=req.connection_title
    )

@router.get("/connections/{contact_id}/semantic-product-match", response_model=SemanticProductMatchResponse)
@router.post("/connections/{contact_id}/semantic-product-match", response_model=SemanticProductMatchResponse)
async def semantic_match_connection(
    contact_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Understands the connection's problem from their 360 intelligence dossier,
    and semantically maps it to our products. If no products are suitable,
    explicitly returns 'No matches found'.
    """
    # 1. Resolve contact_id if a research_run_id was passed
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == contact_id))).scalars().first()
    resolved_contact_id = run.contact_id if run else contact_id

    contact = (await db.execute(select(Contact).where(Contact.id == resolved_contact_id))).scalars().first()

    srs = (await db.execute(
        select(SourceResult)
        .where(SourceResult.source_id == 'evidence_engine')
        .order_by(SourceResult.retrieved_at.desc())
    )).scalars().all()

    snapshot = {}
    for sr in srs:
        is_match = False
        if sr.metadata_ and sr.metadata_.get("contact_id") == resolved_contact_id:
            is_match = True
        elif sr.entity_searched and contact and contact.full_name and sr.entity_searched.strip().lower() == contact.full_name.strip().lower():
            is_match = True
        if is_match and sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
            snapshot = sr.extracted_data['executive_snapshot']
            break

    # Check problem epistemic status
    raw_status = snapshot.get("problem_epistemic_status")
    epistemic_status = raw_status.value if hasattr(raw_status, "value") else str(raw_status) if raw_status else None
    
    # Grounded statuses: Only EVIDENCE_GROUNDED permits definitive automated evidence-backed product matching.
    # SUPPORTED_INFERENCE represents a plausible deduction that requires human/discovery validation before product recommendation.
    is_evidence_grounded = (epistemic_status == "EVIDENCE_GROUNDED")
    is_supported_inference = (epistemic_status == "SUPPORTED_INFERENCE")

    # Extract the connection's identified problem
    prob_text = ""
    smallest = (snapshot.get("smallest_solvable_problem") or "").strip()
    broad = (snapshot.get("broad_business_problem") or "").strip()
    current_role_str = snapshot.get("current_role") or (contact.current_title if contact else "")
    title_lower = current_role_str.lower() if current_role_str else ""
    company_str = snapshot.get("current_organization") or (contact.current_company if contact else "")
    company_lower = company_str.lower() if company_str else ""
    is_doctor = any(w in title_lower for w in ["doctor", "physician", "gastroenterologist", "medical", "clinic", "surgeon", "hospital"])
    is_coach = any(w in title_lower or w in company_lower for w in ["coach", "coaching", "certification", "training", "mentor", "trainer", "academy", "gccp"])

    is_broad_verified = bool(broad) and not SemanticProductMatcherService._is_unverified_problem(broad)
    is_smallest_verified = bool(smallest) and not SemanticProductMatcherService._is_unverified_problem(smallest)

    # Epistemic safety boundary:
    # 1. EVIDENCE_GROUNDED: Fully verified direct evidence permits automated product matching.
    # 2. SUPPORTED_INFERENCE: Plausible deduction requiring explicit discovery validation before any product fit.
    # 3. HYPOTHESIS_ONLY, NO_OBSERVED_PROBLEM, CONFLICTING_EVIDENCE, INSUFFICIENT_EVIDENCE, or legacy: strictly unverified.
    if is_evidence_grounded and (is_broad_verified or is_smallest_verified):
        prob_text = broad if is_broad_verified else smallest
        if is_doctor and "branding" not in prob_text.lower() and "content" not in prob_text.lower():
            prob_text = f"{prob_text.rstrip('.')}; doctor personal branding and medical content strategy."
        elif is_coach and "platform" not in prob_text.lower() and "course" not in prob_text.lower():
            prob_text = f"{prob_text.rstrip('.')}; structured digital course delivery platform and certification assessment workflows for coaching cohorts."
    elif is_supported_inference and (is_broad_verified or is_smallest_verified):
        prob_text = broad if is_broad_verified else smallest
    else:
        # Strictly preserve unverified state: Never fabricate an operational problem when unverified
        if epistemic_status == "NO_OBSERVED_PROBLEM":
            prob_text = "No observed problem in available evidence."
        elif epistemic_status == "CONFLICTING_EVIDENCE":
            prob_text = "Conflicting evidence prevents reliable problem identification."
        elif epistemic_status == "INSUFFICIENT_EVIDENCE":
            prob_text = "Insufficient evidence to identify an operational problem."
        elif epistemic_status == "HYPOTHESIS_ONLY":
            prob_text = f"Unverified hypothesis only: {smallest or broad or 'Insufficient supporting evidence'}."
        else:
            prob_text = "No verified business problem identified."

    name = snapshot.get("name") or (contact.full_name if contact else "Connection")
    company = snapshot.get("current_organization") or (contact.current_company if contact else "")
    title = snapshot.get("current_role") or (contact.current_title if contact else "")

    return await SemanticProductMatcherService.match_connection_problem(
        problem_text=prob_text,
        connection_id=contact_id,
        connection_name=name,
        connection_company=company,
        connection_title=title,
        context={"industry": snapshot.get("domain_name") or (contact.current_company if contact else "")}
    )
