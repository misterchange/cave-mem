"""
cave-mem Before/After Test Report Generator

Usage:
    python tests/run_report.py --phase baseline   # run before cave-mem is created
    python tests/run_report.py --phase cave-mem   # run after cave-mem is created
    python tests/run_report.py --phase both       # run both and compare (default)

Reports are saved to tests/reports/
"""

import argparse
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path

THIS_DIR    = Path(__file__).resolve().parent
REPORTS_DIR = THIS_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def run_suite(module_name: str) -> dict:
    """Run a test module and return structured results."""
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except Exception as exc:
        return {
            "module": module_name,
            "load_error": str(exc),
            "total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
            "details": [],
            "duration_s": 0,
        }

    buf = StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    t0 = time.perf_counter()
    result = runner.run(suite)
    duration = time.perf_counter() - t0

    details = []
    for test, tb in result.failures:
        details.append({"test": str(test), "status": "FAIL", "message": tb})
    for test, tb in result.errors:
        details.append({"test": str(test), "status": "ERROR", "message": tb})
    for test, reason in result.skipped:
        details.append({"test": str(test), "status": "SKIP", "reason": reason})

    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)

    return {
        "module":     module_name,
        "total":      result.testsRun,
        "passed":     passed,
        "failed":     len(result.failures),
        "errors":     len(result.errors),
        "skipped":    len(result.skipped),
        "details":    details,
        "duration_s": round(duration, 3),
        "raw_output": buf.getvalue(),
    }


def render_report(results: list[dict], phase: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 72,
        f"  cave-mem  |  {phase.upper()} PHASE REPORT  |  {now}",
        "=" * 72,
        "",
    ]

    for r in results:
        suite_name = r["module"].replace("tests.", "").replace("_", " ").title()
        status_icon = "PASS" if r["failed"] == 0 and r["errors"] == 0 else "FAIL"
        lines += [
            f"  [{status_icon}]  {suite_name}",
            f"     Total: {r['total']}  |  Passed: {r['passed']}  |  "
            f"Failed: {r['failed']}  |  Errors: {r['errors']}  |  Skipped: {r['skipped']}",
            f"     Duration: {r['duration_s']}s",
        ]
        if r.get("load_error"):
            lines.append(f"     LOAD ERROR: {r['load_error']}")
        for d in r["details"]:
            lines.append(f"     [{d['status']}] {d['test']}")
            if "message" in d:
                for ln in d["message"].strip().splitlines()[-4:]:
                    lines.append(f"        {ln}")
        lines.append("")

    total_tests  = sum(r["total"]  for r in results)
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] + r["errors"] for r in results)
    total_skip   = sum(r["skipped"] for r in results)
    overall = "ALL PASS" if total_failed == 0 else f"{total_failed} FAILING"

    lines += [
        "-" * 72,
        f"  OVERALL [{overall}]  "
        f"Tests: {total_tests}  Passed: {total_passed}  "
        f"Failed: {total_failed}  Skipped: {total_skip}",
        "=" * 72,
    ]
    return "\n".join(lines)


def render_comparison(before: list[dict], after: list[dict]) -> str:
    def _agg(results):
        return {
            "total":   sum(r["total"]   for r in results),
            "passed":  sum(r["passed"]  for r in results),
            "failed":  sum(r["failed"] + r["errors"] for r in results),
            "skipped": sum(r["skipped"] for r in results),
        }

    b = _agg(before)
    a = _agg(after)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    # Collect per-test changes by parsing raw_output
    def _parse_tests(results):
        tests = {}
        for r in results:
            for line in r.get("raw_output", "").splitlines():
                if " ... " in line:
                    name, _, verdict = line.rpartition(" ... ")
                    tests[name.strip()] = verdict.strip()
        return tests

    bt = _parse_tests(before)
    at = _parse_tests(after)
    all_tests = sorted(set(bt) | set(at))

    changed = []
    new_pass = []
    new_fail = []
    for t in all_tests:
        bv = bt.get(t, "MISSING")
        av = at.get(t, "MISSING")
        if bv != av:
            changed.append((t, bv, av))
            if av in ("ok", "OK"):
                new_pass.append(t)
            elif bv in ("ok", "OK"):
                new_fail.append(t)

    lines = [
        "=" * 72,
        f"  cave-mem  |  BEFORE vs AFTER COMPARISON  |  {now}",
        "=" * 72,
        "",
        "  SUMMARY",
        f"  {'Metric':<20}  {'Before':>8}  {'After':>8}  {'Delta':>8}",
        "  " + "-" * 46,
        f"  {'Tests run':<20}  {b['total']:>8}  {a['total']:>8}  "
        f"{a['total']-b['total']:>+8}",
        f"  {'Passed':<20}  {b['passed']:>8}  {a['passed']:>8}  "
        f"{a['passed']-b['passed']:>+8}",
        f"  {'Failed/Errors':<20}  {b['failed']:>8}  {a['failed']:>8}  "
        f"{a['failed']-b['failed']:>+8}",
        f"  {'Skipped':<20}  {b['skipped']:>8}  {a['skipped']:>8}  "
        f"{a['skipped']-b['skipped']:>+8}",
        "",
    ]

    if changed:
        lines += ["  STATUS CHANGES", "  " + "-" * 68]
        for t, bv, av in changed:
            arrow = "→"
            icon  = "+" if av in ("ok", "OK") else "-"
            lines.append(f"  [{icon}] {t}")
            lines.append(f"      Before: {bv}  {arrow}  After: {av}")
        lines.append("")

    if new_pass:
        lines += [f"  NEW PASSES ({len(new_pass)})"]
        for t in new_pass:
            lines.append(f"    [+] {t}")
        lines.append("")

    if new_fail:
        lines += [f"  NEW FAILURES ({len(new_fail)})"]
        for t in new_fail:
            lines.append(f"    [-] {t}")
        lines.append("")

    if not changed:
        lines += ["  No test status changes detected.", ""]

    lines += [
        "  INTERPRETATION",
        "  -----------------------------------------------------------------",
        "  baseline tests  — verify caveman & claude-mem are INDEPENDENT",
        "  cave-mem tests  — verify the COMBINED plugin works correctly",
        "  Expected result — baseline: all pass  |  cave-mem: all pass",
        "=" * 72,
    ]
    return "\n".join(lines)


def main():
    # Fix Windows console encoding for non-ASCII output
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # Add parent dir to sys.path so 'tests.test_*' imports work
    sys.path.insert(0, str(THIS_DIR.parent))

    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["baseline", "cave-mem", "both"],
                        default="both")
    args = parser.parse_args()

    before_results = []
    after_results  = []

    if args.phase in ("baseline", "both"):
        print("\nRunning BASELINE tests (before cave-mem)...")
        before_results = [run_suite("tests.test_baseline")]
        report_text = render_report(before_results, "baseline")
        print(report_text)
        out = REPORTS_DIR / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text(report_text)
        print(f"\nBaseline report saved → {out}")

    if args.phase in ("cave-mem", "both"):
        print("\nRunning CAVE-MEM tests (after cave-mem)...")
        after_results = [run_suite("tests.test_cave_mem")]
        report_text = render_report(after_results, "cave-mem")
        print(report_text)
        out = REPORTS_DIR / f"cave_mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text(report_text)
        print(f"\nCave-mem report saved → {out}")

    if args.phase == "both":
        comp = render_comparison(before_results, after_results)
        print("\n" + comp)
        out = REPORTS_DIR / f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text(comp)
        print(f"\nComparison report saved → {out}")


if __name__ == "__main__":
    main()
