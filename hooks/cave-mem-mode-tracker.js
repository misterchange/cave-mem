#!/usr/bin/env node
/**
 * cave-mem — UserPromptSubmit hook
 *
 * Handles /cave-mem commands and deactivation phrases.
 * /cave-mem search <query> now performs real SQLite full-text search
 * and injects matching memories into the prompt context.
 *
 * Supported commands:
 *   /cave-mem              — activate at default level (full)
 *   /cave-mem lite|full|ultra — switch compression level
 *   /cave-mem off          — disable
 *   /cave-mem search <q>   — full-text search SQLite memories
 *   stop cave-mem          — deactivate
 *   normal mode            — deactivate
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const { getCompressionLevel, claudeDir } = require('./cave-mem-config');
const { openDB, searchMemories } = require('./cave-mem-db');

const flagPath = path.join(claudeDir, '.cave-mem-active');

let rawInput = '';
process.stdin.on('data', chunk => { rawInput += chunk; });
process.stdin.on('end', () => {
  try {
    const data   = JSON.parse(rawInput);
    const prompt = (data.prompt || '').trim();
    const lower  = prompt.toLowerCase();

    // ── Deactivation ─────────────────────────────────────────────────────────
    if (/\b(stop cave-?mem|normal mode)\b/i.test(lower)) {
      try { fs.unlinkSync(flagPath); } catch (_) {}
      process.exit(0);
    }

    // ── /cave-mem commands ────────────────────────────────────────────────────
    if (lower.startsWith('/cave-mem')) {
      const parts = lower.split(/\s+/);
      const sub   = parts[1] || '';

      // search sub-command — query SQLite FTS and inject results
      if (sub === 'search') {
        const query = prompt.slice(prompt.toLowerCase().indexOf('search') + 6).trim();
        if (query) {
          try {
            const db      = openDB();
            const results = searchMemories(db, query, 20);
            db.close();

            if (results.length === 0) {
              process.stdout.write(
                `[cave-mem search] No memories found for: "${query}"`
              );
            } else {
              const lines = results.map(e =>
                `[${e.id}] ${e.ts.slice(0,16)} | ${e.tool} | ${e.summary}\n  ${e.content}`
              );
              process.stdout.write(
                `[cave-mem search] ${results.length} result(s) for "${query}":\n\n` +
                lines.join('\n\n')
              );
            }
          } catch (err) {
            process.stdout.write(`[cave-mem search] Error: ${err.message}`);
          }
        }
        process.exit(0);
      }

      // level switch
      let mode = null;
      if (sub === 'lite')        mode = 'lite';
      else if (sub === 'ultra')  mode = 'ultra';
      else if (sub === 'off')    mode = 'off';
      else if (sub === 'full')   mode = 'full';
      else                       mode = getCompressionLevel();

      if (mode === 'off') {
        try { fs.unlinkSync(flagPath); } catch (_) {}
      } else {
        fs.mkdirSync(claudeDir, { recursive: true });
        fs.writeFileSync(flagPath, mode);
      }
    }
  } catch (_) {
    // Silent fail — never block the user's prompt
  }
});
