"""
stoneage post-install tests — run AFTER stoneage is created and activated.

These verify the "after" state of the system:
  - plugin.json has correct combined structure
  - hooks exist and behave correctly
  - activation writes .stoneage-active flag (NOT the separate .stoneage-active)
  - combined activation output < naive sum of stoneage + claude-mem outputs
  - /stoneage commands are tracked by mode-tracker
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
STONEAGE_ROOT    = WIKIMAN_ROOT / "stoneage"
CLAUDE_MEM_ROOT = WIKIMAN_ROOT / "claude-mem"


def _run_hook(hook_filename, home, stdin_data=None, env_extra=None):
    """Run a stoneage hook script and return the CompletedProcess."""
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
        self.assertTrue(plugin_json.exists(), "stoneage .claude-plugin/plugin.json must exist")

    def test_plugin_json_has_required_fields(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        self.assertEqual(data["name"], "stoneage",
                         "plugin name must be 'stoneage'")
        self.assertIn("description", data)
        self.assertIn("hooks", data)

    def test_plugin_json_declares_session_start_hook(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        self.assertIn("SessionStart", data["hooks"],
                      "stoneage plugin must declare a SessionStart hook")

    def test_plugin_json_declares_user_prompt_submit_hook(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        self.assertIn("UserPromptSubmit", data["hooks"],
                      "stoneage plugin must declare a UserPromptSubmit hook")

    def test_plugin_json_references_cave_mem_activate(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text()
        self.assertIn("stoneage-activate.js", raw,
                      "SessionStart hook must point to stoneage-activate.js")

    def test_plugin_json_references_cave_mem_mode_tracker(self):
        plugin_json = CAVE_MEM_ROOT / ".claude-plugin" / "plugin.json"
        raw = plugin_json.read_text()
        self.assertIn("stoneage-mode-tracker.js", raw,
                      "UserPromptSubmit hook must point to stoneage-mode-tracker.js")

    def test_hooks_directory_has_all_three_files(self):
        hooks_dir = CAVE_MEM_ROOT / "hooks"
        required = [
            "stoneage-config.js",
            "stoneage-activate.js",
            "stoneage-mode-tracker.js",
        ]
        for name in required:
            self.assertTrue((hooks_dir / name).exists(),
                            f"hooks/{name} must exist")

    def test_skill_md_exists(self):
        skill = CAVE_MEM_ROOT / "skills" / "stoneage" / "SKILL.md"
        self.assertTrue(skill.exists(), "skills/stoneage/SKILL.md must exist")


# ════════════════════════════════════════════════════════════════════════════
# 2. stoneage-activate.js behaviour
# ════════════════════════════════════════════════════════════════════════════
class TestActivateHook(unittest.TestCase):

    def test_activate_exits_zero(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-activate-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("stoneage-activate.js", home)
            self.assertEqual(result.returncode, 0,
                             f"activate hook must exit 0, stderr: {result.stderr}")

    def test_activate_writes_cave_mem_active_flag(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-flag-") as tmp:
            home = _fresh_home_with_settings(tmp)
            _run_hook("stoneage-activate.js", home)
            flag = home / ".claude" / ".stoneage-active"
            self.assertTrue(flag.exists(), ".stoneage-active flag must be written")

    def test_activate_flag_contains_compression_level(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-level-") as tmp:
            home = _fresh_home_with_settings(tmp)
            _run_hook("stoneage-activate.js", home)
            flag = home / ".claude" / ".stoneage-active"
            level = flag.read_text().strip()
            self.assertIn(level, {"lite", "full", "ultra", "off"},
                          f"flag must contain a valid compression level, got: '{level}'")

    def test_activate_output_contains_cave_mem_marker(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-out-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("stoneage-activate.js", home)
            self.assertIn("STONEAGE", result.stdout.upper(),
                          "activation output must contain STONEAGE header")

    def test_activate_output_contains_stoneage_rules(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-rules-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("stoneage-activate.js", home)
            # Stoneage rules contain key phrases about brevity
            output_lower = result.stdout.lower()
            has_stoneage = (
                "stoneage" in output_lower
                or "terse" in output_lower
                or "compress" in output_lower
            )
            self.assertTrue(has_stoneage,
                            "activation output must embed stoneage compression rules")

    def test_activate_output_contains_memory_marker(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-mem-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("stoneage-activate.js", home)
            output_lower = result.stdout.lower()
            has_mem = (
                "memory" in output_lower
                or "persist" in output_lower
                or "session" in output_lower
            )
            self.assertTrue(has_mem,
                            "activation output must reference memory persistence")

    def test_activate_off_mode_writes_no_flag(self):
        """When compression is set to 'off', no .stoneage-active flag is written."""
        with tempfile.TemporaryDirectory(prefix="stoneage-off-") as tmp:
            home = _fresh_home_with_settings(tmp)
            config = home / ".claude" / ".stoneage-config.json"
            config.write_text(json.dumps({"compression": "off"}))
            _run_hook("stoneage-activate.js", home)
            flag = home / ".claude" / ".stoneage-active"
            self.assertFalse(flag.exists(),
                             "off mode must NOT write .stoneage-active")

    def test_activate_nudges_statusline_when_missing(self):
        """If settings.json lacks statusLine, activate must emit a setup nudge."""
        with tempfile.TemporaryDirectory(prefix="stoneage-status-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text("{}\n")
            result = _run_hook("stoneage-activate.js", home)
            self.assertIn("STATUSLINE", result.stdout.upper(),
                          "activate must nudge about statusline setup when it is missing")

    def test_activate_does_not_nudge_when_statusline_configured(self):
        """If settings.json already has statusLine, no nudge should appear."""
        with tempfile.TemporaryDirectory(prefix="stoneage-no-nudge-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("stoneage-activate.js", home)
            self.assertNotIn("STATUSLINE SETUP NEEDED", result.stdout,
                             "activate must NOT nudge when statusLine is already configured")


# ════════════════════════════════════════════════════════════════════════════
# 3. stoneage-mode-tracker.js behaviour
# ════════════════════════════════════════════════════════════════════════════
class TestModeTrackerHook(unittest.TestCase):

    def _track(self, home, prompt):
        return _run_hook(
            "stoneage-mode-tracker.js",
            home,
            stdin_data=json.dumps({"prompt": prompt}),
        )

    def test_tracker_exits_zero_on_normal_prompt(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-tracker-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = self._track(home, "hello world")
            self.assertEqual(result.returncode, 0)

    def test_tracker_cave_mem_full_sets_flag(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-full-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/stoneage full")
            flag = home / ".claude" / ".stoneage-active"
            self.assertTrue(flag.exists(), "/stoneage full must create flag")
            self.assertEqual(flag.read_text().strip(), "full")

    def test_tracker_cave_mem_lite_sets_flag(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-lite-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/stoneage lite")
            flag = home / ".claude" / ".stoneage-active"
            self.assertTrue(flag.exists())
            self.assertEqual(flag.read_text().strip(), "lite")

    def test_tracker_cave_mem_ultra_sets_flag(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-ultra-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/stoneage ultra")
            flag = home / ".claude" / ".stoneage-active"
            self.assertTrue(flag.exists())
            self.assertEqual(flag.read_text().strip(), "ultra")

    def test_tracker_stop_cave_mem_removes_flag(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-stop-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".stoneage-active"
            flag.write_text("full")
            self._track(home, "stop stoneage")
            self.assertFalse(flag.exists(), "stop stoneage must remove flag")

    def test_tracker_normal_mode_removes_flag(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-normal-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".stoneage-active"
            flag.write_text("full")
            self._track(home, "normal mode")
            self.assertFalse(flag.exists(), "'normal mode' must remove stoneage flag")

    def test_tracker_ignores_unrelated_prompt(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-unrelated-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".stoneage-active"
            flag.write_text("full")  # pre-existing
            self._track(home, "please fix the bug in my code")
            # Flag must be unchanged
            self.assertTrue(flag.exists(), "unrelated prompt must not remove flag")
            self.assertEqual(flag.read_text().strip(), "full")

    def test_tracker_cave_mem_default_sets_full(self):
        """/stoneage with no argument defaults to 'full' compression."""
        with tempfile.TemporaryDirectory(prefix="stoneage-default-") as tmp:
            home = _fresh_home_with_settings(tmp)
            self._track(home, "/stoneage")
            flag = home / ".claude" / ".stoneage-active"
            self.assertTrue(flag.exists())
            self.assertEqual(flag.read_text().strip(), "full",
                             "/stoneage with no arg must default to 'full'")


# ════════════════════════════════════════════════════════════════════════════
# 4. Combined token-output is smaller than naive sum
# ════════════════════════════════════════════════════════════════════════════
class TestTokenEfficiency(unittest.TestCase):
    """
    stoneage's combined activation output must be STRICTLY SMALLER than
    the sum of running stoneage and a hypothetical memory context separately.
    This validates the deduplication / shared-preamble benefit of integration.
    """

    def _stoneage_output_size(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-tok-") as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            result = subprocess.run(
                ["node", "hooks/stoneage-activate.js"],
                cwd=STONEAGE_ROOT,
                env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
                text=True,
                capture_output=True,
            )
            return len(result.stdout)

    def _cave_mem_output_size(self):
        with tempfile.TemporaryDirectory(prefix="stoneage-tok-") as tmp:
            home = _fresh_home_with_settings(tmp)
            result = _run_hook("stoneage-activate.js", home)
            return len(result.stdout)

    def test_cave_mem_output_is_not_empty(self):
        size = self._cave_mem_output_size()
        self.assertGreater(size, 100,
                           "stoneage activation output must not be trivially empty")
        print(f"\n[STONEAGE] combined activation output: {size} chars")

    def test_combined_output_smaller_than_naive_double(self):
        """
        stoneage combined output < 2 × stoneage-alone output.
        Validates dedup: if we just concatenated both, we'd pay full cost twice.
        """
        stoneage_size = self._stoneage_output_size()
        cave_mem_size = self._cave_mem_output_size()
        naive_double = stoneage_size * 2
        print(f"\n[EFFICIENCY] stoneage-only: {stoneage_size} chars")
        print(f"[EFFICIENCY] stoneage combined: {cave_mem_size} chars")
        print(f"[EFFICIENCY] naive double would be: {naive_double} chars")
        print(f"[EFFICIENCY] savings vs naive double: "
              f"{naive_double - cave_mem_size} chars "
              f"({100*(naive_double-cave_mem_size)/naive_double:.1f}%)")
        self.assertLess(cave_mem_size, naive_double,
                        "stoneage combined output must be < 2× stoneage-alone output "
                        "(deduplication must work)")


# ════════════════════════════════════════════════════════════════════════════
# 5. Integration: full lifecycle
# ════════════════════════════════════════════════════════════════════════════
class TestFullLifecycle(unittest.TestCase):

    def test_install_upgrade_adds_cave_mem_flag(self):
        """
        Simulates a home dir that had stoneage installed but NOT stoneage.
        After running stoneage-activate.js, .stoneage-active should appear.
        """
        with tempfile.TemporaryDirectory(prefix="stoneage-upgrade-") as tmp:
            home = Path(tmp)
            claude_dir = home / ".claude"
            claude_dir.mkdir(parents=True)
            # Pre-existing stoneage flag (user had stoneage before)
            (claude_dir / ".stoneage-active").write_text("full")
            (claude_dir / "settings.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": "echo ok"}})
            )
            _run_hook("stoneage-activate.js", home)
            self.assertTrue((claude_dir / ".stoneage-active").exists(),
                            "stoneage flag must appear after first activation, "
                            "even when .stoneage-active already exists")

    def test_mode_change_persists_across_tracker_calls(self):
        """Switching mode via tracker must persist and survive a second call."""
        with tempfile.TemporaryDirectory(prefix="stoneage-persist-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".stoneage-active"
            payload_full  = json.dumps({"prompt": "/stoneage full"})
            payload_other = json.dumps({"prompt": "can you help me debug this?"})

            _run_hook("stoneage-mode-tracker.js", home, stdin_data=payload_full)
            _run_hook("stoneage-mode-tracker.js", home, stdin_data=payload_other)

            self.assertTrue(flag.exists(), "flag must persist after unrelated prompt")
            self.assertEqual(flag.read_text().strip(), "full",
                             "mode must stay 'full' after non-mode-change prompt")

    def test_uninstall_removes_flag(self):
        """Stopping stoneage removes the flag and leaves no stale state."""
        with tempfile.TemporaryDirectory(prefix="stoneage-uninstall-") as tmp:
            home = _fresh_home_with_settings(tmp)
            flag = home / ".claude" / ".stoneage-active"
            flag.write_text("full")
            _run_hook(
                "stoneage-mode-tracker.js",
                home,
                stdin_data=json.dumps({"prompt": "stop stoneage"}),
            )
            self.assertFalse(flag.exists(), "flag must be gone after 'stop stoneage'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
