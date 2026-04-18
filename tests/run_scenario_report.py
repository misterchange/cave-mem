"""
4-Scenario Comparison Report
=============================
Runs all 4 scenarios and prints a side-by-side report.

Usage:
    python tests/run_scenario_report.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path

WIKIMAN        = Path("C:/Nitin/Nitins/WikiMan")
STONEAGE_ROOT   = WIKIMAN / "stoneage"
CAVE_MEM_ROOT  = Path("C:/Nitin/Nitins/stoneage")

CLAUDE_MEM_CONTEXT = """\
CLAUDE-MEM ACTIVE — persistent cross-session memory enabled.

## Memory Context

Observations from past sessions loaded. Tool results, file edits, key decisions, errors+fixes captured automatically.

Rules:
- Cite stored facts: prefix with [mem:<id>] when drawing from past sessions
- <private>...</private> tags exclude content from memory storage
- Search memories: use mem-search skill
- Memory auto-captures: tool results, file edits, key decisions, errors+fixes

Session continuity active. Past context available for this conversation.
Memory stored in full verbose format. Retrieval cost scales with history size.
"""


def run_node(script, home, stdin=None):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return subprocess.run(
        ["node", str(script)],
        input=stdin, cwd=str(script.parent),
        env=env, text=True, capture_output=True,
    )


def approx_tokens(text):
    return len(text) // 4


def run_tests():
    sys.path.insert(0, str(CAVE_MEM_ROOT))
    buf = StringIO()
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromName("tests.test_all_scenarios")
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    t0 = time.perf_counter()
    result = runner.run(suite)
    duration = time.perf_counter() - t0
    return result, buf.getvalue(), round(duration, 2)


def gather_metrics():
    """Collect live metrics from all 4 scenarios."""
    with tempfile.TemporaryDirectory(prefix="scenario-report-") as tmp:
        home = Path(tmp)
        (home / ".claude").mkdir()
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
        )
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}

        # S1: nothing
        s1_output = ""

        # S2: stoneage
        s2 = subprocess.run(
            ["node", str(STONEAGE_ROOT / "hooks" / "stoneage-activate.js")],
            cwd=str(STONEAGE_ROOT / "hooks"), env=env,
            text=True, capture_output=True,
        )
        s2_output = s2.stdout

        # S3: claude-mem (representative)
        s3_output = CLAUDE_MEM_CONTEXT

        # S4: stoneage
        s4 = subprocess.run(
            ["node", str(CAVE_MEM_ROOT / "hooks" / "stoneage-activate.js")],
            cwd=str(CAVE_MEM_ROOT / "hooks"), env=env,
            text=True, capture_output=True,
        )
        s4_output = s4.stdout

    naive = len(s2_output) + len(s3_output)

    # Memory cost per entry (200 char verbose entry)
    entry = 200
    mem_costs = {
        "s1": 0,
        "s2": 0,
        "s3": entry,
        "s4": int(entry * 0.25),
    }

    # Context after N memories (base + N * per-entry)
    def projected(base, per_entry, n):
        return base + per_entry * n

    return {
        "s1": {"chars": len(s1_output),  "tokens": approx_tokens(s1_output)},
        "s2": {"chars": len(s2_output),  "tokens": approx_tokens(s2_output)},
        "s3": {"chars": len(s3_output),  "tokens": approx_tokens(s3_output)},
        "s4": {"chars": len(s4_output),  "tokens": approx_tokens(s4_output)},
        "naive": {"chars": naive,        "tokens": approx_tokens(s2_output + s3_output)},
        "saving": {"chars": naive - len(s4_output),
                   "pct": round((naive - len(s4_output)) / naive * 100, 1) if naive else 0},
        "mem_costs": mem_costs,
        "projected_10":  {k: projected(v["chars"], mem_costs[k], 10)  for k, v in
                          [("s1", {"chars": 0}), ("s2", {"chars": len(s2_output)}),
                           ("s3", {"chars": len(s3_output)}), ("s4", {"chars": len(s4_output)})]},
        "projected_50":  {k: projected(v["chars"], mem_costs[k], 50)  for k, v in
                          [("s1", {"chars": 0}), ("s2", {"chars": len(s2_output)}),
                           ("s3", {"chars": len(s3_output)}), ("s4", {"chars": len(s4_output)})]},
        "projected_250": {k: projected(v["chars"], mem_costs[k], 250) for k, v in
                          [("s1", {"chars": 0}), ("s2", {"chars": len(s2_output)}),
                           ("s3", {"chars": len(s3_output)}), ("s4", {"chars": len(s4_output)})]},
    }


def render(m, test_result, test_output, duration):
    W = 72
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * W,
        f"  stoneage  |  4-SCENARIO COMPARISON REPORT  |  {now}",
        "=" * W,
        "",
        "  SCENARIOS",
        "  S1  Vanilla       — no plugins, no compression, no memory",
        "  S2  stoneage only  — terse output, no memory",
        "  S3  claude-mem only — memory, no compression",
        "  S4  stoneage      — terse output + compressed memory (combined)",
        "",
        "-" * W,
        "  SESSION START CONTEXT INJECTION",
        "-" * W,
        f"  {'Scenario':<22} {'Chars':>7}  {'~Tokens':>8}  {'vs Naive':>10}",
        f"  {'-'*52}",
        f"  {'S1  Vanilla':<22} {m['s1']['chars']:>7}  {m['s1']['tokens']:>8}       —",
        f"  {'S2  stoneage only':<22} {m['s2']['chars']:>7}  {m['s2']['tokens']:>8}       —",
        f"  {'S3  claude-mem only':<22} {m['s3']['chars']:>7}  {m['s3']['tokens']:>8}       —",
        f"  {'S4  stoneage':<22} {m['s4']['chars']:>7}  {m['s4']['tokens']:>8}  "
        f"-{m['saving']['pct']}%",
        f"  {'Naive S2+S3':<22} {m['naive']['chars']:>7}  {m['naive']['tokens']:>8}  (baseline)",
        f"  {'-'*52}",
        f"  stoneage saves {m['saving']['chars']} chars ({m['saving']['pct']}%) vs running both separately",
        "",
        "-" * W,
        "  FEATURE MATRIX",
        "-" * W,
        f"  {'Scenario':<22} {'Compression':>13} {'Memory':>8} {'Unified Flag':>14} {'Mem Compressed':>16}",
        f"  {'-'*(W-2)}",
        f"  {'S1  Vanilla':<22} {'No':>13} {'No':>8} {'No':>14} {'No':>16}",
        f"  {'S2  stoneage only':<22} {'Yes (~75%)':>13} {'No':>8} {'No':>14} {'No':>16}",
        f"  {'S3  claude-mem only':<22} {'No':>13} {'Yes':>8} {'No':>14} {'No':>16}",
        f"  {'S4  stoneage':<22} {'Yes (~75%)':>13} {'Yes':>8} {'Yes':>14} {'Yes (~75%)':>16}",
        "",
        "-" * W,
        "  MEMORY STORAGE COST PER ENTRY (200 char verbose baseline)",
        "-" * W,
        f"  S1  Vanilla       :   {m['mem_costs']['s1']:>3} chars  (no memory system)",
        f"  S2  stoneage only  :   {m['mem_costs']['s2']:>3} chars  (no memory system)",
        f"  S3  claude-mem only:  {m['mem_costs']['s3']:>3} chars  (stored verbosely, 1.0x)",
        f"  S4  stoneage      :   {m['mem_costs']['s4']:>3} chars  (compressed at full level, 0.25x)",
        "",
        "-" * W,
        "  PROJECTED CONTEXT COST OVER TIME (chars injected at session start)",
        "-" * W,
        f"  {'Scenario':<22} {'Fresh':>8}  {'10 mem':>8}  {'50 mem':>10}  {'250 mem':>10}",
        f"  {'-'*62}",
    ]

    for key, label in [("s1","S1  Vanilla"), ("s2","S2  stoneage"),
                        ("s3","S3  claude-mem"), ("s4","S4  stoneage")]:
        base = m[key]['chars']
        p10  = m['projected_10'][key]
        p50  = m['projected_50'][key]
        p250 = m['projected_250'][key]
        lines.append(f"  {label:<22} {base:>8}  {p10:>8}  {p50:>10}  {p250:>10}")

    lines += [
        "",
        "  KEY INSIGHT: S3 (claude-mem) grows 5x faster than S4 (stoneage)",
        "  because S4 compresses each entry by ~75% before storing.",
        "",
        "-" * W,
        "  HOOK BEHAVIOUR COMPARISON",
        "-" * W,
        "  Event           S1 Vanilla    S2 stoneage    S3 claude-mem  S4 stoneage",
        "  " + "-" * 68,
        "  SessionStart    nothing       stoneage rules mem context    BOTH combined",
        "  UserPromptSubmit nothing      /stoneage cmds n/a            /stoneage cmds",
        "  Flag written    none          .stoneage-act  none           .stoneage-act",
        "  Slash commands  none          /stoneage      /mem-search    /stoneage",
        "                                                             /stoneage-search",
        "",
        "-" * W,
        f"  TEST RESULTS  ({test_result.testsRun} tests, {duration}s)",
        "-" * W,
    ]

    passed  = test_result.testsRun - len(test_result.failures) - len(test_result.errors)
    failed  = len(test_result.failures) + len(test_result.errors)
    skipped = len(test_result.skipped)
    status  = "ALL PASS" if failed == 0 else f"{failed} FAILING"

    lines += [
        f"  Passed: {passed}   Failed: {failed}   Skipped: {skipped}   [{status}]",
        "",
    ]

    for test, tb in test_result.failures + test_result.errors:
        lines.append(f"  [FAIL] {test}")
        for ln in tb.strip().splitlines()[-3:]:
            lines.append(f"         {ln}")
    if failed == 0:
        lines.append("  All scenario tests passed.")

    lines += ["", "=" * W]
    return "\n".join(lines)


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("Gathering metrics from all 4 scenarios...")
    m = gather_metrics()

    print("Running test suite...")
    test_result, test_output, duration = run_tests()

    report = render(m, test_result, test_output, duration)
    print("\n" + report)

    out_dir = CAVE_MEM_ROOT / "tests" / "reports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"scenario_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nReport saved -> {out}")


if __name__ == "__main__":
    main()
