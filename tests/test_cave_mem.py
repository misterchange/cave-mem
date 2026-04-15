"""
cave-mem post-install tests — run AFTER cave-mem is created and activated.

These verify the "after" state of the system:
  - plugin.json has correct combined structure
  - hooks exist and behave correctly
  - activation writes .cave-mem-active flag (NOT the separate .caveman-active)
  - combined activation output < naive sum of caveman + claude-mem outputs
  - /cave-mem commands are tracked by mode-tracker
  - config layer correctly exposes compression levels
  - "off" mode skips flag and emits nothing

Run with:
    python -m pytest tests/test_cave_mem.py -v
  or
    python -m unittest tests.test_cave_mem
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

# ── Repo roots ──────────────────────────────────────────────────────────────
THIS_DIR        = Path(__file__).resolve().parent
CAVE_MEM_ROOT   = THIS_DIR.parent
WIKIMAN_ROOT    = Path("C:/Nitin/Nitins/WikiMan")
CAVEMAN_ROOT    = WIKIMAN_ROOT / "caveman"
CLAUDE_MEM_ROOT = WIKIMAN_ROOT / "claude-mem"


def _run_hook(hook_filename, home, stdin_data=None, env_extra=None):
    """Run a cave-mem hook script and return the CompletedProcess."""
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["node", str(CAVE_MEM_ROOT / "hooks" / hook_filename)],
        input=stdin_data,
        cwd=CAVE_MEM_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def _fresh_home_with_settings(tmp, extra_settings=None):
    home = Path(tmp)
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    settings = {"statusLine": {"type": "command", "command": "echo ok"}}
    if extra_settings:
        settings.update(extra_settings)
    (claude_dir / "settings.json").write_text(json.dumps(settings))
    return home


# ════════════════════════════════════════════════════════════════════════════
# 1. Plugin structure
# ════════════════════════════════════════════════════════════════════════════
class TestPluginStructure(unittest.TestCase):

    def test_plugin_json_exists(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_json.exists(), "cave-mem .claude-plugin/plugin.json must exist")

    def test_plugin_json_has_required_fields(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        self.assertEqual(data["name"], "cave-mem",
                         "plugin name must be 'cave-mem'")
        self.assertIn("description", data)
        self.assertIn("hooks", data)

    def test_plugin_json_declares_session_start_hook(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        self.assertIn("SessionStart", data["hooks"],
                      "cave-mem plugin must declare a SessionStart hook")

    def test_plugin_json_declares_user_prompt_submit_hook(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        self.assertIn("UserPromptSubmit", data["hooks"],
                      "cave-mem plugin must declare a UserPromptSubmit hook")

    def test_plugin_json_references_cave_mem_activate(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text()
        self.assertIn("cave-mem-activate.js", raw,
                      "SessionStart hook must point to cave-mem-activate.js")

    def test_plugin_json_references_cave_mem_mode_tracker(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text()
        self.assertIn("cave-mem-mode-tracker.js", raw,
                      "UserPromptSubmit hook must point to cave-mem-mode-tracker.js")

    def test_hooks_directory_has_all_three_files(self):
        hooks_dir = CAVE_MEM_ROOT / "hooks"
        required = [
            "cave-mem-config.js",
            "cave-mem-activate.js",
            "cave-mem-mode-tracker.js",
        ]
        for name in required:
            self.assertTrue((hooks_dir / name).exists(),
                            f"hooks/{name} must exist")

    def test_skill_md_exists(self):
        skill = CAVE_MEM_ROOT / "skills" / "cave-mem" / "SKILL.md"
        self.assertTrue(skill.exists(), "skills/cave-mem/SKILL.md must exist")


# ════════════════════════════════════════════════════════════════════════════
# 2. cave-mem-activate.js behaviour
# ════════════════════════════════════════════════════════════════════════════
class TestActivateHook(unittest.TestCase):

    def test_activate_exits_zero(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-activate-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("cave-mem-activate.js", home)
            self.assertEqual(result.returncode, 0,
                             f"activate hook must exit 0, stderr: {result.stderr}")

    def test_activate_writes_cave_mem_active_flag(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-flag-") as tmp:
            home = _fresh_home_with_settings(tmp)
            _run_hook("cave-mem-activate.js", home)
            flag = home / ".claude" / ".cave-mem-active"
            self.assertTrue(flag.exists(), ".cave-mem-active flag must be written")

    def test_activate_flag_contains_compression_level(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-level-") as tmp:
            home = _fresh_home_with_settings(tmp)
            _run_hook("cave-mem-activate.js", home)
            flag = home / ".claude" / ".cave-mem-active"
            level = flag.read_text().strip()
            self.assertIn(level, {"lite", "full", "ultra", "off"},
                          f"flag must contain a valid compression level, got: '{level}'")

    def test_activate_output_contains_cave_mem_marker(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-out-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("cave-mem-activate.js", home)
            self.assertIn("CAVE-MEM", result.stdout.upper(),
                          "activation output must contain CAVE-MEM header")

    def test_activate_output_contains_caveman_rules(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-rules-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("cave-mem-activate.js", home)
            # Caveman rules contain key phrases about brevity
            output_lower = result.stdout.lower()
            has_caveman = (
                "caveman" in output_lower
                or "terse" in output_lower
                or "compress" in output_lower
            )
            self.assertTrue(has_caveman,
                            "activation output must embed caveman compression rules")

    def test_activate_output_contains_memory_marker(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-mem-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("cave-mem-activate.js", home)
            output_lower = result.stdout.lower()
            has_mem = (
                "memory" in output_lower
                or "persist" in output_lower
                or "session" in output_lower
            )
            self.assertTrue(has_mem,
                            "activation output must reference memory persistence")

    def test_activate_off_mode_writes_no_flag(self):
        """When compression is set to 'off', no .cave-mem-active flag is written."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-off-") as tmp:
            home = _fresh_home_with_settings(tmp)
            config = home / ".claude" / ".cave-mem-config.json"
            config.write_text(json.dumps({"compression": "off"}))
            _run_hook("cave-mem-activate.js", home)
            flag = home / ".claude" / ".cave-mem-active"
            self.assertFalse(flag.exists(),
                             "off mode must NOT write .cave-mem-active")

    def test_activate_nudges_statusline_when_missing(self):
        """If settings.json lacks statusLine, activate must emit a setup nudge."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-status-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text("{}\n")
            result = _run_hook("cave-mem-activate.js", home)
            self.assertIn("STATUSLINE", result.stdout.upper(),
                          "activate must nudge about statusline setup when it is missing")

    def test_activate_does_not_nudge_when_statusline_configured(self):
        """If settings.json already has statusLine, no nudge should appear."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-no-nudge-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("cave-mem-activate.js", home)
            self.assertNotIn("STATUSLINE SETUP NEEDED", result.stdout,
                             "activate must NOT nudge when statusLine is already configured")


# ════════════════════════════════════════════════════════════════════════════
# 3. cave-mem-mode-tracker.js behaviour
# ════════════════════════════════════════════════════════════════════════════
class TestModeTrackerHook(unittest.TestCase):

    def _track(self, home, prompt):
        return _run_hook(
            "cave-mem-mode-tracker.js",
            home,
            stdin_data=json.dumps({"prompt": prompt}),
        )

    def test_tracker_exits_zero_on_normal_prompt(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-tracker-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = self._track(home, "hello world")
            self.assertEqual(result.returncode, 0)

    def test_tracker_cave_mem_full_sets_flag(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-full-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/cave-mem full")
            flag = home / ".claude" / ".cave-mem-active"
            self.assertTrue(flag.exists(), "/cave-mem full must create flag")
            self.assertEqual(flag.read_text().strip(), "full")

    def test_tracker_cave_mem_lite_sets_flag(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-lite-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/cave-mem lite")
            flag = home / ".claude" / ".cave-mem-active"
            self.assertTrue(flag.exists())
            self.assertEqual(flag.read_text().strip(), "lite")

    def test_tracker_cave_mem_ultra_sets_flag(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-ultra-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/cave-mem ultra")
            flag = home / ".claude" / ".cave-mem-active"
            self.assertTrue(flag.exists())
            self.assertEqual(flag.read_text().strip(), "ultra")

    def test_tracker_stop_cave_mem_removes_flag(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-stop-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".cave-mem-active"
            flag.write_text("full")
            self._track(home, "stop cave-mem")
            self.assertFalse(flag.exists(), "stop cave-mem must remove flag")

    def test_tracker_normal_mode_removes_flag(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-normal-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".cave-mem-active"
            flag.write_text("full")
            self._track(home, "normal mode")
            self.assertFalse(flag.exists(), "'normal mode' must remove cave-mem flag")

    def test_tracker_ignores_unrelated_prompt(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-unrelated-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".cave-mem-active"
            flag.write_text("full")  # pre-existing
            self._track(home, "please fix the bug in my code")
            # Flag must be unchanged
            self.assertTrue(flag.exists(), "unrelated prompt must not remove flag")
            self.assertEqual(flag.read_text().strip(), "full")

    def test_tracker_cave_mem_default_sets_full(self):
        """/cave-mem with no argument defaults to 'full' compression."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-default-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/cave-mem")
            flag = home / ".claude" / ".cave-mem-active"
            self.assertTrue(flag.exists())
            self.assertEqual(flag.read_text().strip(), "full",
                             "/cave-mem with no arg must default to 'full'")


# ════════════════════════════════════════════════════════════════════════════
# 4. Combined token-output is smaller than naive sum
# ════════════════════════════════════════════════════════════════════════════
class TestTokenEfficiency(unittest.TestCase):
    """
    cave-mem's combined activation output must be STRICTLY SMALLER than
    the sum of running caveman and a hypothetical memory context separately.
    This validates the deduplication / shared-preamble benefit of integration.
    """

    def _caveman_output_size(self):
        with tempfile.TemporaryDirectory(prefix="caveman-tok-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            result = subprocess.run(
                ["node", "hooks/caveman-activate.js"],
                cwd=CAVEMAN_ROOT,
                env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
                text=True,
                capture_output=True,
            )
            return len(result.stdout)

    def _cave_mem_output_size(self):
        with tempfile.TemporaryDirectory(prefix="cave-mem-tok-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("cave-mem-activate.js", home)
            return len(result.stdout)

    def test_cave_mem_output_is_not_empty(self):
        size = self._cave_mem_output_size()
        self.assertGreater(size, 100,
                           "cave-mem activation output must not be trivially empty")
        print(f"\n[CAVE-MEM] combined activation output: {size} chars")

    def test_combined_output_smaller_than_naive_double(self):
        """
        cave-mem combined output < 2 × caveman-alone output.
        Validates dedup: if we just concatenated both, we'd pay full cost twice.
        """
        caveman_size = self._caveman_output_size()
        cave_mem_size = self._cave_mem_output_size()
        naive_double = caveman_size * 2
        print(f"\n[EFFICIENCY] caveman-only: {caveman_size} chars")
        print(f"[EFFICIENCY] cave-mem combined: {cave_mem_size} chars")
        print(f"[EFFICIENCY] naive double would be: {naive_double} chars")
        print(f"[EFFICIENCY] savings vs naive double: "
              f"{naive_double - cave_mem_size} chars "
              f"({100*(naive_double-cave_mem_size)/naive_double:.1f}%)")
        self.assertLess(cave_mem_size, naive_double,
                        "cave-mem combined output must be < 2× caveman-alone output "
                        "(deduplication must work)")


# ════════════════════════════════════════════════════════════════════════════
# 5. Integration: full lifecycle
# ════════════════════════════════════════════════════════════════════════════
class TestFullLifecycle(unittest.TestCase):

    def test_install_upgrade_adds_cave_mem_flag(self):
        """
        Simulates a home dir that had caveman installed but NOT cave-mem.
        After running cave-mem-activate.js, .cave-mem-active should appear.
        """
        with tempfile.TemporaryDirectory(prefix="cave-mem-upgrade-") as tmp:
            home = Path(tmp)
            claude_dir = home / ".claude"
            claude_dir.mkdir(parents=True)
            # Pre-existing caveman flag (user had caveman before)
            (claude_dir / ".caveman-active").write_text("full")
            (claude_dir / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            _run_hook("cave-mem-activate.js", home)
            self.assertTrue((claude_dir / ".cave-mem-active").exists(),
                            "cave-mem flag must appear after first activation, "
                            "even when .caveman-active already exists")

    def test_mode_change_persists_across_tracker_calls(self):
        """Switching mode via tracker must persist and survive a second call."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-persist-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".cave-mem-active"
            payload_full  = json.dumps({"prompt": "/cave-mem full"})
            payload_other = json.dumps({"prompt": "can you help me debug this?"})

            _run_hook("cave-mem-mode-tracker.js", home, stdin_data=payload_full)
            _run_hook("cave-mem-mode-tracker.js", home, stdin_data=payload_other)

            self.assertTrue(flag.exists(), "flag must persist after unrelated prompt")
            self.assertEqual(flag.read_text().strip(), "full",
                             "mode must stay 'full' after non-mode-change prompt")

    def test_uninstall_removes_flag(self):
        """Stopping cave-mem removes the flag and leaves no stale state."""
        with tempfile.TemporaryDirectory(prefix="cave-mem-uninstall-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".cave-mem-active"
            flag.write_text("full")
            _run_hook(
                "cave-mem-mode-tracker.js",
                home,
                stdin_data=json.dumps({"prompt": "stop cave-mem"}),
            )
            self.assertFalse(flag.exists(), "flag must be gone after 'stop cave-mem'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
