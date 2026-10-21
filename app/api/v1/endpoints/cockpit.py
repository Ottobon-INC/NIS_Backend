from fastapi import APIRouter, Depends
from typing import List
from app.api.dependencies import get_current_user

router = APIRouter()

@router.get("/queue")
async def get_founder_decision_queue(
    user: dict = Depends(get_current_user),
):
    """
    Founder Decision Queue:
    Centralized inbox answering 'WHAT NEEDS MY ATTENTION?'
    Aggregates candidate validations, match approvals, and intro reviews.
    """
    return {
        "queue": [
            {
                "id": "dec-01",
                "type": "OPPORTUNITY_VALIDATION",
                "priority": "HIGH",
                "title": "Validate Detected Opportunity",
                "subtitle": "David Chen · Apex Financial Group",
                "reason": "AI inferred high-urgency compliance need with $100k+ budget signal.",
                "actionUrl": "/opportunities/opp-fintech-fraud-02",
                "createdAt": "2026-03-22T08:30:00Z"
            },
            {
                "id": "dec-02",
                "type": "INTRODUCTION_REVIEW",
                "priority": "HIGH",
                "title": "Approve Outbound Introduction Draft",
                "subtitle": "Rahul Dhamdhere · Global Logistics Corp",
                "reason": "Calibrated warm email intro drafted via Bhanu connection path.",
                "actionUrl": "/messages/draft-01/review",
                "createdAt": "2026-03-22T09:00:00Z"
            },
            {
                "id": "dec-03",
                "type": "NETWORK_MATCH_APPROVAL",
                "priority": "MEDIUM",
                "title": "Review Candidate Network Route",
                "subtitle": "Meridian Freight Solutions via Priya Sharma",
                "reason": "Single-hop connection detected with 4/5 relationship strength.",
                "actionUrl": "/network/matches/match-03",
                "createdAt": "2026-03-22T07:15:00Z"
            }
        ]
    }


@router.get("/stats")
async def get_cockpit_stats(
    user: dict = Depends(get_current_user),
):
    """Returns top-level operational health and throughput counts."""
    return {
        "pendingDecisions": 3,
        "activeOpportunities": 3,
        "networkNodes": 52,
        "validatedNeeds": 1,
        "introductionsSent": 4
    }
