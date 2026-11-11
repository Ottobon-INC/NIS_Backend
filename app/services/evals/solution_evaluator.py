import re
from typing import Dict, Any, Tuple, List

class SolutionEvaluator:
    """
    Evaluates Ottobon product-to-problem solution alignment, commercial feasibility
    boundaries, and identity-gated suppression compliance.
    """

    VALID_CAPABILITY_KEYWORDS = [
        "development", "ai", "application", "marketing", "sales",
        "support", "cloud", "infrastructure", "data", "engineering",
        "automation", "integration", "analytics", "platform"
    ]

    @classmethod
    def evaluate(
        cls,
        snapshot_dict: Dict[str, Any]
    ) -> Tuple[float, Dict[str, Any]]:
        snapshot = snapshot_dict or {}
        issues: List[str] = []
        score = 95.0

        provenance = str(snapshot.get("provenance_status", "")).upper()
        pipeline_stage = str(snapshot.get("pipeline_stage", "")).upper()
        is_unverified = (provenance == "UNVERIFIED" or pipeline_stage == "UNCERTAIN_IDENTITY")

        cap_match = (snapshot.get("ottobon_capability_match") or "").strip()
        broad_prob = (snapshot.get("broad_business_problem") or "").strip()
        smallest_prob = (snapshot.get("smallest_solvable_problem") or "").strip()
        pricing = (snapshot.get("cost_pricing_estimate") or "").strip()
        effort = (snapshot.get("estimated_effort_hours") or "").strip()
        first_eng = (snapshot.get("proposed_first_engagement") or "").strip()
        risk_level = (snapshot.get("delivery_risk_level") or "MEDIUM").upper()

        # 1. Safeguard Compliance: Unverified identity MUST suppress commercial pricing
        if is_unverified:
            has_suppressed_pricing = "SUPPRESSED" in pricing.upper() or not pricing
            has_suppressed_effort = "SUPPRESSED" in effort.upper() or not effort
            if has_suppressed_pricing and has_suppressed_effort:
                score = 98.0
            else:
                score = 35.0
                issues.append("CRITICAL: Commercial pricing leaked on UNVERIFIED identity profile")
            return round(score, 1), {
                "solution_alignment_pct": round(score, 1),
                "capability_match": cap_match or "Suppressed",
                "risk_level": risk_level,
                "safeguard_enforced": has_suppressed_pricing and has_suppressed_effort,
                "issues": issues
            }

        # 2. Problem-to-Solution Coherence
        raw_ep_status = snapshot.get("problem_epistemic_status")
        epistemic_status = str(getattr(raw_ep_status, "value", raw_ep_status or "NO_OBSERVED_PROBLEM")).upper()

        if epistemic_status == "NO_OBSERVED_PROBLEM":
            # Should not aggressively force a sales pitch if no problem exists
            if not cap_match or "none" in cap_match.lower():
                score = 96.0
            else:
                score = 84.0
                issues.append("Capability matched despite NO_OBSERVED_PROBLEM status")
        else:
            # Verify valid capability alignment
            if not cap_match:
                score -= 15.0
                issues.append("Problem identified without matching Ottobon capability")
            elif not any(kw in cap_match.lower() for kw in cls.VALID_CAPABILITY_KEYWORDS):
                score -= 10.0
                issues.append(f"Capability '{cap_match}' falls outside standard Ottobon pillars")

            if not smallest_prob and not first_eng:
                score -= 15.0
                issues.append("Missing concrete smallest solvable problem or first sprint deliverable")

            # Check realistic hour bounds if provided
            if effort and any(c.isdigit() for c in effort):
                nums = [int(n) for n in re.findall(r'\d+', effort)]
                if nums and (max(nums) > 2000 or min(nums) < 10):
                    score -= 10.0
                    issues.append(f"Estimated effort '{effort}' outside standard pilot bounds (40-400 hrs)")

            # Check pricing sanity if provided
            if pricing and "$" not in pricing and "suppress" not in pricing.lower():
                score -= 5.0
                issues.append("Pricing estimate lacks quantitative financial framing")

        # 3. Delivery Risk Tagging check
        if not any(lvl in risk_level for lvl in ["LOW", "MEDIUM", "HIGH"]):
            score -= 5.0
            issues.append(f"Non-standard delivery risk classification: '{risk_level}'")

        score = round(max(0.0, min(100.0, score)), 1)

        return score, {
            "solution_alignment_pct": score,
            "capability_match": cap_match or "None Established",
            "risk_level": risk_level,
            "safeguard_enforced": True,
            "issues": issues
        }
