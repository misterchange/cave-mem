#!/usr/bin/env node
/**
 * cave-mem — SessionStart activation hook
 *
 * Combines caveman output-token compression with claude-mem persistent memory.
 * Runs on every session start:
 *
 *   1. Read active compression level from config
 *   2. Write ~/.claude/.cave-mem-active flag (statusline reads this)
 *   3. Load caveman SKILL.md (single source of truth for compression rules)
 *   4. Emit COMBINED context: caveman rules + memory-persistence reminder
 *      — shared preamble deduplication keeps combined output < 2× caveman alone
 *   5. Detect missing statusline config and nudge user to set it up
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { getCompressionLevel, claudeDir } = require('./cave-mem-config');

const flagPath    = path.join(claudeDir, '.cave-mem-active');
const settingsPath = path.join(claudeDir, 'settings.json');

const level = getCompressionLevel();

// ── Off mode: clean up flag and exit silently ────────────────────────────────
if (level === 'off') {
  try { fs.unlinkSync(flagPath); } catch (_) {}
  process.stdout.write('OK');
  process.exit(0);
}

// ── 1. Write runtime flag ────────────────────────────────────────────────────
try {
  fs.mkdirSync(claudeDir, { recursive: true });
  fs.writeFileSync(flagPath, level);
} catch (_) { /* best-effort — don't block session start */ }

// ── 2. Load caveman SKILL.md ─────────────────────────────────────────────────
//
// We read the caveman skill directly rather than duplicating its rules here.
// This ensures cave-mem always stays in sync with upstream caveman changes.
// Resolution order:
//   a) ${CLAUDE_PLUGIN_ROOT}/../caveman/skills/caveman/SKILL.md  (marketplace layout)
//   b) ~/.claude/plugins/marketplaces/JuliusBrussee/skills/caveman/SKILL.md
//   c) Sibling repo: C:/Nitin/Nitins/WikiMan/caveman/skills/caveman/SKILL.md
//   d) Inline fallback (minimal ruleset)

let skillContent = '';
const skillCandidates = [
  path.join(__dirname, '..', '..', 'caveman', 'skills', 'caveman', 'SKILL.md'),
  path.join(os.homedir(), '.claude', 'plugins', 'marketplaces', 'JuliusBrussee', 'skills', 'caveman', 'SKILL.md'),
  path.join('C:', 'Nitin', 'Nitins', 'WikiMan', 'caveman', 'skills', 'caveman', 'SKILL.md'),
];
for (const candidate of skillCandidates) {
  try {
    skillContent = fs.readFileSync(candidate, 'utf8');
    break;
  } catch (_) { /* try next */ }
}

// ── 3. Build compression-rules section from SKILL.md ────────────────────────
function extractCavemanRules(raw, activeLevel) {
  if (!raw) return null;

  // Strip YAML frontmatter
  const body = raw.replace(/^---[\s\S]*?---\s*/, '');

  // Filter intensity table: keep only the active level's row
  const filtered = body.split('\n').reduce((acc, line) => {
    const tableRow = line.match(/^\|\s*\*\*(\S+?)\*\*\s*\|/);
    if (tableRow) {
      if (tableRow[1] === activeLevel) acc.push(line);
      return acc;
    }
    const exampleLine = line.match(/^- (\S+?):\s/);
    if (exampleLine) {
      if (exampleLine[1] === activeLevel) acc.push(line);
      return acc;
    }
    acc.push(line);
    return acc;
  }, []);

  return filtered.join('\n').trim();
}

const cavemanRules = extractCavemanRules(skillContent, level) || (
  // Inline fallback — minimal but functional
  'Respond terse like smart caveman. All technical substance stay. Only fluff die.\n\n' +
  '## Persistence\n\nACTIVE EVERY RESPONSE. No revert after many turns. No filler drift.\n\n' +
  '## Rules\n\n' +
  'Drop: articles, filler (just/really/basically), pleasantries, hedging. ' +
  'Fragments OK. Short synonyms. Technical terms exact. Code blocks unchanged.\n\n' +
  'Pattern: `[thing] [action] [reason]. [next step].`\n\n' +
  'Off: "stop cave-mem" / "normal mode".'
);

// ── 4. Build memory-persistence section ─────────────────────────────────────
//
// cave-mem stores session observations in caveman-compressed format.
// This section tells Claude how to interact with the memory system.
// Intentionally brief — full memory context is injected by claude-mem's
// own hooks if installed; this is the lightweight reminder for standalone use.
const memorySection = `\
## Memory (cave-mem)

Cross-session observations stored compressed. Format same as active caveman level (${level}).

Rules:
- Cite stored facts: prefix with [mem:<id>] when drawing from past sessions
- <private>...</private> tags exclude content from memory storage
- \`/cave-mem search <query>\` — retrieve relevant past observations
- Memory auto-captures: tool results, file edits, key decisions, errors+fixes

Current level: **${level}**. Switch: \`/cave-mem lite|full|ultra\`.`;

// ── 5. Compose final combined output ────────────────────────────────────────
//
// Shared preamble (CAVE-MEM MODE ACTIVE header) replaces the separate
// "CAVEMAN MODE ACTIVE" + "CLAUDE-MEM ACTIVE" headers, saving ~80 chars.
// The rest is deduplicated by merging into a single structured context block.
let output =
  `CAVE-MEM MODE ACTIVE — level: ${level}\n` +
  `(caveman output compression + persistent cross-session memory)\n\n` +
  cavemanRules +
  '\n\n---\n\n' +
  memorySection;

// ── 6. Statusline nudge ──────────────────────────────────────────────────────
try {
  let hasStatusline = false;
  if (fs.existsSync(settingsPath)) {
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    if (settings.statusLine) hasStatusline = true;
  }
  if (!hasStatusline) {
    const isWindows   = process.platform === 'win32';
    const scriptName  = isWindows ? 'cave-mem-statusline.ps1' : 'cave-mem-statusline.sh';
    const scriptPath  = path.join(__dirname, scriptName);
    const command     = isWindows
      ? `powershell -ExecutionPolicy Bypass -File "${scriptPath}"`
      : `bash "${scriptPath}"`;
    const snippet = `"statusLine": { "type": "command", "command": ${JSON.stringify(command)} }`;
    output +=
      '\n\nSTATUSLINE SETUP NEEDED: cave-mem includes a status badge showing active mode ' +
      '(e.g. [CAVE-MEM:FULL]). Not configured yet. ' +
      `To enable, add to ~/.claude/settings.json: ${snippet} ` +
      'Proactively offer to set this up on first interaction.';
  }
} catch (_) { /* silent fail — don't block session start */ }

process.stdout.write(output);
