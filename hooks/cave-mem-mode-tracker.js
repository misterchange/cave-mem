#!/usr/bin/env node
/**
 * cave-mem — UserPromptSubmit hook
 *
 * Tracks /cave-mem commands and deactivation phrases.
 * Reads JSON from stdin (Claude Code hook protocol) and writes the
 * active mode to ~/.claude/.cave-mem-active.
 *
 * Supported commands:
 *   /cave-mem          — activate at default level (full)
 *   /cave-mem lite     — lite compression
 *   /cave-mem full     — full compression (default)
 *   /cave-mem ultra    — ultra compression
 *   /cave-mem off      — disable
 *   /cave-mem search … — pass-through to memory search (flag unchanged)
 *   stop cave-mem      — deactivate
 *   normal mode        — deactivate
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { getCompressionLevel, claudeDir } = require('./cave-mem-config');

const flagPath = path.join(claudeDir, '.cave-mem-active');

let rawInput = '';
process.stdin.on('data', chunk => { rawInput += chunk; });
process.stdin.on('end', () => {
  try {
    const data   = JSON.parse(rawInput);
    const prompt = (data.prompt || '').trim().toLowerCase();

    // ── Deactivation phrases ─────────────────────────────────────────────────
    if (/\b(stop cave-?mem|normal mode)\b/i.test(prompt)) {
      try { fs.unlinkSync(flagPath); } catch (_) {}
      process.exit(0);
    }

    // ── /cave-mem commands ───────────────────────────────────────────────────
    if (prompt.startsWith('/cave-mem')) {
      const parts = prompt.split(/\s+/);
      const sub   = parts[1] || '';  // lite | full | ultra | off | search | ''

      // search sub-command — don't change mode, just let it pass through
      if (sub === 'search') {
        process.exit(0);
      }

      let mode = null;
      if (sub === 'lite')  mode = 'lite';
      else if (sub === 'ultra') mode = 'ultra';
      else if (sub === 'off')   mode = 'off';
      else                      mode = getCompressionLevel(); // 'full' or configured default

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
