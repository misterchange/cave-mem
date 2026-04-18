#!/usr/bin/env node
/**
 * stoneage — SessionStart activation hook
 *
 * 1. Read active compression level from config
 * 2. Write ~/.claude/.stoneage-active flag (statusline reads this)
 * 3. Load stoneage SKILL.md (single source of truth for compression rules)
 * 4. Load last 200 memories from SQLite → inject as context
 * 5. Emit COMBINED context: stoneage rules + memory section
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { getCompressionLevel, claudeDir } = require('./stoneage-config');
const { openDB, loadRecent } = require('./stoneage-db');

const flagPath     = path.join(claudeDir, '.stoneage-active');
const settingsPath = path.join(claudeDir, 'settings.json');
const level        = getCompressionLevel();

// ── Off mode ──────────────────────────────────────────────────────────────────
if (level === 'off') {
  try { fs.unlinkSync(flagPath); } catch (_) {}
  process.stdout.write('OK');
  process.exit(0);
}

// ── Write runtime flag ────────────────────────────────────────────────────────
try {
  fs.mkdirSync(claudeDir, { recursive: true });
  fs.writeFileSync(flagPath, level);
} catch (_) {}

// ── Load stoneage SKILL.md ─────────────────────────────────────────────────────
let skillContent = '';
const skillCandidates = [
  path.join(__dirname, '..', '..', 'stoneage', 'skills', 'stoneage', 'SKILL.md'),
  path.join(os.homedir(), '.claude', 'plugins', 'marketplaces', 'JuliusBrussee', 'skills', 'stoneage', 'SKILL.md'),
  path.join('C:', 'Nitin', 'Nitins', 'WikiMan', 'stoneage', 'skills', 'stoneage', 'SKILL.md'),
];
for (const candidate of skillCandidates) {
  try { skillContent = fs.readFileSync(candidate, 'utf8'); break; } catch (_) {}
}

function extractStoneageRules(raw, activeLevel) {
  if (!raw) return null;
  const body = raw.replace(/^---[\s\S]*?---\s*/, '');
  const filtered = body.split('\n').reduce((acc, line) => {
    const tableRow = line.match(/^\|\s*\*\*(\S+?)\*\*\s*\|/);
    if (tableRow) { if (tableRow[1] === activeLevel) acc.push(line); return acc; }
    const exampleLine = line.match(/^- (\S+?):\s/);
    if (exampleLine) { if (exampleLine[1] === activeLevel) acc.push(line); return acc; }
    acc.push(line);
    return acc;
  }, []);
  return filtered.join('\n').trim();
}

const stoneageRules = extractStoneageRules(skillContent, level) || (
  'Respond terse like smart stoneage. All technical substance stay. Only fluff die.\n\n' +
  '## Persistence\n\nACTIVE EVERY RESPONSE. No revert. Off: "stop stoneage" / "normal mode".\n\n' +
  '## Rules\n\nDrop: articles, filler, pleasantries, hedging. Fragments OK. Short synonyms. Code blocks unchanged.\n\n' +
  'Pattern: `[thing] [action] [reason]. [next step].`'
);

// ── Load recent memories from SQLite ─────────────────────────────────────────
let recentMemories = [];
try {
  const db = openDB();
  recentMemories = loadRecent(db, 200);
  db.close();
} catch (_) {}

function formatMemoryContext(entries) {
  if (entries.length === 0) return null;
  const lines = entries.slice(-30).map(e =>  // show last 30 in context
    `[${e.id}] ${e.ts.slice(0,16)} | ${e.tool} | ${e.summary}`
  );
  return `## Recent memories (${entries.length} stored, showing last ${lines.length})\n\n` +
    lines.join('\n');
}

const memCtx = formatMemoryContext(recentMemories);

// ── Memory section ────────────────────────────────────────────────────────────
const memorySection = `\
## Memory (stoneage)

Cross-session observations stored in SQLite. Format: active stoneage level (${level}).

Rules:
- Cite stored facts: prefix with [mem:<id>] when drawing from past sessions
- <private>...</private> tags exclude content from memory storage
- \`/stoneage search <query>\` — full-text search past observations
- Memory auto-captures: tool results, file edits, key decisions, errors+fixes

Current level: **${level}**. Switch: \`/stoneage lite|full|ultra\`.` +
(memCtx ? '\n\n' + memCtx : '');

// ── Compose output ────────────────────────────────────────────────────────────
let output =
  `STONEAGE MODE ACTIVE — level: ${level}\n` +
  `(stoneage output compression + persistent cross-session memory)\n\n` +
  stoneageRules +
  '\n\n---\n\n' +
  memorySection;

// ── Statusline nudge ──────────────────────────────────────────────────────────
try {
  let hasStatusline = false;
  if (fs.existsSync(settingsPath)) {
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    if (settings.statusLine) hasStatusline = true;
  }
  if (!hasStatusline) {
    const isWindows  = process.platform === 'win32';
    const scriptName = isWindows ? 'stoneage-statusline.ps1' : 'stoneage-statusline.sh';
    const scriptPath = path.join(__dirname, scriptName);
    const command    = isWindows
      ? `powershell -ExecutionPolicy Bypass -File "${scriptPath}"`
      : `bash "${scriptPath}"`;
    const snippet = `"statusLine": { "type": "command", "command": ${JSON.stringify(command)} }`;
    output += '\n\nSTATUSLINE SETUP NEEDED: add to ~/.claude/settings.json: ' + snippet;
  }
} catch (_) {}

process.stdout.write(output);
