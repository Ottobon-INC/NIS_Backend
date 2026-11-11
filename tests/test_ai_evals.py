import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.runnables import RunnableLambda

from app.services.evals import (
    EvalEngine,
    CitationEvaluator,
    IdentityEvaluator,
    GroundingEvaluator,
    FaithfulnessEvaluator,
    SolutionEvaluator,
)
from app.services.evals.faithfulness_evaluator import FaithfulnessJudgment


def test_citation_evaluator_valid_and_fabricated():
    evidence_map = {
        "E1": {"identity_match_status": "CONFIRMED", "authority_tier": "PRIMARY_OFFICIAL"},
        "[E1]": {"identity_match_status": "CONFIRMED", "authority_tier": "PRIMARY_OFFICIAL"},
        "E2": {"identity_match_status": "CONFIRMED", "authority_tier": "PRIMARY_OFFICIAL"},
        "[E2]": {"identity_match_status": "CONFIRMED", "authority_tier": "PRIMARY_OFFICIAL"},
    }

    # Case 1: Clean citations
    score_clean, details_clean = CitationEvaluator.evaluate(
        "The executive leads platform engineering [E1] and spoke at KubeCon [E2].",
        evidence_map=evidence_map
    )
    assert score_clean == 100.0
    assert details_clean["valid_citations"] == ["E1", "E2"]
    assert details_clean["fabricated_citations"] == []

    # Case 2: Fabricated key [E99]
    score_fab, details_fab = CitationEvaluator.evaluate(
        "Built systems [E1] and caused an outage [E99].",
        evidence_map=evidence_map
    )
    assert score_fab < 50.0
    assert details_fab["fabricated_citations"] == ["E99"]


def test_identity_evaluator_confirmed_vs_conflicted():
    snap_good = {
        "name": "Bhanu Prakash",
        "current_organization": "Ottobon Inc",
        "identity_confidence": 96.0,
        "identity_resolution_status": "CONFIRMED",
        "provenance_status": "VERIFIED CURRENT",
        "detected_conflicts": []
    }
    score_good, _ = IdentityEvaluator.evaluate(
        snap_good,
        contact_name="Bhanu Prakash",
        contact_company="Ottobon"
    )
    assert score_good >= 92.0

    snap_bad = {
        "name": "John Smith",
        "current_organization": "Unrelated Corp",
        "identity_confidence": 42.0,
        "identity_resolution_status": "AMBIGUOUS",
        "provenance_status": "UNVERIFIED",
        "detected_conflicts": ["Employer mismatch A vs B", "Role mismatch"]
    }
    score_bad, details_bad = IdentityEvaluator.evaluate(
        snap_bad,
        contact_name="Bhanu Prakash",
        contact_company="Ottobon"
    )
    assert score_bad < 40.0
    assert len(details_bad["issues"]) >= 2


def test_grounding_evaluator_epistemic_integrity():
    # Direct verified problem
    snap_grounded = {
        "problem_epistemic_status": "EVIDENCE_GROUNDED",
        "problem_evidence_references": ["[E1]"],
        "structured_problem_references": [{"citation_key": "[E1]", "supports_directly": True, "is_stale": False}],
        "broad_business_problem": "API latency bottlenecks",
        "smallest_solvable_problem": "Latency profiling pilot",
    }
    score_g, _ = GroundingEvaluator.evaluate(snap_grounded)
    assert score_g >= 95.0

    # Claimed EVIDENCE_GROUNDED with zero references -> Fail!
    snap_fake_grounded = {
        "problem_epistemic_status": "EVIDENCE_GROUNDED",
        "problem_evidence_references": [],
        "structured_problem_references": [],
        "broad_business_problem": "Fabricated outage",
    }
    score_fg, details_fg = GroundingEvaluator.evaluate(snap_fake_grounded)
    assert score_fg <= 45.0
    assert len(details_fg["issues"]) >= 1

    # Negative control: NO_OBSERVED_PROBLEM -> high epistemic score!
    snap_no_prob = {
        "problem_epistemic_status": "NO_OBSERVED_PROBLEM",
        "broad_business_problem": None,
        "smallest_solvable_problem": None,
    }
    score_np, _ = GroundingEvaluator.evaluate(snap_no_prob)
    assert score_np >= 95.0


def test_solution_evaluator_safeguard_enforcement():
    # Unverified identity MUST suppress commercial pricing
    snap_leaked = {
        "provenance_status": "UNVERIFIED",
        "pipeline_stage": "UNCERTAIN_IDENTITY",
        "cost_pricing_estimate": "$15,000 fixed sprint",
        "estimated_effort_hours": "120 hours",
    }
    score_leaked, details_leaked = SolutionEvaluator.evaluate(snap_leaked)
    assert score_leaked < 50.0
    assert details_leaked["safeguard_enforced"] is False

    snap_safe = {
        "provenance_status": "UNVERIFIED",
        "pipeline_stage": "UNCERTAIN_IDENTITY",
        "cost_pricing_estimate": "SUPPRESSED: Identity confidence below 70%",
        "estimated_effort_hours": "SUPPRESSED: Pending identity confirmation",
    }
    score_safe, details_safe = SolutionEvaluator.evaluate(snap_safe)
    assert score_safe >= 95.0
    assert details_safe["safeguard_enforced"] is True


@pytest.mark.asyncio
async def test_faithfulness_evaluator_llm_judge_and_fallback():
    snapshot = {
        "name": "Alice Executive",
        "current_role": "VP Engineering",
        "current_organization": "Acme Cloud",
        "who_they_are": "Alice Executive is VP Engineering at Acme Cloud.",
        "career_history": ["VP Engineering at Acme Cloud"],
        "full_markdown_report": "Alice leads cloud engineering at Acme Cloud [E1]."
    }
    sources = {
        "E1": {
            "source_id": "linkedin",
            "title": "Alice Executive - Acme Cloud",
            "raw_text": "Alice Executive serves as VP Engineering at Acme Cloud leading distributed teams."
        }
    }

    # Test deterministic fallback
    fb_score, fb_details = await FaithfulnessEvaluator.evaluate(
        snapshot,
        sources_registry=sources,
        citation_score=100.0,
        enable_llm_judge=False
    )
    assert fb_score >= 90.0
    assert fb_details["evaluation_mode"] == "DETERMINISTIC_FALLBACK"

    # Test mocked gpt-4o-mini structured judge
    mock_judgment = FaithfulnessJudgment(
        total_claims_checked=2,
        verified_claims=["VP Engineering at Acme Cloud", "Leads distributed engineering teams"],
        unsupported_or_hallucinated_claims=[],
        faithfulness_score=98.0,
        reasoning="All core claims strictly entailed by source E1."
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda _: mock_judgment)

    with patch("app.services.evals.faithfulness_evaluator.ChatOpenAI", return_value=mock_llm), \
         patch("app.services.evals.faithfulness_evaluator.settings.OPENAI_API_KEY", "test-key"):
        llm_score, llm_details = await FaithfulnessEvaluator.evaluate(
            snapshot,
            sources_registry=sources,
            citation_score=100.0,
            enable_llm_judge=True
        )
        assert llm_score == 98.0
        assert "LLM_JUDGE" in llm_details["evaluation_mode"]
        assert llm_details["hallucinated_claims_count"] == 0


@pytest.mark.asyncio
async def test_eval_engine_composite_score_and_badges():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    snapshot = {
        "name": "Jane Founder",
        "current_role": "CTO",
        "current_organization": "DataScale AI",
        "provenance_status": "VERIFIED CURRENT",
        "identity_confidence": 96.0,
        "identity_resolution_status": "CONFIRMED",
        "problem_epistemic_status": "EVIDENCE_GROUNDED",
        "broad_business_problem": "Data pipeline ingestion bottleneck",
        "smallest_solvable_problem": "4-week Kafka partitioning audit",
        "ottobon_capability_match": "AI Applications & Data Engineering",
        "delivery_risk_level": "LOW",
        "estimated_effort_hours": "120-160 hours",
        "cost_pricing_estimate": "$12,000 pilot engagement",
        "problem_evidence_references": ["[E1]"],
        "structured_problem_references": [{"citation_key": "[E1]", "supports_directly": True, "is_stale": False}],
        "evidence_map": {
            "E1": {"identity_match_status": "CONFIRMED", "authority_tier": "PRIMARY_OFFICIAL", "claim": "CTO at DataScale AI noted ingestion bottleneck", "excerpt": "ingestion bottleneck in data pipeline"}
        },
        "sources_used": [
            {"source_id": "company_blog", "status": "SUCCESS", "identity_match_status": "CONFIRMED", "identity_match_confidence": 96.0}
        ],
        "full_markdown_report": "Jane Founder is CTO at DataScale AI facing a data pipeline ingestion bottleneck [E1]."
    }

    res = await EvalEngine.evaluate_dossier(
        db=mock_db,
        contact_id="c-123",
        research_run_id="run-123",
        snapshot_dict=snapshot,
        contact_name="Jane Founder",
        contact_company="DataScale AI",
        enable_llm_judge=False,
        persist=True
    )

    assert res.overall_accuracy_score >= 95.0
    assert res.badge.color == "green"
    assert res.badge.label == "Grounded"
    assert len(res.dimensions) == 6
    assert mock_db.add.called

