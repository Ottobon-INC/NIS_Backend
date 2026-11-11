import logging
import re
from typing import Dict, Any, Tuple, List, Optional
from pydantic import BaseModel, Field, SecretStr
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings

logger = logging.getLogger("networkos")


class FaithfulnessJudgment(BaseModel):
    total_claims_checked: int = Field(description="Total distinct factual claims extracted from the generated dossier")
    verified_claims: List[str] = Field(default_factory=list, description="Claims directly entailed by the retrieved source text")
    unsupported_or_hallucinated_claims: List[str] = Field(default_factory=list, description="Claims contradicted or completely invented without basis in sources")
    faithfulness_score: float = Field(description="Overall faithfulness percentage from 0.0 to 100.0")
    reasoning: str = Field(description="Concise audit explanation of entailment vs hallucinations")


JUDGE_SYSTEM_PROMPT = """You are an objective Epistemic NLI (Natural Language Inference) Auditor for NetworkOS.
Your task is to audit an AI-generated executive dossier against the raw retrieved evidence sources.

STRICT RULES:
1. Extract the core factual assertions from the GENERATED DOSSIER (role, company, career history, achievements, operational problem).
2. Check whether each factual assertion is supported by or reasonably inferred from the RETRIEVED EVIDENCE SOURCES.
3. Explicitly distinguish between:
   - Supported/Entailed claims
   - Reasonably labeled inferences (e.g., clearly framed commercial hypotheses)
   - Hallucinations (invented job titles, fabricated dates, fake client metrics, or unsupported operational crises stated as hard facts).
4. Compute an objective `faithfulness_score` (0.0 to 100.0):
   - 95-100%: Zero hallucinations; all core facts are grounded.
   - 80-94%: Minor stylistic extrapolations, core facts solid.
   - <80%: Contains ungrounded factual claims or fabricated specifics."""


class FaithfulnessEvaluator:
    """
    Evaluates synthesis faithfulness (hallucination-free rate) using gpt-4o-mini
    as an NLI judge against retrieved evidence sources, with deterministic fallback.
    """

    @classmethod
    def _build_evidence_corpus(
        cls,
        snapshot_dict: Dict[str, Any],
        sources_registry: Optional[Dict[str, Any]] = None
    ) -> str:
        chunks: List[str] = []
        if sources_registry:
            for key, rec in list(sources_registry.items())[:15]:
                raw_txt = getattr(rec, "raw_text", None) or (rec.get("raw_text") if isinstance(rec, dict) else "")
                title = getattr(rec, "title", None) or (rec.get("title") if isinstance(rec, dict) else "")
                if raw_txt or title:
                    chunks.append(f"[{key}] {title}: {str(raw_txt)[:800]}")

        ev_map = snapshot_dict.get("evidence_map") or {}
        if not chunks and ev_map:
            for key, item in list(ev_map.items())[:15]:
                claim = item.get("claim", "") if isinstance(item, dict) else ""
                excerpt = item.get("excerpt", "") if isinstance(item, dict) else ""
                chunks.append(f"{key} {claim} | {excerpt[:600]}")

        return "\n\n".join(chunks)[:12000]

    @classmethod
    def _build_dossier_summary(cls, snapshot_dict: Dict[str, Any]) -> str:
        parts = [
            f"Name: {snapshot_dict.get('name', 'N/A')}",
            f"Current Role: {snapshot_dict.get('current_role', 'N/A')} at {snapshot_dict.get('current_organization', 'N/A')}",
            f"Who They Are: {snapshot_dict.get('who_they_are', '')}",
            f"Problem Epistemic Status: {snapshot_dict.get('problem_epistemic_status', '')}",
            f"Broad Problem: {snapshot_dict.get('broad_business_problem', 'None')}",
            f"Career History: {', '.join(snapshot_dict.get('career_history', [])[:8])}",
            f"Notable Projects: {', '.join(snapshot_dict.get('notable_projects', [])[:5])}",
            f"Report Excerpt:\n{str(snapshot_dict.get('full_markdown_report', ''))[:4000]}"
        ]
        return "\n".join(parts)

    @classmethod
    def _deterministic_fallback(
        cls,
        snapshot_dict: Dict[str, Any],
        corpus_text: str,
        citation_score: float,
        reason: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Deterministic token-anchor overlap evaluation when LLM judge is unavailable or disabled.
        """
        corpus_lower = corpus_text.lower()
        # Expand common executive abbreviations in corpus check
        abbrev_map = {
            "chief executive officer": ["ceo"],
            "chief technology officer": ["cto"],
            "chief operating officer": ["coo"],
            "chief financial officer": ["cfo"],
            "chief information officer": ["cio"],
            "vice president": ["vp"],
        }
        claims: List[str] = []
        if snapshot_dict.get("current_organization"):
            claims.append(str(snapshot_dict["current_organization"]))
        if snapshot_dict.get("current_role"):
            claims.append(str(snapshot_dict["current_role"]))
        for ch in (snapshot_dict.get("career_history") or [])[:5]:
            claims.append(str(ch))
        prob_status = str(snapshot_dict.get("problem_epistemic_status", "")).upper()
        if hasattr(snapshot_dict.get("problem_epistemic_status"), "value"):
            prob_status = snapshot_dict["problem_epistemic_status"].value.upper()
        if snapshot_dict.get("broad_business_problem") and prob_status == "EVIDENCE_GROUNDED":
            claims.append(str(snapshot_dict["broad_business_problem"]))

        verified: List[str] = []
        unverified: List[str] = []

        for claim in claims:
            claim_low = claim.lower()
            matched_synonym = False
            for full_phrase, abbrevs in abbrev_map.items():
                if full_phrase in claim_low and any(re.search(rf'\b{a}\b', corpus_lower) for a in abbrevs):
                    matched_synonym = True
                    break
                if any(re.search(rf'\b{a}\b', claim_low) for a in abbrevs) and full_phrase in corpus_lower:
                    matched_synonym = True
                    break
            if matched_synonym:
                verified.append(claim)
                continue

            tokens = [t for t in re.findall(r'[a-zA-Z0-9]{4,}', claim_low) if t not in {"with", "from", "that", "this", "have", "lead", "role"}]
            if not tokens:
                verified.append(claim)
                continue
            hits = sum(1 for t in tokens if t in corpus_lower)
            if hits / len(tokens) >= 0.4 or not corpus_lower:
                verified.append(claim)
            else:
                unverified.append(claim)

        total = len(claims)
        if total == 0:
            score = citation_score
        else:
            entailment_ratio = (len(verified) / total) * 100.0
            score = (0.65 * entailment_ratio) + (0.35 * citation_score)

        score = round(max(0.0, min(100.0, score)), 1)
        return score, {
            "faithfulness_score_pct": score,
            "total_claims_checked": total,
            "verified_claims_count": len(verified),
            "hallucinated_claims_count": len(unverified),
            "verified_claims": verified,
            "hallucinations": unverified,
            "evaluation_mode": "DETERMINISTIC_FALLBACK",
            "reasoning": reason
        }

    @classmethod
    async def evaluate(
        cls,
        snapshot_dict: Dict[str, Any],
        sources_registry: Optional[Dict[str, Any]] = None,
        citation_score: float = 100.0,
        enable_llm_judge: bool = True
    ) -> Tuple[float, Dict[str, Any]]:
        corpus_text = cls._build_evidence_corpus(snapshot_dict, sources_registry)
        dossier_text = cls._build_dossier_summary(snapshot_dict)

        if not corpus_text.strip():
            return cls._deterministic_fallback(
                snapshot_dict,
                corpus_text,
                citation_score,
                "Insufficient retrieved source text for LLM NLI verification"
            )

        if not enable_llm_judge or not settings.OPENAI_API_KEY:
            return cls._deterministic_fallback(
                snapshot_dict,
                corpus_text,
                citation_score,
                "LLM judge disabled or OpenAI API key unavailable"
            )

        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL,
                temperature=0.0,
                api_key=SecretStr(settings.OPENAI_API_KEY)
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", JUDGE_SYSTEM_PROMPT),
                ("user", (
                    "<RETRIEVED_EVIDENCE_SOURCES>\n{corpus}\n</RETRIEVED_EVIDENCE_SOURCES>\n\n"
                    "<GENERATED_DOSSIER>\n{dossier}\n</GENERATED_DOSSIER>\n\n"
                    "Evaluate faithfulness and list any unsupported claims."
                ))
            ])
            chain = prompt | llm.with_structured_output(FaithfulnessJudgment, method="function_calling")
            res = await chain.ainvoke({"corpus": corpus_text, "dossier": dossier_text})

            if isinstance(res, BaseModel):
                data = res.model_dump()
            elif isinstance(res, dict):
                data = res
            else:
                data = dict(res)

            score = round(max(0.0, min(100.0, float(data.get("faithfulness_score", 85.0)))), 1)
            verified_claims = data.get("verified_claims") or []
            hallucinations = data.get("unsupported_or_hallucinated_claims") or []
            total_checked = int(data.get("total_claims_checked") or (len(verified_claims) + len(hallucinations)))

            return score, {
                "faithfulness_score_pct": score,
                "total_claims_checked": total_checked,
                "verified_claims_count": len(verified_claims),
                "hallucinated_claims_count": len(hallucinations),
                "verified_claims": verified_claims,
                "hallucinations": hallucinations,
                "evaluation_mode": f"LLM_JUDGE ({settings.OPENAI_MODEL})",
                "reasoning": data.get("reasoning", "")
            }
        except Exception as e:
            logger.warning(f"FaithfulnessEvaluator LLM judge failed ({type(e).__name__}: {e}). Using deterministic fallback.")
            return cls._deterministic_fallback(
                snapshot_dict,
                corpus_text,
                citation_score,
                f"LLM judge exception fallback: {type(e).__name__}"
            )
