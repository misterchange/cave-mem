#!/usr/bin/env node
/**
 * stoneage — PostToolUse observer hook
 *
 * Fires after every tool call. Captures the tool result, compresses it
 * to the active stoneage level, and stores in SQLite.
 *
 * DB:     ~/.claude/stoneage-memory.db
 * Viewer: node C:/Nitin/Nitins/stoneage/viewer/server.js
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const { getCompressionLevel, claudeDir } = require('./stoneage-config');
const { openDB, insertEntry } = require('./stoneage-db');
const { writeAllHandoffs }    = require('./stoneage-handoff');

const flagPath = path.join(claudeDir, '.stoneage-active');

// Only run if stoneage is active
try {
  if (!fs.existsSync(flagPath)) process.exit(0);
} catch (_) { process.exit(0); }

const level = getCompressionLevel();

// ── Compression ───────────────────────────────────────────────────────────────
function compress(text, lvl) {
  if (!text || typeof text !== 'string') return String(text || '');
  const maxLen = { lite: 800, full: 400, ultra: 180 }[lvl] || 400;
  let out = text.trim();

  if (lvl === 'lite') {
    out = out
      .replace(/\b(just|really|basically|actually|simply|very|quite)\b/gi, '')
      .replace(/\b(I'd be happy to|Sure!|Of course|Certainly)\b/gi, '')
      .replace(/\s{2,}/g, ' ').trim();

  } else if (lvl === 'full') {
    out = out
      .replace(/\b(a|an|the)\s+/gi, '')
      .replace(/\b(just|really|basically|actually|simply|very|quite|I'd be happy to|Sure!|Of course|Certainly|Please note that|It's worth noting that|It is important to)\b[,\s]*/gi, '')
      .replace(/\b(successfully|correctly|properly|currently)\b/gi, '')
      .replace(/\s{2,}/g, ' ').trim();

  } else if (lvl === 'ultra') {
    const firstSentence = out.split(/[.!?]/)[0];
    out = firstSentence
      .replace(/\b(a|an|the|is|are|was|were|be|been|being)\b/gi, '')
      .replace(/\s{2,}/g, ' ').trim();
  }

  if (out.length > maxLen) out = out.slice(0, maxLen - 3) + '...';
  return out;
}

function tokens(text) { return Math.ceil((text || '').length / 4); }

// ── Read stdin ────────────────────────────────────────────────────────────────
let raw = '';
process.stdin.on('data', c => { raw += c; });
process.stdin.on('end', () => {
  try {
    const event = JSON.parse(raw);

    const toolName   = event.tool_name || event.toolName || 'unknown';
    const toolInput  = event.tool_input || event.toolInput || {};
    const toolResult = event.tool_response ?? event.tool_result
                    ?? event.toolResponse  ?? event.toolResult
                    ?? event.output ?? '';

    const SKIP_TOOLS = new Set(['TodoRead', 'TodoWrite']);
    if (SKIP_TOOLS.has(toolName)) process.exit(0);

    // Build summary
    let summary = '';
    if (['Write','Edit','MultiEdit'].includes(toolName)) {
      summary = `${toolName} ${toolInput.file_path || toolInput.path || ''}`;
    } else if (toolName === 'Bash') {
      summary = `Bash: ${(toolInput.command || '').slice(0, 80)}`;
    } else if (toolName === 'Read') {
      summary = `Read ${toolInput.file_path || ''}`;
    } else {
      summary = `${toolName}: ${JSON.stringify(toolInput).slice(0, 80)}`;
    }

    let resultText = typeof toolResult === 'string'
      ? toolResult
      : JSON.stringify(toolResult);

    const compressedSummary = compress(summary, level);
    const compressed        = compress(resultText, level);
    const verboseLen        = (summary + resultText).length;
    const compressedLen     = (compressedSummary + compressed).length;
    const savedTokens       = tokens(summary + resultText) - tokens(compressedSummary + compressed);

    const entry = {
      id:           Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      ts:           new Date().toISOString(),
      level,
      tool:         toolName,
      summary:      compressedSummary,
      content:      compressed,
      verbose_len:  verboseLen,
      stored_len:   compressedLen,
      tokens_saved: Math.max(0, savedTokens),
      session_id:   event.session_id
                 || event.sessionId
                 || process.env.CLAUDE_SESSION_ID
                 || process.env.SESSION_ID
                 || 'unknown',
      cwd:          event.cwd || process.env.CLAUDE_CWD || process.cwd(),
    };

    const db = openDB();
    insertEntry(db, entry);

    // Regenerate handoff .md files on disk — always-fresh context for AI handoff.
    // Throttled to max once every 3 seconds to keep tool-call overhead near-zero.
    try {
      const stampPath = require('path').join(
        require('./stoneage-config').claudeDir, '.stoneage-handoff-stamp'
      );
      const now  = Date.now();
      let last   = 0;
      try { last = parseInt(fs.readFileSync(stampPath, 'utf8'), 10) || 0; } catch (_) {}
      if (now - last > 3000) {
        fs.writeFileSync(stampPath, String(now));
        writeAllHandoffs(db, { limit: 200, onlySession: entry.session_id });
      }
    } catch (_) { /* handoff write is best-effort */ }

    db.close();

  } catch (_) {
    // Silent fail — never block tool execution
  }
});
