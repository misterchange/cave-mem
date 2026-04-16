#!/usr/bin/env node
/**
 * cave-mem — SessionStart activation hook
 *
 * 1. Read active compression level from config
 * 2. Write ~/.claude/.cave-mem-active flag (statusline reads this)
 * 3. Load caveman SKILL.md (single source of truth for compression rules)
 * 4. Load last 200 memories from SQLite → inject as context
 * 5. Emit COMBINED context: caveman rules + memory section
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { getCompressionLevel, claudeDir } = require('./cave-mem-config');
const { openDB, loadRecent } = require('./cave-mem-db');

const flagPath     = path.join(claudeDir, '.cave-mem-active');
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

// ── Load caveman SKILL.md ─────────────────────────────────────────────────────
let skillContent = '';
const skillCandidates = [
  path.join(__dirname, '..', '..', 'caveman', 'skills', 'caveman', 'SKILL.md'),
  path.join(os.homedir(), '.claude', 'plugins', 'marketplaces', 'JuliusBrussee', 'skills', 'caveman', 'SKILL.md'),
  path.join('C:', 'Nitin', 'Nitins', 'WikiMan', 'caveman', 'skills', 'caveman', 'SKILL.md'),
];
for (const candidate of skillCandidates) {
  try { skillContent = fs.readFileSync(candidate, 'utf8'); break; } catch (_) {}
}

function extractCavemanRules(raw, activeLevel) {
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

const cavemanRules = extractCavemanRules(skillContent, level) || (
  'Respond terse like smart caveman. All technical substance stay. Only fluff die.\n\n' +
  '## Persistence\n\nACTIVE EVERY RESPONSE. No revert. Off: "stop cave-mem" / "normal mode".\n\n' +
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
## Memory (cave-mem)

Cross-session observations stored in SQLite. Format: active caveman level (${level}).

Rules:
- Cite stored facts: prefix with [mem:<id>] when drawing from past sessions
- <private>...</private> tags exclude content from memory storage
- \`/cave-mem search <query>\` — full-text search past observations
- Memory auto-captures: tool results, file edits, key decisions, errors+fixes

Current level: **${level}**. Switch: \`/cave-mem lite|full|ultra\`.` +
(memCtx ? '\n\n' + memCtx : '');

// ── Compose output ────────────────────────────────────────────────────────────
let output =
  `CAVE-MEM MODE ACTIVE — level: ${level}\n` +
  `(caveman output compression + persistent cross-session memory)\n\n` +
  cavemanRules +
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
    const scriptName = isWindows ? 'cave-mem-statusline.ps1' : 'cave-mem-statusline.sh';
    const scriptPath = path.join(__dirname, scriptName);
    const command    = isWindows
      ? `powershell -ExecutionPolicy Bypass -File "${scriptPath}"`
      : `bash "${scriptPath}"`;
    const snippet = `"statusLine": { "type": "command", "command": ${JSON.stringify(command)} }`;
    output += '\n\nSTATUSLINE SETUP NEEDED: add to ~/.claude/settings.json: ' + snippet;
  }
} catch (_) {}

process.stdout.write(output);
