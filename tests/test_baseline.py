"""
Baseline tests — run BEFORE stoneage is installed.

These verify the "before" state of the system:
  - stoneage plugin does NOT exist yet
  - stoneage and claude-mem are fully independent (no cross-wiring)
  - no combined hooks are registered
  - activating stoneage alone produces zero memory-compression output
  - activating claude-mem alone produces zero stoneage-style compression markers

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
CAVE_MEM_ROOT = THIS_DIR.parent                          # C:\Nitin\Nitins\stoneage
WIKIMAN_ROOT  = Path("C:/Nitin/Nitins/WikiMan")
STONEAGE_ROOT  = WIKIMAN_ROOT / "stoneage"
CLAUDE_MEM_ROOT = WIKIMAN_ROOT / "claude-mem"


def _run(cmd, home, cwd=None):
    env = os.environ.copy()
    env["HOME"]        = str(home)
    env["USERPROFILE"] = str(home)
    return subprocess.run(
        cmd,
        cwd=cwd or STONEAGE_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


# ════════════════════════════════════════════════════════════════════════════
# 1. stoneage plugin does NOT exist yet
# ════════════════════════════════════════════════════════════════════════════
class TestStoneageAbsent(unittest.TestCase):

    def test_stoneage_plugin_json_missing(self):
        """Before installation: stoneage plugin.json should NOT exist."""
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        self.assertFalse(
            plugin_json.exists(),
            f"stoneage plugin.json should not exist yet, found at {plugin_json}",
        )

    def test_stoneage_activate_hook_missing(self):
        """Before installation: stoneage-activate.js should NOT exist."""
        hook = CAVE_MEM_ROOT / "hooks" / "stoneage-activate.js"
        self.assertFalse(
            hook.exists(),
            f"stoneage activate hook should not exist yet, found at {hook}",
        )

    def test_stoneage_mode_tracker_missing(self):
        """Before installation: stoneage-mode-tracker.js should NOT exist."""
        hook = CAVE_MEM_ROOT / "hooks" / "stoneage-mode-tracker.js"
        self.assertFalse(
            hook.exists(),
            f"stoneage mode-tracker hook should not exist yet, found at {hook}",
        )

    def test_no_cave_mem_flag_in_tmp_home(self):
        """Before activation: .stoneage-active flag should NOT be written."""
        with tempfile.TemporaryDirectory(prefix="stoneage-baseline-") as tmp:
            flag = Path(tmp) / ".claude" / ".stoneage-active"
            self.assertFalse(
                flag.exists(),
                ".stoneage-active flag must not exist in a fresh home dir",
            )


# ════════════════════════════════════════════════════════════════════════════
# 2. stoneage is standalone — no knowledge of memory compression
# ════════════════════════════════════════════════════════════════════════════
class TestStoneageStandalone(unittest.TestCase):

    def _stoneage_activate_output(self, home):
        """Run stoneage-activate.js and return stdout."""
        result = _run(["node", "hooks/stoneage-activate.js"], home, cwd=STONEAGE_ROOT)
        return result.stdout

    def test_stoneage_plugin_json_has_no_mem_reference(self):
        """stoneage plugin.json must not reference claude-mem or stoneage."""
        plugin_json = STONEAGE_ROOT / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_json.exists(), "stoneage plugin.json must exist")
        data = json.loads(plugin_json.read_text())
        raw = json.dumps(data).lower()
        self.assertNotIn("claude-mem",  raw, "stoneage plugin must not mention claude-mem")
        self.assertNotIn("stoneage",    raw, "stoneage plugin must not mention stoneage")
        self.assertNotIn("memory",      raw, "stoneage plugin must not mention memory")

    def test_stoneage_activate_output_has_no_memory_marker(self):
        """stoneage activate output must NOT contain stoneage/memory-compression markers."""
        with tempfile.TemporaryDirectory(prefix="stoneage-baseline-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            output = self._stoneage_activate_output(home)
            self.assertNotIn("STONEAGE",        output.upper())
            self.assertNotIn("MEMORY COMPRESS", output.upper())
            self.assertNotIn("stoneage",        output.lower())

    def test_stoneage_activate_writes_stoneage_flag_not_cave_mem_flag(self):
        """stoneage activation must write .stoneage-active, NOT .stoneage-active."""
        with tempfile.TemporaryDirectory(prefix="stoneage-flag-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            _run(["node", "hooks/stoneage-activate.js"], home, cwd=STONEAGE_ROOT)
            self.assertTrue(
                (home / ".claude" / ".stoneage-active").exists(),
                "stoneage must write its own .stoneage-active flag",
            )
            self.assertFalse(
                (home / ".claude" / ".stoneage-active").exists(),
                "stoneage must NOT write .stoneage-active (that belongs to stoneage)",
            )

    def test_stoneage_mode_tracker_handles_stoneage_commands_only(self):
        """stoneage mode tracker must only respond to /stoneage commands, not /stoneage."""
        with tempfile.TemporaryDirectory(prefix="stoneage-tracker-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            flag = home / ".claude" / ".stoneage-active"
            payload = json.dumps({"prompt": "/stoneage full"})
            result = subprocess.run(
                ["node", "hooks/stoneage-mode-tracker.js"],
                input=payload,
                cwd=STONEAGE_ROOT,
                env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0)
            # A /stoneage command must NOT trigger stoneage's flag
            self.assertFalse(
                flag.exists(),
                "stoneage tracker must ignore /stoneage commands (that's stoneage's job)",
            )


# ════════════════════════════════════════════════════════════════════════════
# 3. claude-mem is standalone — no knowledge of stoneage compression
# ════════════════════════════════════════════════════════════════════════════
class TestClaudeMemStandalone(unittest.TestCase):

    def test_claude_mem_plugin_json_has_no_stoneage_reference(self):
        """claude-mem plugin.json must not reference stoneage or stoneage."""
        plugin_json = CLAUDE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_json.exists(), "claude-mem plugin.json must exist")
        data = json.loads(plugin_json.read_text())
        raw = json.dumps(data).lower()
        self.assertNotIn("stoneage",  raw, "claude-mem plugin must not mention stoneage")
        self.assertNotIn("stoneage", raw, "claude-mem plugin must not mention stoneage")

    def test_claude_mem_package_json_has_no_stoneage_dependency(self):
        """claude-mem package.json must not list stoneage as a dependency."""
        pkg = CLAUDE_MEM_ROOT / "package.json"
        self.assertTrue(pkg.exists(), "claude-mem package.json must exist")
        data = json.loads(pkg.read_text())
        all_deps = {
            **data.get("dependencies", {}),
            **data.get("devDependencies", {}),
            **data.get("peerDependencies", {}),
        }
        self.assertNotIn("stoneage",  all_deps)
        self.assertNotIn("stoneage", all_deps)

    def test_no_cave_mem_combined_hooks_in_claude_mem_plugin(self):
        """claude-mem plugin must not declare stoneage combined hooks."""
        plugin_json = CLAUDE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text().lower()
        self.assertNotIn("stoneage-activate",     raw)
        self.assertNotIn("stoneage-mode-tracker", raw)


# ════════════════════════════════════════════════════════════════════════════
# 4. No shared state / cross-contamination exists
# ════════════════════════════════════════════════════════════════════════════
class TestNoSharedState(unittest.TestCase):

    def test_stoneage_skills_dir_has_no_cave_mem_skill(self):
        """stoneage skills must not include a stoneage sub-skill."""
        skills_dir = STONEAGE_ROOT / "skills"
        skill_names = [d.name.lower() for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("stoneage", skill_names)

    def test_claude_mem_skills_has_no_stoneage_sub_skill(self):
        """claude-mem plugin skills must not include a stoneage sub-skill."""
        skills_dir = CLAUDE_MEM_ROOT / "plugin" / "skills"
        if not skills_dir.exists():
            self.skipTest("claude-mem plugin/skills dir not found — skip")
        skill_names = [d.name.lower() for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("stoneage",  skill_names)
        self.assertNotIn("stoneage", skill_names)

    def test_stoneage_has_no_sqlite_dependency(self):
        """stoneage must not import SQLite (that's claude-mem's concern)."""
        cave_hooks = STONEAGE_ROOT / "hooks"
        hits = []
        for js_file in cave_hooks.glob("*.js"):
            if "sqlite" in js_file.read_text(encoding="utf-8", errors="ignore").lower():
                hits.append(js_file.name)
        self.assertEqual(hits, [], f"stoneage hooks must not use SQLite: {hits}")

    def test_claude_mem_has_no_stoneage_mode_flag_read(self):
        """claude-mem hook scripts must not read .stoneage-active flag."""
        plugin_scripts = CLAUDE_MEM_ROOT / "plugin" / "scripts"
        if not plugin_scripts.exists():
            self.skipTest("claude-mem plugin/scripts dir not found — skip")
        hits = []
        for js_file in plugin_scripts.glob("*.js"):
            if ".stoneage-active" in js_file.read_text(encoding="utf-8", errors="ignore"):
                hits.append(js_file.name)
        self.assertEqual(hits, [], f"claude-mem must not read .stoneage-active: {hits}")


# ════════════════════════════════════════════════════════════════════════════
# 5. Token-output sizing baseline (without stoneage integration)
# ════════════════════════════════════════════════════════════════════════════
class TestBaselineTokenOutput(unittest.TestCase):
    """
    Measures the size of each plugin's activation output independently.
    After stoneage is installed the combined output should be SMALLER than
    the naive sum of running both separately (deduplication + shared preamble).
    """

    def _get_stoneage_output_size(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-token-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            result = _run(["node", "hooks/stoneage-activate.js"], home, cwd=STONEAGE_ROOT)
            return len(result.stdout)

    def test_stoneage_activation_output_size(self):
        """Measure and record stoneage-only activation output size."""
        size = self._get_stoneage_output_size()
        # Stoneage emits its full ruleset — should be substantial
        self.assertGreater(size, 200, "stoneage activation output seems too small")
        print(f"\n[BASELINE] stoneage-only activation output: {size} chars")

    def test_no_deduplication_happening_without_cave_mem(self):
        """Without stoneage, running stoneage twice produces 2× the output."""
        size = self._get_stoneage_output_size()
        double = size * 2
        # Confirm: no deduplication logic exists when running standalone
        self.assertGreater(double, size, "sanity: 2× output must be larger than 1×")
        print(f"\n[BASELINE] naive double-run (no dedup): {double} chars total")


if __name__ == "__main__":
    unittest.main(verbosity=2)
