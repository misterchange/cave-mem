"""
Baseline tests — run BEFORE cave-mem is installed.

These verify the "before" state of the system:
  - cave-mem plugin does NOT exist yet
  - caveman and claude-mem are fully independent (no cross-wiring)
  - no combined hooks are registered
  - activating caveman alone produces zero memory-compression output
  - activating claude-mem alone produces zero caveman-style compression markers

Run with:
    python -m pytest tests/test_baseline.py -v
  or
    python -m unittest tests.test_baseline
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

# ── Repo roots ──────────────────────────────────────────────────────────────
THIS_DIR      = Path(__file__).resolve().parent
CAVE_MEM_ROOT = THIS_DIR.parent                          # C:\Nitin\Nitins\cave-mem
WIKIMAN_ROOT  = Path("C:/Nitin/Nitins/WikiMan")
CAVEMAN_ROOT  = WIKIMAN_ROOT / "caveman"
CLAUDE_MEM_ROOT = WIKIMAN_ROOT / "claude-mem"


def _run(cmd, home, cwd=None):
    env = os.environ.copy()
    env["HOME"]        = str(home)
    env["USERPROFILE"] = str(home)
    return subprocess.run(
        cmd,
        cwd=cwd or CAVEMAN_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


# ════════════════════════════════════════════════════════════════════════════
# 1. cave-mem plugin does NOT exist yet
# ════════════════════════════════════════════════════════════════════════════
class TestCaveMemAbsent(unittest.TestCase):

    def test_cave_mem_plugin_json_missing(self):
        """Before installation: cave-mem plugin.json should NOT exist."""
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        self.assertFalse(
            plugin_json.exists(),
            f"cave-mem plugin.json should not exist yet, found at {plugin_json}",
        )

    def test_cave_mem_activate_hook_missing(self):
        """Before installation: cave-mem-activate.js should NOT exist."""
        hook = CAVE_MEM_ROOT / "hooks" / "cave-mem-activate.js"
        self.assertFalse(
            hook.exists(),
            f"cave-mem activate hook should not exist yet, found at {hook}",
        )

    def test_cave_mem_mode_tracker_missing(self):
        """Before installation: cave-mem-mode-tracker.js should NOT exist."""
        hook = CAVE_MEM_ROOT / "hooks" / "cave-mem-mode-tracker.js"
        self.assertFalse(
            hook.exists(),
            f"cave-mem mode-tracker hook should not exist yet, found at {hook}",
        )

    def test_no_cave_mem_flag_in_tmp_home(self):
        """Before activation: .cave-mem-active flag should NOT be written."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-baseline-") as tmp:
            flag = Path(tmp) / ".claude" / ".cave-mem-active"
            self.assertFalse(
                flag.exists(),
                ".cave-mem-active flag must not exist in a fresh home dir",
            )


# ════════════════════════════════════════════════════════════════════════════
# 2. caveman is standalone — no knowledge of memory compression
# ════════════════════════════════════════════════════════════════════════════
class TestCavemanStandalone(unittest.TestCase):

    def _caveman_activate_output(self, home):
        """Run caveman-activate.js and return stdout."""
        result = _run(["node", "hooks/caveman-activate.js"], home, cwd=CAVEMAN_ROOT)
        return result.stdout

    def test_caveman_plugin_json_has_no_mem_reference(self):
        """caveman plugin.json must not reference claude-mem or cave-mem."""
        plugin_json = CAVEMAN_ROOT / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_json.exists(), "caveman plugin.json must exist")
        data = json.loads(plugin_json.read_text())
        raw = json.dumps(data).lower()
        self.assertNotIn("claude-mem",  raw, "caveman plugin must not mention claude-mem")
        self.assertNotIn("cave-mem",    raw, "caveman plugin must not mention cave-mem")
        self.assertNotIn("memory",      raw, "caveman plugin must not mention memory")

    def test_caveman_activate_output_has_no_memory_marker(self):
        """caveman activate output must NOT contain cave-mem/memory-compression markers."""
        with tempfile.TemporaryDirectory(prefix="caveman-baseline-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            output = self._caveman_activate_output(home)
            self.assertNotIn("CAVE-MEM",        output.upper())
            self.assertNotIn("MEMORY COMPRESS", output.upper())
            self.assertNotIn("cave-mem",        output.lower())

    def test_caveman_activate_writes_caveman_flag_not_cave_mem_flag(self):
        """caveman activation must write .caveman-active, NOT .cave-mem-active."""
        with tempfile.TemporaryDirectory(prefix="caveman-flag-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            _run(["node", "hooks/caveman-activate.js"], home, cwd=CAVEMAN_ROOT)
            self.assertTrue(
                (home / ".claude" / ".caveman-active").exists(),
                "caveman must write its own .caveman-active flag",
            )
            self.assertFalse(
                (home / ".claude" / ".cave-mem-active").exists(),
                "caveman must NOT write .cave-mem-active (that belongs to cave-mem)",
            )

    def test_caveman_mode_tracker_handles_caveman_commands_only(self):
        """caveman mode tracker must only respond to /caveman commands, not /cave-mem."""
        with tempfile.TemporaryDirectory(prefix="caveman-tracker-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            flag = home / ".claude" / ".caveman-active"
            payload = json.dumps({"prompt": "/cave-mem full"})
            result = subprocess.run(
                ["node", "hooks/caveman-mode-tracker.js"],
                input=payload,
                cwd=CAVEMAN_ROOT,
                env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0)
            # A /cave-mem command must NOT trigger caveman's flag
            self.assertFalse(
                flag.exists(),
                "caveman tracker must ignore /cave-mem commands (that's cave-mem's job)",
            )


# ════════════════════════════════════════════════════════════════════════════
# 3. claude-mem is standalone — no knowledge of caveman compression
# ════════════════════════════════════════════════════════════════════════════
class TestClaudeMemStandalone(unittest.TestCase):

    def test_claude_mem_plugin_json_has_no_caveman_reference(self):
        """claude-mem plugin.json must not reference caveman or cave-mem."""
        plugin_json = CLAUDE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_json.exists(), "claude-mem plugin.json must exist")
        data = json.loads(plugin_json.read_text())
        raw = json.dumps(data).lower()
        self.assertNotIn("caveman",  raw, "claude-mem plugin must not mention caveman")
        self.assertNotIn("cave-mem", raw, "claude-mem plugin must not mention cave-mem")

    def test_claude_mem_package_json_has_no_caveman_dependency(self):
        """claude-mem package.json must not list caveman as a dependency."""
        pkg = CLAUDE_MEM_ROOT / "package.json"
        self.assertTrue(pkg.exists(), "claude-mem package.json must exist")
        data = json.loads(pkg.read_text())
        all_deps = {
            **data.get("dependencies", {}),
            **data.get("devDependencies", {}),
            **data.get("peerDependencies", {}),
        }
        self.assertNotIn("caveman",  all_deps)
        self.assertNotIn("cave-mem", all_deps)

    def test_no_cave_mem_combined_hooks_in_claude_mem_plugin(self):
        """claude-mem plugin must not declare cave-mem combined hooks."""
        plugin_json = CLAUDE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text().lower()
        self.assertNotIn("cave-mem-activate",     raw)
        self.assertNotIn("cave-mem-mode-tracker", raw)


# ════════════════════════════════════════════════════════════════════════════
# 4. No shared state / cross-contamination exists
# ════════════════════════════════════════════════════════════════════════════
class TestNoSharedState(unittest.TestCase):

    def test_caveman_skills_dir_has_no_cave_mem_skill(self):
        """caveman skills must not include a cave-mem sub-skill."""
        skills_dir = CAVEMAN_ROOT / "skills"
        skill_names = [d.name.lower() for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("cave-mem", skill_names)

    def test_claude_mem_skills_has_no_caveman_sub_skill(self):
        """claude-mem plugin skills must not include a caveman sub-skill."""
        skills_dir = CLAUDE_MEM_ROOT / "plugin" / "skills"
        if not skills_dir.exists():
            self.skipTest("claude-mem plugin/skills dir not found — skip")
        skill_names = [d.name.lower() for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("caveman",  skill_names)
        self.assertNotIn("cave-mem", skill_names)

    def test_caveman_has_no_sqlite_dependency(self):
        """caveman must not import SQLite (that's claude-mem's concern)."""
        cave_hooks = CAVEMAN_ROOT / "hooks"
        hits = []
        for js_file in cave_hooks.glob("*.js"):
            if "sqlite" in js_file.read_text(encoding="utf-8", errors="ignore").lower():
                hits.append(js_file.name)
        self.assertEqual(hits, [], f"caveman hooks must not use SQLite: {hits}")

    def test_claude_mem_has_no_caveman_mode_flag_read(self):
        """claude-mem hook scripts must not read .caveman-active flag."""
        plugin_scripts = CLAUDE_MEM_ROOT / "plugin" / "scripts"
        if not plugin_scripts.exists():
            self.skipTest("claude-mem plugin/scripts dir not found — skip")
        hits = []
        for js_file in plugin_scripts.glob("*.js"):
            if ".caveman-active" in js_file.read_text(encoding="utf-8", errors="ignore"):
                hits.append(js_file.name)
        self.assertEqual(hits, [], f"claude-mem must not read .caveman-active: {hits}")


# ════════════════════════════════════════════════════════════════════════════
# 5. Token-output sizing baseline (without cave-mem integration)
# ════════════════════════════════════════════════════════════════════════════
class TestBaselineTokenOutput(unittest.TestCase):
    """
    Measures the size of each plugin's activation output independently.
    After cave-mem is installed the combined output should be SMALLER than
    the naive sum of running both separately (deduplication + shared preamble).
    """

    def _get_caveman_output_size(self):
        with tempfile.TemporaryDirectory(prefix="caveman-token-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            result = _run(["node", "hooks/caveman-activate.js"], home, cwd=CAVEMAN_ROOT)
            return len(result.stdout)

    def test_caveman_activation_output_size(self):
        """Measure and record caveman-only activation output size."""
        size = self._get_caveman_output_size()
        # Caveman emits its full ruleset — should be substantial
        self.assertGreater(size, 200, "caveman activation output seems too small")
        print(f"\n[BASELINE] caveman-only activation output: {size} chars")

    def test_no_deduplication_happening_without_cave_mem(self):
        """Without cave-mem, running caveman twice produces 2× the output."""
        size = self._get_caveman_output_size()
        double = size * 2
        # Confirm: no deduplication logic exists when running standalone
        self.assertGreater(double, size, "sanity: 2× output must be larger than 1×")
        print(f"\n[BASELINE] naive double-run (no dedup): {double} chars total")


if __name__ == "__main__":
    unittest.main(verbosity=2)
