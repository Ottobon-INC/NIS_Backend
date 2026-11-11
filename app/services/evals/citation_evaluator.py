import re
from typing import Dict, List, Tuple, Any, Optional

class CitationEvaluator:
    """
    Deterministic evaluation of citation integrity within synthesized intelligence reports.
    Audits for phantom/fabricated keys, syntax malformations, and unverified/uncertain sources.
    """

    @classmethod
    def evaluate(
        cls,
        markdown_text: str,
        sources_registry: Optional[Dict[str, Any]] = None,
        evidence_map: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Returns (citation_validity_score, detailed_report).
        Score is 0.0 - 100.0.
        """
        text = markdown_text or ""
        sources = sources_registry or {}
        ev_map = evidence_map or {}

        found_keys = re.findall(r'\[(E\d+)\]', text)
        malformed = re.findall(r'\[(E[a-zA-Z]+|\bEV\d+|\bE\b)\]', text)

        unique_keys = list(dict.fromkeys(found_keys))
        total_found = len(unique_keys)

        valid_keys: List[str] = []
        fabricated_keys: List[str] = []
        uncertain_keys: List[str] = []

        # Collect authoritative citation keys
        available_keys: Dict[str, Any] = {}
        for k, v in ev_map.items():
            clean_k = k.strip("[]")
            if re.fullmatch(r'E\d+', clean_k):
                available_keys[clean_k] = v

        # Check explicit E-keys in sources_registry if provided
        has_explicit_e_keys = False
        for k, v in sources.items():
            clean_k = k.strip("[]")
            if re.fullmatch(r'E\d+', clean_k):
                has_explicit_e_keys = True
                if clean_k not in available_keys:
                    available_keys[clean_k] = v

        # Fallback: derive E1..En from distinct source records if no evidence_map keys exist
        if not available_keys and not has_explicit_e_keys and sources:
            distinct_records: List[Any] = []
            seen_ids = set()
            for rec in sources.values():
                rec_id = id(rec)
                if rec_id not in seen_ids:
                    seen_ids.add(rec_id)
                    distinct_records.append(rec)
            for idx, rec in enumerate(distinct_records, 1):
                available_keys[f"E{idx}"] = rec

        for k in unique_keys:
            if k in available_keys:
                rec = available_keys[k]
                auth_tier = getattr(rec, "authority_tier", None) or (rec.get("authority_tier") if isinstance(rec, dict) else None)
                id_match = getattr(rec, "identity_match_status", None) or (rec.get("identity_match_status") if isinstance(rec, dict) else None)
                if auth_tier == "UNVERIFIED_WEB" or id_match == "UNCERTAIN":
                    uncertain_keys.append(k)
                else:
                    valid_keys.append(k)
            else:
                fabricated_keys.append(k)

        # Calculate Accuracy Score
        if total_found == 0:
            # If report has substantial claims (>600 chars) without any citations, apply penalty
            score = 50.0 if len(text) > 600 else 100.0
        else:
            # Uncertain keys carry half weight; fabricated keys heavily penalize
            effective_valid = len(valid_keys) + (0.5 * len(uncertain_keys))
            valid_ratio = effective_valid / total_found
            fabrication_penalty = (len(fabricated_keys) / total_found) * 100.0
            malformed_penalty = min(20.0, len(malformed) * 5.0)
            score = max(0.0, (valid_ratio * 100.0) - (fabrication_penalty * 1.5) - malformed_penalty)

        if total_found == 0 and malformed:
            score = max(0.0, score - min(30.0, len(malformed) * 10.0))

        details = {
            "total_citations_found": total_found,
            "valid_citations": valid_keys,
            "fabricated_citations": fabricated_keys,
            "uncertain_citations": uncertain_keys,
            "malformed_citations": malformed,
            "citation_precision_pct": round(score, 1)
        }

        return round(score, 1), details
