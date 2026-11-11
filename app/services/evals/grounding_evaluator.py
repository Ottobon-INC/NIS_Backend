from typing import Dict, Any, Tuple, List, Optional

class GroundingEvaluator:
    """
    Evaluates operational problem grounding, factual corroboration, and adherence
    to epistemic truth tiers (EVIDENCE_GROUNDED vs SUPPORTED_INFERENCE vs NO_OBSERVED_PROBLEM).
    """

    @classmethod
    def evaluate(
        cls,
        snapshot_dict: Dict[str, Any],
        sources_registry: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, Dict[str, Any]]:
        snapshot = snapshot_dict or {}
        issues: List[str] = []

        raw_ep_status = snapshot.get("problem_epistemic_status")
        if raw_ep_status is not None and hasattr(raw_ep_status, "value"):
            epistemic_status = str(getattr(raw_ep_status, "value"))
        elif not raw_ep_status:
            epistemic_status = "NO_OBSERVED_PROBLEM"
        else:
            epistemic_status = str(raw_ep_status)
        epistemic_status = epistemic_status.upper()

        prob_refs = snapshot.get("problem_evidence_references") or []
        struct_refs = snapshot.get("structured_problem_references") or []
        broad_prob = snapshot.get("broad_business_problem")
        smallest_prob = snapshot.get("smallest_solvable_problem")

        # 1. Epistemic status verification
        if epistemic_status == "EVIDENCE_GROUNDED":
            if not prob_refs and not struct_refs:
                score = 40.0
                issues.append("Claimed EVIDENCE_GROUNDED but problem lacks all citation references")
            else:
                direct_supports = [
                    r for r in struct_refs 
                    if isinstance(r, dict) and r.get("supports_directly")
                ]
                stale_refs = [
                    r for r in struct_refs 
                    if isinstance(r, dict) and r.get("is_stale")
                ]

                if direct_supports:
                    score = 98.0
                else:
                    score = 80.0
                    issues.append("Problem marked EVIDENCE_GROUNDED but lacks direct verbatim deficit proof")

                if stale_refs:
                    score = max(50.0, score - (len(stale_refs) * 10.0))
                    issues.append(f"{len(stale_refs)} citation(s) are historical (>365 days old)")

        elif epistemic_status in ["SUPPORTED_INFERENCE", "INFERENCE"]:
            if broad_prob or smallest_prob:
                score = 88.0
            else:
                score = 75.0
                issues.append("SUPPORTED_INFERENCE declared without specific problem hypothesis")

        elif epistemic_status == "NO_OBSERVED_PROBLEM":
            # Reward epistemic safety: no hallucinated fake problems
            if not broad_prob and not smallest_prob:
                score = 99.0
            else:
                score = 60.0
                issues.append("NO_OBSERVED_PROBLEM declared but problem strings were populated")

        elif epistemic_status in ["CONFLICTING_EVIDENCE", "INSUFFICIENT_EVIDENCE"]:
            score = 90.0  # System correctly admitted insufficient/conflicting data

        else:  # HYPOTHESIS_ONLY or others
            score = 72.0
            issues.append("Problem relies on ungrounded sales hypothesis")

        # 2. Check verified facts ratio
        verified_facts = snapshot.get("verified_facts") or []
        audit_issues = snapshot.get("audit_issues") or []
        if audit_issues:
            score = max(30.0, score - min(25.0, len(audit_issues) * 5.0))
            issues.append(f"{len(audit_issues)} research audit issue(s) recorded")

        score = round(max(0.0, min(100.0, score)), 1)

        details = {
            "grounding_score_pct": score,
            "problem_epistemic_status": epistemic_status,
            "citations_count": len(prob_refs),
            "structured_references_count": len(struct_refs),
            "verified_facts_count": len(verified_facts),
            "issues": issues
        }

        return score, details
