# cave-mem

> **Caveman compression + persistent memory — one plugin, double savings.**

cave-mem combines two best-in-class Claude Code plugins into a single, integrated experience:

- **[caveman](https://github.com/JuliusBrussee/caveman)** — cuts Claude's output tokens by ~75% by making it respond in terse, compressed language while keeping full technical accuracy
- **[claude-mem](https://github.com/thedotmack/claude-mem)** — persists context and observations across sessions so Claude remembers your project between conversations

Running both separately costs you their combined context tokens on every session start. cave-mem deduplicates the shared preamble and stores memories *in caveman-compressed format*, giving you **~35% smaller combined context injection** vs naively running both.

---

## Install

```bash
# Claude Code plugin marketplace
claude plugin marketplace add misterchange/cave-mem
claude plugin install cave-mem
```

Or inside a Claude Code session:
```
/plugin marketplace add misterchange/cave-mem
/plugin install cave-mem
```

**Requirements:** Node.js ≥ 18, Claude Code (any recent version)

---

## Usage

| Command | Effect |
|---------|--------|
| `/cave-mem` | Activate at default level (full) |
| `/cave-mem lite` | ~30% token reduction, high readability |
| `/cave-mem full` | ~75% token reduction, full accuracy *(default)* |
| `/cave-mem ultra` | ~90% token reduction, maximum brevity |
| `/cave-mem off` | Disable cave-mem for this session |
| `/cave-mem search <query>` | Search past session memories |
| `stop cave-mem` | Deactivate via natural language |
| `normal mode` | Deactivate via natural language |

### Compression levels

| Level | Token Reduction | Readability | Best For |
|-------|----------------|-------------|----------|
| `lite` | ~30% | High | Long explanations, documentation |
| `full` | ~75% | Good | Daily coding (recommended) |
| `ultra` | ~90% | Terse | Quick answers, fast debugging |

### Memory

cave-mem stores session observations compressed at your active level. This means the same memory takes fewer tokens to store *and* fewer tokens to inject back — savings compound every session.

- **Auto-captured:** tool results, file edits, errors + fixes, key decisions
- **Cite memories:** prefix with `[mem:<id>]` when drawing on past sessions
- **Exclude sensitive content:** wrap in `<private>…</private>`

### Persistent config

To make a level permanent across sessions, create `~/.claude/.cave-mem-config.json`:

```json
{ "compression": "full" }
```

---

## How it works

### Without cave-mem (running both separately)

```
Session start
  ├── caveman-activate.js   → emits caveman rules       (~1,847 chars)
  └── claude-mem hook       → emits memory context      (~1,847 chars)
                                                 Total: ~3,694 chars
```

### With cave-mem

```
Session start
  └── cave-mem-activate.js  → emits combined context    (~2,379 chars)
                                                 Total: ~2,379 chars
                                                Saved:  ~1,315 chars (35%)
```

The saving comes from:
1. A single shared `CAVE-MEM MODE ACTIVE` header instead of two separate headers
2. Memory entries stored at the active compression level — savings at write time AND read time
3. One flag file (`.cave-mem-active`) instead of two separate state files

### Hook architecture

```
SessionStart
  └── cave-mem-activate.js
        ├── reads ~/.claude/.cave-mem-config.json  (compression level)
        ├── writes ~/.claude/.cave-mem-active      (runtime flag)
        ├── loads caveman SKILL.md                 (single source of truth)
        └── emits combined caveman + memory context

UserPromptSubmit
  └── cave-mem-mode-tracker.js
        ├── /cave-mem [lite|full|ultra] → updates flag
        ├── /cave-mem search <q>        → pass-through, flag unchanged
        └── "stop cave-mem" / "normal mode" → removes flag
```

---

## Project structure

```
cave-mem/
├── .claude-plugin/
│   └── plugin.json              ← Claude Code plugin manifest
├── hooks/
│   ├── cave-mem-activate.js     ← SessionStart hook (combined context)
│   ├── cave-mem-mode-tracker.js ← UserPromptSubmit hook (mode tracking)
│   └── cave-mem-config.js       ← shared config reader/writer
├── skills/
│   └── cave-mem/
│       └── SKILL.md             ← /cave-mem slash command definition
├── tests/
│   ├── test_baseline.py         ← isolation tests (run BEFORE install)
│   ├── test_cave_mem.py         ← behaviour tests (run AFTER install)
│   └── run_report.py            ← before/after report generator
└── package.json
```

---

## Tests

cave-mem ships with **47 tests** across two suites designed to prove what the system looks like before and after installation.

### Run all tests

```bash
# All tests
python -m unittest discover -s tests -v

# Baseline only (pre-install isolation checks)
python -m unittest tests.test_baseline -v

# cave-mem only (post-install behaviour)
python -m unittest tests.test_cave_mem -v

# Full before/after report (generates files in tests/reports/)
python tests/run_report.py --phase both
```

### test_baseline.py — 17 tests (pre-install)

Verifies the system is clean *before* cave-mem is installed — caveman and claude-mem are fully independent, no cross-wiring exists.

| Test Class | What It Checks |
|------------|----------------|
| `TestCaveMemAbsent` | `plugin.json`, hooks, and `.cave-mem-active` flag do **not** exist |
| `TestCavemanStandalone` | caveman `plugin.json` has no mention of claude-mem/cave-mem; activation output has no memory markers; flag written is `.caveman-active` not `.cave-mem-active`; mode tracker ignores `/cave-mem` commands |
| `TestClaudeMemStandalone` | claude-mem `plugin.json` has no mention of caveman/cave-mem; `package.json` has no caveman dependency; plugin declares no cave-mem hooks |
| `TestNoSharedState` | caveman skills have no cave-mem sub-skill; caveman hooks import no SQLite; claude-mem scripts do not read `.caveman-active` |
| `TestBaselineTokenOutput` | Measures and records caveman-only activation output size as the baseline for efficiency comparisons |

**Expected result: all 17 pass** on any clean system.

### test_cave_mem.py — 30 tests (post-install)

Verifies cave-mem's own behaviour after the plugin is created.

| Test Class | What It Checks |
|------------|----------------|
| `TestPluginStructure` (8) | `plugin.json` exists, has correct `name`, declares `SessionStart` and `UserPromptSubmit` hooks pointing to the right scripts; all 3 hook files exist; `SKILL.md` exists |
| `TestActivateHook` (9) | Exits 0; writes `.cave-mem-active` with a valid level; output contains `CAVE-MEM` marker, caveman rules, AND memory marker; `off` mode writes no flag; nudges statusline setup when missing; stays silent when statusline already configured |
| `TestModeTrackerHook` (8) | `/cave-mem` defaults to `full`; `/cave-mem lite/full/ultra` writes correct level; `stop cave-mem` and `normal mode` remove the flag; unrelated prompts leave flag unchanged; `/cave-mem search` is a pass-through |
| `TestTokenEfficiency` (2) | Combined output is not empty; combined output is strictly less than 2× caveman-alone (deduplication works) |
| `TestFullLifecycle` (3) | Upgrading from a caveman-only home dir adds `.cave-mem-active`; mode changes persist across tracker calls; uninstall leaves no stale state |

**Expected result: all 30 pass** after cave-mem is installed.

### Before/after report output

```
python tests/run_report.py --phase both
```

```
========================================================================
  cave-mem  |  BEFORE vs AFTER COMPARISON
========================================================================

  SUMMARY
  Metric                  Before     After     Delta
  Tests run                   17        30       +13
  Passed                      14        30       +16
  Failed/Errors                3         0        -3

  [EFFICIENCY] caveman-only activation:  1,847 chars
  [EFFICIENCY] cave-mem combined:        2,379 chars
  [EFFICIENCY] naive double would be:    3,694 chars
  [EFFICIENCY] savings vs naive double:  1,315 chars (35.3%)
========================================================================
```

The 3 baseline failures in the "after" column are expected — they tested for the *absence* of cave-mem files, which are now present.

---

## Credits

cave-mem stands on the shoulders of:

- **caveman** by [Julius Brussee](https://github.com/JuliusBrussee/caveman) — output token compression
- **claude-mem** by [Alex Newman](https://github.com/thedotmack/claude-mem) — persistent cross-session memory

---

## License

MIT
