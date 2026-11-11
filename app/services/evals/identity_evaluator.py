import re
from typing import Dict, Any, Tuple, List, Optional

class IdentityEvaluator:
    """
    Evaluates candidate identity resolution accuracy, anchor concordance,
    and person-organization binding integrity.
    """

    @classmethod
    def evaluate(
        cls,
        snapshot_dict: Dict[str, Any],
        sources_registry: Optional[Dict[str, Any]] = None,
        contact_name: Optional[str] = None,
        contact_company: Optional[str] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculates identity accuracy score (0.0 - 100.0) and generates an audit breakdown.
        """
        snapshot = snapshot_dict or {}
        issues: List[str] = []

        # 1. Base identity confidence from resolver
        raw_conf = float(snapshot.get("identity_confidence", 0.0) or 0.0)
        match_status = str(snapshot.get("identity_resolution_status", "PROBABLE")).upper()

        # 2. Check Name concordance
        name_in_snap = (snapshot.get("name") or "").strip().lower()
        target_name = (contact_name or name_in_snap or "").strip().lower()
        name_score = 100.0

        if target_name and name_in_snap:
            target_tokens = set(re.findall(r'\w+', target_name))
            snap_tokens = set(re.findall(r'\w+', name_in_snap))
            if target_tokens and snap_tokens:
                overlap = len(target_tokens & snap_tokens) / max(len(target_tokens), len(snap_tokens))
                name_score = round(overlap * 100.0, 1)
                if name_score < 70.0:
                    issues.append(f"Name divergence detected: '{name_in_snap}' vs expected '{target_name}'")

        # 3. Check Organization / Company concordance
        org_in_snap = (snapshot.get("current_organization") or "").strip().lower()
        target_company = (contact_company or org_in_snap or "").strip().lower()
        org_score = 100.0

        if target_company and org_in_snap:
            # Normalize common suffixes
            def _clean_org(org_str: str) -> str:
                return re.sub(r'\b(inc|corp|corporation|llc|ltd|technologies|solutions|technologies|systems)\b', '', org_str).strip()

            c_target = _clean_org(target_company)
            c_snap = _clean_org(org_in_snap)
            if c_target and c_snap:
                if c_target in c_snap or c_snap in c_target:
                    org_score = 100.0
                else:
                    t_toks = set(re.findall(r'\w+', c_target))
                    s_toks = set(re.findall(r'\w+', c_snap))
                    if t_toks and s_toks:
                        overlap = len(t_toks & s_toks) / max(len(t_toks), len(s_toks))
                        org_score = round(overlap * 100.0, 1)
                    else:
                        org_score = 50.0

            if org_score < 70.0:
                issues.append(f"Organization divergence detected: '{org_in_snap}' vs expected '{target_company}'")

        # 4. Check Conflict penalties
        conflicts = snapshot.get("detected_conflicts") or []
        conflict_penalty = min(35.0, len(conflicts) * 12.0)
        if conflicts:
            issues.append(f"{len(conflicts)} cross-source career/organization conflict(s) detected")

        # 5. Provenance status adjustment
        provenance = str(snapshot.get("provenance_status", "VERIFIED CURRENT")).upper()
        provenance_mult = 1.0
        if provenance == "UNVERIFIED":
            provenance_mult = 0.6
            issues.append("Provenance marked UNVERIFIED pending manual identity audit")
        elif provenance == "LAST KNOWN":
            provenance_mult = 0.85

        # 6. Synthesize composite identity score
        # Weighting: 40% resolver confidence, 30% name matching, 30% org matching
        base_score = (0.40 * raw_conf) + (0.30 * name_score) + (0.30 * org_score)
        penalized_score = max(0.0, (base_score - conflict_penalty) * provenance_mult)

        # Status floor/ceiling constraints
        if match_status == "CONFIRMED":
            final_score = max(85.0, min(100.0, penalized_score))
        elif match_status == "AMBIGUOUS":
            final_score = min(60.0, penalized_score)
        elif match_status == "UNMATCHED":
            final_score = min(30.0, penalized_score)
        else: # PROBABLE
            final_score = min(92.0, penalized_score)

        final_score = round(final_score, 1)

        details = {
            "identity_accuracy_pct": final_score,
            "resolution_status": match_status,
            "raw_resolver_confidence": raw_conf,
            "name_score": name_score,
            "organization_score": org_score,
            "provenance_status": provenance,
            "conflict_count": len(conflicts),
            "issues": issues
        }

        return final_score, details

