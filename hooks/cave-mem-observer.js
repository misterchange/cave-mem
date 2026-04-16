#!/usr/bin/env node
/**
 * cave-mem — PostToolUse observer hook
 *
 * Fires after every tool call. Captures the tool result, compresses it
 * to the active cave-mem level, and appends to the memory JSONL log.
 *
 * Log file: ~/.claude/cave-mem-memory.jsonl
 * Viewer:   node C:/Nitin/Nitins/cave-mem/viewer/server.js
 *           then open http://localhost:37778
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { getCompressionLevel, claudeDir } = require('./cave-mem-config');

const memoryLog = path.join(claudeDir, 'cave-mem-memory.jsonl');
const flagPath  = path.join(claudeDir, '.cave-mem-active');

// Only run if cave-mem is active
try {
  if (!fs.existsSync(flagPath)) process.exit(0);
} catch (_) { process.exit(0); }

const level = getCompressionLevel();

// ── Compression: reduce text to active level ─────────────────────────────────
function compress(text, lvl) {
  if (!text || typeof text !== 'string') return String(text || '');

  // Truncate to level-appropriate length first
  const maxLen = { lite: 800, full: 400, ultra: 180 }[lvl] || 400;
  let out = text.trim();

  if (lvl === 'lite') {
    // Remove filler phrases, keep most content
    out = out
      .replace(/\b(just|really|basically|actually|simply|very|quite)\b/gi, '')
      .replace(/\b(I'd be happy to|Sure!|Of course|Certainly)\b/gi, '')
      .replace(/\s{2,}/g, ' ')
      .trim();

  } else if (lvl === 'full') {
    // Drop articles, hedging, pleasantries — keep technical substance
    out = out
      .replace(/\b(a|an|the)\s+/gi, '')
      .replace(/\b(just|really|basically|actually|simply|very|quite|I'd be happy to|Sure!|Of course|Certainly|Please note that|It's worth noting that|It is important to)\b[,\s]*/gi, '')
      .replace(/\b(successfully|correctly|properly|currently)\b/gi, '')
      .replace(/\s{2,}/g, ' ')
      .trim();

  } else if (lvl === 'ultra') {
    // Keep only first sentence + key terms
    const firstSentence = out.split(/[.!?]/)[0];
    out = firstSentence
      .replace(/\b(a|an|the|is|are|was|were|be|been|being)\b/gi, '')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  // Final length cap
  if (out.length > maxLen) {
    out = out.slice(0, maxLen - 3) + '...';
  }

  return out;
}

// ── Estimate tokens ───────────────────────────────────────────────────────────
function tokens(text) { return Math.ceil((text || '').length / 4); }

// ── Read stdin (PostToolUse event) ───────────────────────────────────────────
let raw = '';
process.stdin.on('data', c => { raw += c; });
process.stdin.on('end', () => {
  try {
    const event = JSON.parse(raw);

    const toolName   = event.tool_name || event.toolName || 'unknown';
    const toolInput  = event.tool_input || event.toolInput || {};
    const toolResult = event.tool_result ?? event.toolResult ?? event.output ?? '';

    // Skip tools that produce noisy output not worth storing
    const SKIP_TOOLS = new Set(['TodoRead', 'TodoWrite']);
    if (SKIP_TOOLS.has(toolName)) { process.exit(0); }

    // Build summary of the tool call
    let summary = '';
    if (toolName === 'Write' || toolName === 'Edit' || toolName === 'MultiEdit') {
      const filePath = toolInput.file_path || toolInput.path || '';
      summary = `${toolName} ${filePath}`;
    } else if (toolName === 'Bash') {
      const cmd = (toolInput.command || '').slice(0, 80);
      summary = `Bash: ${cmd}`;
    } else if (toolName === 'Read') {
      summary = `Read ${toolInput.file_path || ''}`;
    } else {
      summary = `${toolName}: ${JSON.stringify(toolInput).slice(0, 80)}`;
    }

    // Result content to store
    let resultText = '';
    if (typeof toolResult === 'string') {
      resultText = toolResult;
    } else if (toolResult && typeof toolResult === 'object') {
      resultText = JSON.stringify(toolResult);
    }

    const verboseLen  = (summary + resultText).length;
    const compressed  = compress(resultText, level);
    const compressedLen = (summary + compressed).length;
    const savedTokens = tokens(resultText) - tokens(compressed);

    // Build memory entry
    const entry = {
      id:          Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      ts:          new Date().toISOString(),
      level,
      tool:        toolName,
      summary:     compress(summary, level),
      content:     compressed,
      verbose_len: verboseLen,
      stored_len:  compressedLen,
      tokens_saved: Math.max(0, savedTokens),
      session_id:  process.env.CLAUDE_SESSION_ID || process.env.SESSION_ID || 'unknown',
      cwd:         process.env.CLAUDE_CWD || process.cwd(),
    };

    // Append to JSONL log
    fs.mkdirSync(path.dirname(memoryLog), { recursive: true });
    fs.appendFileSync(memoryLog, JSON.stringify(entry) + '\n', 'utf8');

  } catch (_) {
    // Silent fail — never block tool execution
  }
});
