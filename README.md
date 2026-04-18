# stoneage

> **Stoneage compression + persistent memory — one plugin, double savings.**

stoneage combines two best-in-class Claude Code plugins into a single, integrated experience:

- **[stoneage](https://github.com/JuliusBrussee/stoneage)** — cuts Claude's output tokens by ~75% by making it respond in terse, compressed language while keeping full technical accuracy
- **[claude-mem](https://github.com/thedotmack/claude-mem)** — persists context and observations across sessions so Claude remembers your project between conversations

Running both separately costs you their combined context tokens on every session start. stoneage deduplicates the shared preamble and stores memories *in stoneage-compressed format*, giving you **~35% smaller combined context injection** vs naively running both.

**v1.2.0** — Memory storage upgraded from JSONL to **SQLite** (Node 22 built-in `node:sqlite`, zero npm deps). Brings full-text search (FTS5), per-session deletion, indexed queries. A live real-time viewer shows every captured memory with its per-entry token reduction.

---

## Install

```bash
# Claude Code plugin marketplace
claude plugin marketplace add misterchange/stoneage
claude plugin install stoneage
```

Or inside a Claude Code session:
```
/plugin marketplace add misterchange/stoneage
/plugin install stoneage
```

**Requirements:** Node.js **≥ 22** (for built-in `node:sqlite`), Claude Code (any recent version). Zero npm dependencies.

---

## Usage

| Command | Effect |
|---------|--------|
| `/stoneage` | Activate at default level (full) |
| `/stoneage lite` | ~30% token reduction, high readability |
| `/stoneage full` | ~75% token reduction, full accuracy *(default)* |
| `/stoneage ultra` | ~90% token reduction, maximum brevity |
| `/stoneage off` | Disable stoneage for this session |
| `/stoneage search <query>` | Search past session memories |
| `stop stoneage` | Deactivate via natural language |
| `normal mode` | Deactivate via natural language |

### Compression levels

| Level | Token Reduction | Readability | Best For |
|-------|----------------|-------------|----------|
| `lite` | ~30% | High | Long explanations, documentation |
| `full` | ~75% | Good | Daily coding (recommended) |
| `ultra` | ~90% | Terse | Quick answers, fast debugging |

### Memory

stoneage stores session observations compressed at your active level in a **SQLite** database at `~/.claude/stoneage-memory.db`. The same memory takes fewer tokens to store *and* fewer tokens to inject back — savings compound every session.

- **Auto-captured:** tool results, file edits, errors + fixes, key decisions
- **Cite memories:** prefix with `[mem:<id>]` when drawing on past sessions
- **Exclude sensitive content:** wrap in `<private>…</private>`
- **Full-text search:** `/stoneage search <query>` hits an FTS5 index across every stored entry
- **Per-session delete:** remove any session's entries from the live viewer (or `POST /delete-session?id=<sid>`)
- **Storage footprint:** ~300 bytes per entry. 10,000 entries ≈ **3 MB**. No cap.

### Live viewer

```bash
npm run viewer
# → http://localhost:37778
```

- Real-time SSE stream, newest sessions at the top
- Per-session reduction badge (`verbose → stored | % saved`)
- Per-entry token reduction column (before strikethrough → after → −XX%)
- Always-visible **Delete session** button per session
- Sidebar: tool breakdown, storage panel (DB path, size, engine)
- Auto-migrates any pre-existing `stoneage-memory.jsonl` to SQLite on first boot

### Persistent config

To make a level permanent across sessions, create `~/.claude/.stoneage-config.json`:

```json
{ "compression": "full" }
```

---

## How it works

### Without stoneage (running both separately)

```
Session start
  ├── stoneage-activate.js   → emits stoneage rules       (~1,847 chars)
  └── claude-mem hook       → emits memory context      (~1,847 chars)
                                                 Total: ~3,694 chars
```

### With stoneage

```
Session start
  └── stoneage-activate.js  → emits combined context    (~2,379 chars)
                                                 Total: ~2,379 chars
                                                Saved:  ~1,315 chars (35%)
```

The saving comes from:
1. A single shared `STONEAGE MODE ACTIVE` header instead of two separate headers
2. Memory entries stored at the active compression level — savings at write time AND read time
3. One flag file (`.stoneage-active`) instead of two separate state files

### Hook architecture

```
SessionStart
  └── stoneage-activate.js
        ├── reads ~/.claude/.stoneage-config.json  (compression level)
        ├── writes ~/.claude/.stoneage-active      (runtime flag)
        ├── loads stoneage SKILL.md                 (single source of truth)
        ├── loads last 200 memories from SQLite    (context injection)
        └── emits combined stoneage + memory context

UserPromptSubmit
  └── stoneage-mode-tracker.js
        ├── /stoneage [lite|full|ultra] → updates flag
        ├── /stoneage search <q>        → SQLite FTS5 lookup, injects results
        └── "stop stoneage" / "normal mode" → removes flag

PostToolUse  (async, non-blocking)
  └── stoneage-observer.js
        ├── compress(tool_result, active_level)
        └── INSERT INTO memories (SQLite)
```

### SQLite schema

```sql
memories      -- id, ts, level, tool, summary, content,
              -- verbose_len, stored_len, tokens_saved, session_id, cwd
memories_fts  -- virtual FTS5 table over (summary, content)
idx_ts        -- timestamp index (fast poll queries)
idx_session   -- session_id index (fast delete-session)
idx_tool      -- tool index (sidebar breakdown)
```

### Viewer data flow

```
tool fires → PostToolUse hook → compress → INSERT SQLite
                                              │
                                              ▼
                       viewer polls every 500ms (SELECT WHERE ts > lastTs)
                                              │
                                              ▼
                             SSE broadcast → browser UI
```

---

## Project structure

```
stoneage/
├── .claude-plugin/
│   └── plugin.json              ← Claude Code plugin manifest
├── hooks/
│   ├── stoneage-activate.js     ← SessionStart hook (combined context)
│   ├── stoneage-mode-tracker.js ← UserPromptSubmit hook (+ FTS search)
│   ├── stoneage-observer.js     ← PostToolUse hook (INSERT into SQLite)
│   ├── stoneage-config.js       ← shared config reader/writer
│   ├── stoneage-db.js           ← shared SQLite open/schema/CRUD/FTS
│   └── stoneage-statusline.ps1  ← reads flag → outputs [STONEAGE:FULL] badge
├── viewer/
│   ├── server.js                ← HTTP + SSE server, polls SQLite
│   └── public/index.html        ← dark UI, real-time, per-entry reduction
├── skills/
│   └── stoneage/SKILL.md        ← /stoneage slash command definition
├── tests/
│   ├── test_baseline.py         ← isolation tests (run BEFORE install)
│   ├── test_cave_mem.py         ← behaviour tests (run AFTER install)
│   ├── test_all_scenarios.py    ← 4-scenario comparison
│   ├── test_token_reduction.py  ← real-response token savings proof
│   └── run_report.py            ← before/after report generator
└── package.json
```

### Runtime files (in `~/.claude/`)

| File | Purpose |
|------|---------|
| `.stoneage-active` | runtime flag (contains active compression level) |
| `.stoneage-config.json` | optional persistent level override |
| `stoneage-memory.db` | SQLite database (memories + FTS index) |
| `stoneage-memory.jsonl.bak` | one-time backup created during JSONL → SQLite migration |

---

## Tests

stoneage ships with **47 tests** across two suites designed to prove what the system looks like before and after installation.

### Run all tests

```bash
# All tests
python -m unittest discover -s tests -v

# Baseline only (pre-install isolation checks)
python -m unittest tests.test_baseline -v

# stoneage only (post-install behaviour)
python -m unittest tests.test_cave_mem -v

# Full before/after report (generates files in tests/reports/)
python tests/run_report.py --phase both
```

### test_baseline.py — 17 tests (pre-install)

Verifies the system is clean *before* stoneage is installed — stoneage and claude-mem are fully independent, no cross-wiring exists.

| Test Class | What It Checks |
|------------|----------------|
| `TestStoneageAbsent` | `plugin.json`, hooks, and `.stoneage-active` flag do **not** exist |
| `TestStoneageStandalone` | stoneage `plugin.json` has no mention of claude-mem/stoneage; activation output has no memory markers; flag written is `.stoneage-active` not `.stoneage-active`; mode tracker ignores `/stoneage` commands |
| `TestClaudeMemStandalone` | claude-mem `plugin.json` has no mention of stoneage/stoneage; `package.json` has no stoneage dependency; plugin declares no stoneage hooks |
| `TestNoSharedState` | stoneage skills have no stoneage sub-skill; stoneage hooks import no SQLite; claude-mem scripts do not read `.stoneage-active` |
| `TestBaselineTokenOutput` | Measures and records stoneage-only activation output size as the baseline for efficiency comparisons |

**Expected result: all 17 pass** on any clean system.

### test_cave_mem.py — 30 tests (post-install)

Verifies stoneage's own behaviour after the plugin is created.

| Test Class | What It Checks |
|------------|----------------|
| `TestPluginStructure` (8) | `plugin.json` exists, has correct `name`, declares `SessionStart` and `UserPromptSubmit` hooks pointing to the right scripts; all 3 hook files exist; `SKILL.md` exists |
| `TestActivateHook` (9) | Exits 0; writes `.stoneage-active` with a valid level; output contains `STONEAGE` marker, stoneage rules, AND memory marker; `off` mode writes no flag; nudges statusline setup when missing; stays silent when statusline already configured |
| `TestModeTrackerHook` (8) | `/stoneage` defaults to `full`; `/stoneage lite/full/ultra` writes correct level; `stop stoneage` and `normal mode` remove the flag; unrelated prompts leave flag unchanged; `/stoneage search` is a pass-through |
| `TestTokenEfficiency` (2) | Combined output is not empty; combined output is strictly less than 2× stoneage-alone (deduplication works) |
| `TestFullLifecycle` (3) | Upgrading from a stoneage-only home dir adds `.stoneage-active`; mode changes persist across tracker calls; uninstall leaves no stale state |

**Expected result: all 30 pass** after stoneage is installed.

### Before/after report output

```
python tests/run_report.py --phase both
```

```
========================================================================
  stoneage  |  BEFORE vs AFTER COMPARISON
========================================================================

  SUMMARY
  Metric                  Before     After     Delta
  Tests run                   17        30       +13
  Passed                      14        30       +16
  Failed/Errors                3         0        -3

  [EFFICIENCY] stoneage-only activation:  1,847 chars
  [EFFICIENCY] stoneage combined:        2,379 chars
  [EFFICIENCY] naive double would be:    3,694 chars
  [EFFICIENCY] savings vs naive double:  1,315 chars (35.3%)
========================================================================
```

The 3 baseline failures in the "after" column are expected — they tested for the *absence* of stoneage files, which are now present.

---

## Credits

stoneage stands on the shoulders of:

- **stoneage** by [Julius Brussee](https://github.com/JuliusBrussee/stoneage) — output token compression
- **claude-mem** by [Alex Newman](https://github.com/thedotmack/claude-mem) — persistent cross-session memory

---

## License

MIT
