import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from app.services.evals import EvalEngine


async def run_benchmark_suite(dataset_path: Path, output_path: Path, use_llm_judge: bool = False) -> int:
    if not dataset_path.exists():
        print(f"ERROR: Golden dataset not found at {dataset_path}")
        return 1

    with dataset_path.open("r", encoding="utf-8") as f:
        cases: List[Dict[str, Any]] = json.load(f)

    results: List[Dict[str, Any]] = []
    passed_assertions = 0
    total_latency = 0.0

    for case in cases:
        t0 = time.perf_counter()
        res = await EvalEngine.evaluate_dossier(
            db=None,
            contact_id=None,
            research_run_id=None,
            snapshot_dict=case["snapshot"],
            contact_name=case.get("contact_name"),
            contact_company=case.get("contact_company"),
            enable_llm_judge=use_llm_judge,
            persist=False
        )
        elapsed = time.perf_counter() - t0
        total_latency += elapsed

        passed = True
        failure_reasons: List[str] = []

        if "min_expected_accuracy" in case and res.overall_accuracy_score < case["min_expected_accuracy"]:
            passed = False
            failure_reasons.append(
                f"Expected >= {case['min_expected_accuracy']}%, got {res.overall_accuracy_score}%"
            )
        if "max_expected_accuracy" in case and res.overall_accuracy_score > case["max_expected_accuracy"]:
            passed = False
            failure_reasons.append(
                f"Expected <= {case['max_expected_accuracy']}%, got {res.overall_accuracy_score}%"
            )
        if "expected_badge_color" in case and res.badge.color != case["expected_badge_color"]:
            passed = False
            failure_reasons.append(
                f"Expected badge '{case['expected_badge_color']}', got '{res.badge.color}'"
            )

        if passed:
            passed_assertions += 1

        results.append({
            "case_id": case["case_id"],
            "category": case["category"],
            "passed": passed,
            "failure_reasons": failure_reasons,
            "latency_sec": round(elapsed, 4),
            "overall_accuracy_score": res.overall_accuracy_score,
            "identity_accuracy_score": res.identity_accuracy_score,
            "citation_validity_score": res.citation_validity_score,
            "grounding_score": res.grounding_score,
            "faithfulness_score": res.faithfulness_score,
            "solution_alignment_score": res.solution_alignment_score,
            "badge": res.badge.model_dump()
        })

    n = len(results) or 1
    avg_overall = round(sum(r["overall_accuracy_score"] for r in results) / n, 1)
    avg_cite = round(sum(r["citation_validity_score"] for r in results) / n, 1)
    avg_id = round(sum(r["identity_accuracy_score"] for r in results) / n, 1)
    avg_ground = round(sum(r["grounding_score"] for r in results) / n, 1)
    avg_faith = round(sum(r["faithfulness_score"] for r in results) / n, 1)
    avg_sol = round(sum(r["solution_alignment_score"] for r in results) / n, 1)

    report = {
        "summary": {
            "total_cases": len(results),
            "passed_assertions": passed_assertions,
            "assertion_pass_rate": round((passed_assertions / n) * 100.0, 1),
            "average_overall_accuracy": avg_overall,
            "average_identity_accuracy": avg_id,
            "average_citation_validity": avg_cite,
            "average_grounding_score": avg_ground,
            "average_faithfulness_score": avg_faith,
            "average_solution_alignment": avg_sol,
            "average_latency_sec": round(total_latency / n, 4),
            "llm_judge_enabled": use_llm_judge,
        },
        "cases": results
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 78)
    print("NETWORKOS EVAL SUMMARY".center(78))
    print("=" * 78)
    print(f"Total Test Cases Evaluated:       {len(results)}")
    print(f"Benchmark Assertions Passed:      {passed_assertions}/{len(results)} ({report['summary']['assertion_pass_rate']}%)")
    print(f"Overall Composite Accuracy Avg:   {avg_overall}%")
    print(f"Identity Resolution Avg:          {avg_id}%")
    print(f"Citation Validity Avg:            {avg_cite}%")
    print(f"Problem Grounding Avg:            {avg_ground}%")
    print(f"Synthesis Faithfulness Avg:       {avg_faith}%")
    print(f"Solution Alignment Avg:           {avg_sol}%")
    print(f"Average Latency per Eval:         {report['summary']['average_latency_sec']}s")
    print("=" * 78)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f" [{mark}] {r['case_id']:<38} | Score: {r['overall_accuracy_score']:>5.1f}% | Badge: {r['badge']['color']:<5} ({r['badge']['label']})")
        if r["failure_reasons"]:
            for fr in r["failure_reasons"]:
                print(f"        -> {fr}")
    print("=" * 78)
    print(f"Saved detailed JSON report to: {output_path}\n")

    return 0 if passed_assertions == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NetworkOS AI Evaluation Golden Benchmark Suite")
    parser.add_argument("--dataset", default="evals/golden_dataset.json", help="Path to golden dataset JSON")
    parser.add_argument("--output", default="evals/reports/latest.json", help="Output report JSON path")
    parser.add_argument("--llm", action="store_true", help="Enable gpt-4o-mini LLM-as-a-Judge faithfulness scoring")
    args = parser.parse_args()

    exit_code = asyncio.run(run_benchmark_suite(Path(args.dataset), Path(args.output), args.llm))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

