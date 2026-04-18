#!/usr/bin/env node
/**
 * stoneage shared configuration
 *
 * Config file: ~/.claude/.stoneage-config.json
 * {
 *   "compression": "lite" | "full" | "ultra" | "off"   // default: "full"
 * }
 *
 * Compression levels:
 *   lite  — minor token reduction, high readability
 *   full  — ~75% token reduction, full accuracy (default)
 *   ultra — extreme compression, fast responses only
 *   off   — disable entirely (no flag written, no rules injected)
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');

const VALID_LEVELS  = new Set(['lite', 'full', 'ultra', 'off']);
const DEFAULT_LEVEL = 'full';

const claudeDir    = path.join(os.homedir(), '.claude');
const configPath   = path.join(claudeDir, '.stoneage-config.json');
// Backward-compat: pre-rebrand filenames. Copied to the new name on first read
// if the new file does not yet exist, preserving existing settings/flag.
const LEGACY_CONFIG = path.join(claudeDir, '.cave-mem-config.json');
const LEGACY_FLAG   = path.join(claudeDir, '.cave-mem-active');

function migrateLegacy(newPath, oldPath) {
  try {
    if (!fs.existsSync(newPath) && fs.existsSync(oldPath)) {
      fs.copyFileSync(oldPath, newPath);
    }
  } catch (_) { /* best-effort */ }
}

/**
 * Return the active compression level.
 * Reads ~/.claude/.stoneage-config.json; falls back to DEFAULT_LEVEL.
 */
function getCompressionLevel() {
  try {
    migrateLegacy(configPath, LEGACY_CONFIG);
    const raw   = fs.readFileSync(configPath, 'utf8');
    const cfg   = JSON.parse(raw);
    const level = (cfg.compression || '').trim().toLowerCase();
    return VALID_LEVELS.has(level) ? level : DEFAULT_LEVEL;
  } catch (_) {
    return DEFAULT_LEVEL;
  }
}

/**
 * Write a new compression level to the config file.
 */
function setCompressionLevel(level) {
  if (!VALID_LEVELS.has(level)) {
    throw new Error(`Invalid compression level: '${level}'. Valid: ${[...VALID_LEVELS].join(', ')}`);
  }
  try {
    fs.mkdirSync(claudeDir, { recursive: true });
    fs.writeFileSync(configPath, JSON.stringify({ compression: level }, null, 2) + '\n');
  } catch (e) {
    // Silent fail — config is best-effort
  }
}

/**
 * Read the current active mode from the runtime flag file.
 * Returns null if stoneage is not currently active.
 */
function getActiveMode() {
  const flagPath = path.join(claudeDir, '.stoneage-active');
  try {
    migrateLegacy(flagPath, LEGACY_FLAG);
    return fs.readFileSync(flagPath, 'utf8').trim() || null;
  } catch (_) {
    return null;
  }
}

module.exports = { getCompressionLevel, setCompressionLevel, getActiveMode, claudeDir };
