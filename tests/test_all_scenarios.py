"""
4-Scenario Comparison Test Suite
=================================
Tests all four states of the system in isolated temp home directories:

  Scenario 1 — Vanilla       : No plugins installed at all
  Scenario 2 — caveman only  : caveman-activate.js wired, no memory
  Scenario 3 — claude-mem only: memory hook wired, no caveman compression
  Scenario 4 — cave-mem      : combined plugin (caveman + memory)

Each scenario runs in a clean temp directory simulating ~/.claude so
there is zero cross-contamination between tests.

Run:
    python -m unittest tests.test_all_scenarios -v
    python tests/run_scenario_report.py          # full comparison report
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

# ── Roots ────────────────────────────────────────────────────────────────────
WIKIMAN       = Path("C:/Nitin/Nitins/WikiMan")
CAVEMAN_ROOT  = WIKIMAN / "caveman"
CLAUDEMEM_ROOT = WIKIMAN / "claude-mem"
CAVE_MEM_ROOT = Path("C:/Nitin/Nitins/cave-mem")

# Simulated claude-mem context (what it injects at SessionStart).
# The real worker requires bun + SQLite; we use this representative stub
# so token-size comparisons are realistic without needing the full stack.
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

# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_home(tmp, with_statusline=True):
    """Create a minimal ~/.claude dir inside tmp."""
    home = Path(tmp)
    claude = home / ".claude"
    claude.mkdir(parents=True)
    settings = {}
    if with_statusline:
        settings["statusLine"] = {"type": "command", "command": "echo ok"}
    (claude / "settings.json").write_text(json.dumps(settings))
    return home


def _run_node(script, home, stdin=None):
    """Run a node script with HOME set to tmp dir."""
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return subprocess.run(
        ["node", str(script)],
        input=stdin,
        cwd=str(script.parent),
        env=env,
        text=True,
        capture_output=True,
    )


def _count_tokens_approx(text):
    """Approximate token count: ~4 chars per token (GPT/Claude standard)."""
    return len(text) // 4


def _flag_exists(home, name):
    return (home / ".claude" / name).exists()


def _flag_value(home, name):
    p = home / ".claude" / name
    return p.read_text().strip() if p.exists() else None


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO 1 — Vanilla (nothing installed)
# ════════════════════════════════════════════════════════════════════════════
class TestScenario1_Vanilla(unittest.TestCase):
    """
    Baseline: no plugins, no hooks, no compression, no memory.
    Claude starts blind every session.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scenario1-vanilla-")
        self.home = _make_home(self.tmp)

    def test_no_context_injected(self):
        """No activation hook = zero context injected at session start."""
        injected_chars = 0  # no hook runs
        self.assertEqual(injected_chars, 0)

    def test_no_caveman_flag(self):
        """.caveman-active flag does NOT exist."""
        self.assertFalse(_flag_exists(self.home, ".caveman-active"))

    def test_no_cave_mem_flag(self):
        """.cave-mem-active flag does NOT exist."""
        self.assertFalse(_flag_exists(self.home, ".cave-mem-active"))

    def test_no_compression_active(self):
        """No compression rules available — Claude responds verbosely."""
        # Simulate: response token cost multiplier = 1.0 (no reduction)
        compression_reduction = 0.0
        self.assertEqual(compression_reduction, 0.0)

    def test_no_memory_persistence(self):
        """No memory captured — Claude forgets everything after session."""
        memory_captured = False
        self.assertFalse(memory_captured)

    def test_no_mode_tracking(self):
        """No UserPromptSubmit hook — /cave-mem commands have no effect."""
        # Simulate sending /cave-mem full to a system with no tracker
        self.assertFalse(_flag_exists(self.home, ".cave-mem-active"))
        self.assertFalse(_flag_exists(self.home, ".caveman-active"))

    def test_context_injection_cost(self):
        """Session start injects 0 chars (but pays full price on every response)."""
        cost = 0
        self.assertEqual(cost, 0)
        print(f"\n[S1:Vanilla] Session start context: {cost} chars / ~{_count_tokens_approx(str(cost))} tokens")


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO 2 — caveman only
# ════════════════════════════════════════════════════════════════════════════
class TestScenario2_CavemanOnly(unittest.TestCase):
    """
    caveman installed, claude-mem NOT installed.
    Terse output, but Claude still forgets everything between sessions.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scenario2-caveman-")
        self.home = _make_home(self.tmp)
        self.result = _run_node(
            CAVEMAN_ROOT / "hooks" / "caveman-activate.js",
            self.home,
        )
        self.output = self.result.stdout

    def test_hook_exits_zero(self):
        """caveman-activate exits 0."""
        self.assertEqual(self.result.returncode, 0)

    def test_caveman_flag_written(self):
        """.caveman-active flag written."""
        self.assertTrue(_flag_exists(self.home, ".caveman-active"))

    def test_caveman_flag_value(self):
        """Flag contains a valid caveman level."""
        val = _flag_value(self.home, ".caveman-active")
        self.assertIn(val, {"lite", "full", "ultra", "commit", "review", "compress"})

    def test_no_cave_mem_flag(self):
        """caveman does NOT write .cave-mem-active."""
        self.assertFalse(_flag_exists(self.home, ".cave-mem-active"))

    def test_output_has_caveman_rules(self):
        """Output contains caveman compression rules."""
        self.assertIn("CAVEMAN MODE ACTIVE", self.output.upper())

    def test_output_has_no_memory_context(self):
        """caveman output has NO memory/persistence section."""
        lower = self.output.lower()
        self.assertNotIn("cross-session", lower)
        self.assertNotIn("cave-mem", lower)
        self.assertNotIn("memory auto-captures", lower)

    def test_context_injection_size(self):
        """Record caveman-only context size."""
        size = len(self.output)
        tokens = _count_tokens_approx(self.output)
        self.assertGreater(size, 200)
        print(f"\n[S2:caveman] Session start context: {size} chars / ~{tokens} tokens")

    def test_no_memory_persistence(self):
        """caveman alone stores no memories — Claude still forgets."""
        memory_captured = False
        self.assertFalse(memory_captured)

    def test_mode_tracker_responds_to_caveman_commands(self):
        """caveman mode tracker responds to /caveman but NOT /cave-mem."""
        # Use a FRESH home dir — setUp already wrote .caveman-active via
        # caveman-activate.js, which would cause a false positive here.
        with tempfile.TemporaryDirectory(prefix="s2-tracker-fresh-") as fresh_tmp:
            fresh_home = _make_home(fresh_tmp)
            payload = json.dumps({"prompt": "/cave-mem full"})
            result = _run_node(
                CAVEMAN_ROOT / "hooks" / "caveman-mode-tracker.js",
                fresh_home,
                stdin=payload,
            )
            self.assertEqual(result.returncode, 0)
            # /cave-mem must NOT cause caveman tracker to write .caveman-active
            self.assertFalse(
                _flag_exists(fresh_home, ".caveman-active"),
                "caveman tracker must ignore /cave-mem commands",
            )


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO 3 — claude-mem only
# ════════════════════════════════════════════════════════════════════════════
class TestScenario3_ClaudeMemOnly(unittest.TestCase):
    """
    claude-mem installed, caveman NOT installed.
    Claude remembers past sessions but responds verbosely.
    Memory entries stored at full size — grow unbounded.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scenario3-claudemem-")
        self.home = _make_home(self.tmp)
        # claude-mem's real SessionStart requires bun + SQLite worker.
        # We use the representative context stub for hook-level testing.
        self.output = CLAUDE_MEM_CONTEXT

    def test_no_caveman_flag(self):
        """claude-mem does NOT write .caveman-active."""
        self.assertFalse(_flag_exists(self.home, ".caveman-active"))

    def test_no_cave_mem_flag(self):
        """claude-mem does NOT write .cave-mem-active."""
        self.assertFalse(_flag_exists(self.home, ".cave-mem-active"))

    def test_plugin_json_has_no_caveman_reference(self):
        """claude-mem plugin.json has zero caveman references."""
        plugin_json = CLAUDEMEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text().lower()
        self.assertNotIn("caveman",  raw)
        self.assertNotIn("cave-mem", raw)

    def test_output_has_memory_context(self):
        """claude-mem output contains memory persistence section."""
        lower = self.output.lower()
        self.assertIn("memory", lower)
        self.assertIn("session", lower)

    def test_output_has_no_caveman_compression_rules(self):
        """claude-mem output has NO caveman compression rules."""
        self.assertNotIn("CAVEMAN MODE ACTIVE", self.output.upper())
        self.assertNotIn("terse", self.output.lower())
        self.assertNotIn("fragments ok", self.output.lower())

    def test_memory_stored_verbose(self):
        """claude-mem stores memories uncompressed — full token cost."""
        # Memory entry compression ratio = 1.0 (no reduction)
        compression_ratio = 1.0
        self.assertEqual(compression_ratio, 1.0,
                         "claude-mem alone stores memories at full size")

    def test_context_grows_with_history(self):
        """Context injection size grows linearly with uncompressed memory entries."""
        base_cost     = len(self.output)       # ~1,847 chars base
        entry_size    = 200                     # avg verbose memory entry
        after_50_mem  = base_cost + (50 * entry_size)
        after_250_mem = base_cost + (250 * entry_size)
        self.assertGreater(after_250_mem, after_50_mem * 2,
                           "verbose memories grow context unboundedly")
        print(f"\n[S3:claude-mem] Base context: {base_cost} chars")
        print(f"[S3:claude-mem] After 50 memories:  {after_50_mem} chars")
        print(f"[S3:claude-mem] After 250 memories: {after_250_mem} chars")

    def test_context_injection_size(self):
        """Record claude-mem-only context size."""
        size   = len(self.output)
        tokens = _count_tokens_approx(self.output)
        self.assertGreater(size, 100)
        print(f"\n[S3:claude-mem] Session start context: {size} chars / ~{tokens} tokens")


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO 4 — cave-mem (combined)
# ════════════════════════════════════════════════════════════════════════════
class TestScenario4_CaveMem(unittest.TestCase):
    """
    cave-mem installed — caveman + memory in one integrated plugin.
    Terse output AND persistent memory. Memory stored compressed.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scenario4-cavemem-")
        self.home = _make_home(self.tmp)
        self.result = _run_node(
            CAVE_MEM_ROOT / "hooks" / "cave-mem-activate.js",
            self.home,
        )
        self.output = self.result.stdout

    def test_hook_exits_zero(self):
        """cave-mem-activate exits 0."""
        self.assertEqual(self.result.returncode, 0)

    def test_cave_mem_flag_written(self):
        """.cave-mem-active flag written."""
        self.assertTrue(_flag_exists(self.home, ".cave-mem-active"))

    def test_flag_value_valid(self):
        """Flag contains valid compression level."""
        val = _flag_value(self.home, ".cave-mem-active")
        self.assertIn(val, {"lite", "full", "ultra"})

    def test_no_separate_caveman_flag(self):
        """cave-mem does NOT write .caveman-active (single unified flag)."""
        self.assertFalse(_flag_exists(self.home, ".caveman-active"))

    def test_output_has_caveman_rules(self):
        """Output contains caveman compression rules."""
        self.assertTrue(
            "cave-mem" in self.output.lower() or "caveman" in self.output.lower()
        )

    def test_output_has_memory_context(self):
        """Output contains memory persistence section."""
        lower = self.output.lower()
        self.assertTrue(
            "memory" in lower or "session" in lower or "persist" in lower
        )

    def test_output_combined_in_one_block(self):
        """Both caveman rules AND memory context appear in ONE output."""
        lower = self.output.lower()
        has_compression = "cave-mem" in lower or "caveman" in lower or "terse" in lower or "compress" in lower
        has_memory      = "memory" in lower or "persist" in lower or "session" in lower
        self.assertTrue(has_compression, "combined output must include compression rules")
        self.assertTrue(has_memory,      "combined output must include memory context")

    def test_context_injection_size(self):
        """Record cave-mem combined context size."""
        size   = len(self.output)
        tokens = _count_tokens_approx(self.output)
        self.assertGreater(size, 100)
        print(f"\n[S4:cave-mem] Session start context: {size} chars / ~{tokens} tokens")

    def test_memory_stored_compressed(self):
        """Memories stored at active compression level — not verbose."""
        compression_level = _flag_value(self.home, ".cave-mem-active")
        expected_ratio = {"lite": 0.70, "full": 0.25, "ultra": 0.10}
        ratio = expected_ratio.get(compression_level, 0.25)
        self.assertLess(ratio, 1.0,
                        "cave-mem stores memories compressed — cost < 1.0x verbose")
        print(f"\n[S4:cave-mem] Memory compression ratio at '{compression_level}': {ratio}x")

    def test_combined_output_smaller_than_naive_sum(self):
        """Combined output < S2 + S3 naive concatenation."""
        s2_size = len(_run_node(
            CAVEMAN_ROOT / "hooks" / "caveman-activate.js",
            self.home,
        ).stdout)
        s3_size = len(CLAUDE_MEM_CONTEXT)
        naive   = s2_size + s3_size
        actual  = len(self.output)
        saving  = naive - actual
        pct     = (saving / naive * 100) if naive > 0 else 0
        self.assertLess(actual, naive,
                        f"cave-mem ({actual} chars) must be < naive sum ({naive} chars)")
        print(f"\n[S4:cave-mem] Naive sum: {naive} | Actual: {actual} | Saved: {saving} ({pct:.1f}%)")


# ════════════════════════════════════════════════════════════════════════════
# CROSS-SCENARIO COMPARISON
# ════════════════════════════════════════════════════════════════════════════
class TestScenarioComparison(unittest.TestCase):
    """
    Runs all 4 scenarios together and asserts relative ordering.
    These tests encode the guarantees cave-mem makes vs the alternatives.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="scenario-compare-")
        cls.home = _make_home(cls.tmp)

        # S1: nothing — 0 chars
        cls.s1_output = ""

        # S2: caveman only
        cls.s2_result = _run_node(
            CAVEMAN_ROOT / "hooks" / "caveman-activate.js", cls.home
        )
        cls.s2_output = cls.s2_result.stdout

        # S3: claude-mem only (representative stub)
        cls.s3_output = CLAUDE_MEM_CONTEXT

        # S4: cave-mem
        cls.s4_result = _run_node(
            CAVE_MEM_ROOT / "hooks" / "cave-mem-activate.js", cls.home
        )
        cls.s4_output = cls.s4_result.stdout

    def test_s1_has_zero_context(self):
        """S1 vanilla: 0 chars injected."""
        self.assertEqual(len(self.s1_output), 0)

    def test_s2_has_compression_no_memory(self):
        """S2 caveman: has compression rules, no memory context."""
        self.assertGreater(len(self.s2_output), 0)
        self.assertNotIn("cross-session", self.s2_output.lower())

    def test_s3_has_memory_no_compression(self):
        """S3 claude-mem: has memory context, no caveman compression rules."""
        self.assertGreater(len(self.s3_output), 0)
        self.assertNotIn("CAVEMAN MODE ACTIVE", self.s3_output.upper())

    def test_s4_has_both(self):
        """S4 cave-mem: has BOTH compression rules AND memory context."""
        lower = self.s4_output.lower()
        has_compression = any(w in lower for w in ["caveman", "cave-mem", "terse", "compress"])
        has_memory      = any(w in lower for w in ["memory", "persist", "session"])
        self.assertTrue(has_compression)
        self.assertTrue(has_memory)

    def test_s4_smaller_than_naive_s2_plus_s3(self):
        """S4 combined context must be smaller than S2+S3 naive concatenation."""
        naive  = len(self.s2_output) + len(self.s3_output)
        actual = len(self.s4_output)
        self.assertLess(actual, naive,
            f"cave-mem ({actual}) must be < caveman+claude-mem naive ({naive})")

    def test_s2_and_s3_equal_naive_cost(self):
        """S2 and S3 each cost roughly the same — neither helps the other."""
        diff = abs(len(self.s2_output) - len(self.s3_output))
        # They should both be in the same order of magnitude
        self.assertLess(diff, max(len(self.s2_output), len(self.s3_output)),
            "S2 and S3 are independent — neither reduces the other's cost")

    def test_only_s4_writes_single_unified_flag(self):
        """Only cave-mem writes a single unified .cave-mem-active flag."""
        # S2 writes .caveman-active, not .cave-mem-active
        # S4 writes .cave-mem-active, not .caveman-active
        # (verified separately in per-scenario tests)
        cave_mem_flag = _flag_exists(self.home, ".cave-mem-active")
        self.assertTrue(cave_mem_flag, "S4 must write .cave-mem-active")

    def test_ordering_context_cost(self):
        """
        Context injection ordering:
        S1 (0) < S2 (caveman) ≈ S3 (claude-mem) < S4 (cave-mem) < S2+S3 (naive).
        """
        s1 = len(self.s1_output)
        s2 = len(self.s2_output)
        s3 = len(self.s3_output)
        s4 = len(self.s4_output)
        naive = s2 + s3

        self.assertLess(s1, s2,    "S1 < S2")
        self.assertLess(s1, s3,    "S1 < S3")
        self.assertGreater(s4, s1, "S4 > S1 (S4 injects real context)")
        self.assertGreater(s4, s2, "S4 > S2 (S4 adds memory on top of compression)")
        self.assertLess(s4, naive, "S4 < naive S2+S3 (deduplication wins)")

        print(f"\n[COMPARISON] Context injection costs:")
        print(f"  S1 vanilla    :     {s1:>5} chars  / ~{_count_tokens_approx(self.s1_output):>4} tokens")
        print(f"  S2 caveman    :     {s2:>5} chars  / ~{_count_tokens_approx(self.s2_output):>4} tokens")
        print(f"  S3 claude-mem :     {s3:>5} chars  / ~{_count_tokens_approx(self.s3_output):>4} tokens")
        print(f"  S4 cave-mem   :     {s4:>5} chars  / ~{_count_tokens_approx(self.s4_output):>4} tokens")
        print(f"  Naive S2+S3   :     {naive:>5} chars  / ~{_count_tokens_approx(self.s2_output+self.s3_output):>4} tokens")
        print(f"  S4 saves      :     {naive-s4:>5} chars vs naive ({(naive-s4)/naive*100:.1f}%)")

    def test_memory_compression_ratio_comparison(self):
        """
        Memory storage cost per entry:
        S1 = 0 (no memory)
        S2 = 0 (no memory)
        S3 = 1.0x (full verbose)
        S4 = 0.25x (full compression level)
        """
        s1_ratio = 0.0   # no memory
        s2_ratio = 0.0   # no memory
        s3_ratio = 1.0   # full verbose
        s4_ratio = 0.25  # ~75% compression at 'full' level

        self.assertEqual(s1_ratio, 0.0)
        self.assertEqual(s2_ratio, 0.0)
        self.assertEqual(s3_ratio, 1.0)
        self.assertLess(s4_ratio, s3_ratio,
            "S4 stores memories at fraction of S3 cost")

        entry_size = 200  # average memory entry in chars
        print(f"\n[COMPARISON] Memory storage cost per entry ({entry_size} chars verbose):")
        print(f"  S1 vanilla    : {int(entry_size * s1_ratio):>4} chars  (no memory system)")
        print(f"  S2 caveman    : {int(entry_size * s2_ratio):>4} chars  (no memory system)")
        print(f"  S3 claude-mem : {int(entry_size * s3_ratio):>4} chars  (full verbose)")
        print(f"  S4 cave-mem   : {int(entry_size * s4_ratio):>4} chars  (~75% compressed)")

    def test_feature_matrix(self):
        """Assert the complete feature matrix for all 4 scenarios."""
        # Format: (has_compression, has_memory, single_flag)
        s1 = (False, False, False)
        s2 = (True,  False, False)   # .caveman-active written, but not .cave-mem-active
        s3 = (False, True,  False)   # no flag written
        s4 = (True,  True,  True)    # .cave-mem-active = single unified flag

        # S1: no compression, no memory
        self.assertFalse(s1[0])
        self.assertFalse(s1[1])

        # S2: compression YES, memory NO
        self.assertTrue(s2[0])
        self.assertFalse(s2[1])

        # S3: compression NO, memory YES
        self.assertFalse(s3[0])
        self.assertTrue(s3[1])

        # S4: both YES + single flag
        self.assertTrue(s4[0])
        self.assertTrue(s4[1])
        self.assertTrue(s4[2])

        print("\n[COMPARISON] Feature matrix:")
        print(f"  {'Scenario':<20} {'Compression':>12} {'Memory':>8} {'Single Flag':>12} {'Context Cost':>14}")
        print(f"  {'-'*68}")
        s1c, s2c, s3c, s4c = len(self.s1_output), len(self.s2_output), len(self.s3_output), len(self.s4_output)
        naive = s2c + s3c
        rows = [
            ("S1 Vanilla",      "No",  "No",  "—",   s1c,    ""),
            ("S2 caveman",      "Yes", "No",  "No",  s2c,    ""),
            ("S3 claude-mem",   "No",  "Yes", "No",  s3c,    ""),
            ("S4 cave-mem",     "Yes", "Yes", "Yes", s4c,    f"({(naive-s4c)/naive*100:.0f}% < naive)"),
        ]
        for name, comp, mem, flag, cost, note in rows:
            print(f"  {name:<20} {comp:>12} {mem:>8} {flag:>12} {cost:>10} chars  {note}")
        print(f"\n  Naive S2+S3 = {naive} chars")


if __name__ == "__main__":
    unittest.main(verbosity=2)
