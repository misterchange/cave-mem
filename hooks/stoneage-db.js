#!/usr/bin/env node
/**
 * stoneage — Shared SQLite database module
 *
 * Uses Node.js built-in node:sqlite (Node 22+, zero npm deps).
 * Single source of truth for DB path, schema, and helpers.
 *
 * DB file: ~/.claude/stoneage-memory.db
 * Auto-migrates existing stoneage-memory.jsonl on first open.
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { DatabaseSync } = require('node:sqlite');

const claudeDir = path.join(os.homedir(), '.claude');
const MEM_DB    = path.join(claudeDir, 'stoneage-memory.db');
const MEM_LOG   = path.join(claudeDir, 'stoneage-memory.jsonl'); // legacy
// Backward-compat: pre-rebrand DB filename. If the new-name file doesn't yet
// exist but the old one does, copy it on first open to preserve existing data.
const LEGACY_MEM_DB = path.join(claudeDir, 'cave-mem-memory.db');

// ── Schema ────────────────────────────────────────────────────────────────────
const SCHEMA = `
  CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    level        TEXT DEFAULT 'full',
    tool         TEXT DEFAULT 'unknown',
    summary      TEXT DEFAULT '',
    content      TEXT DEFAULT '',
    verbose_len  INTEGER DEFAULT 0,
    stored_len   INTEGER DEFAULT 0,
    tokens_saved INTEGER DEFAULT 0,
    session_id   TEXT DEFAULT 'unknown',
    cwd          TEXT DEFAULT '',
    project_folder TEXT DEFAULT ''
  );
  CREATE INDEX IF NOT EXISTS idx_ts      ON memories(ts);
  CREATE INDEX IF NOT EXISTS idx_session ON memories(session_id);
  CREATE INDEX IF NOT EXISTS idx_tool    ON memories(tool);

  CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(summary, content, content=memories, content_rowid=rowid);

  CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, summary, content)
      VALUES (new.rowid, new.summary, new.content);
  END;
  CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, summary, content)
      VALUES ('delete', old.rowid, old.summary, old.content);
  END;
`;

// ── Open & initialise ─────────────────────────────────────────────────────────
function openDB() {
  fs.mkdirSync(claudeDir, { recursive: true });
  // Backward-compat: copy legacy cave-mem-memory.db → stoneage-memory.db
  // on first run after rebrand, so existing memories are preserved.
  try {
    if (!fs.existsSync(MEM_DB) && fs.existsSync(LEGACY_MEM_DB)) {
      fs.copyFileSync(LEGACY_MEM_DB, MEM_DB);
      process.stderr.write(
        `[stoneage] Migrated legacy DB: ${LEGACY_MEM_DB} → ${MEM_DB}\n`
      );
    }
  } catch (_) { /* best-effort */ }
  const db = new DatabaseSync(MEM_DB);
  db.exec(SCHEMA);
  ensureProjectFolderColumn(db);
  migrateJSONL(db);
  return db;
}

// Ensure `project_folder` column exists on older DBs (additive migration).
function ensureProjectFolderColumn(db) {
  try {
    const cols = db.prepare("PRAGMA table_info(memories)").all();
    const has = cols.some(c => c.name === 'project_folder');
    if (!has) {
      db.exec("ALTER TABLE memories ADD COLUMN project_folder TEXT DEFAULT ''");
    }
    db.exec("CREATE INDEX IF NOT EXISTS idx_project_folder ON memories(project_folder)");
  } catch (_) { /* best-effort */ }
}

// ── JSONL → SQLite migration (one-time) ──────────────────────────────────────
function migrateJSONL(db) {
  try {
    if (!fs.existsSync(MEM_LOG)) return;
    const count = db.prepare('SELECT COUNT(*) AS c FROM memories').get().c;
    if (count > 0) return; // already populated — skip

    const lines = fs.readFileSync(MEM_LOG, 'utf8')
      .split('\n').filter(l => l.trim());
    if (lines.length === 0) return;

    const insert = db.prepare(`
      INSERT OR IGNORE INTO memories
        (id, ts, level, tool, summary, content, verbose_len, stored_len, tokens_saved, session_id, cwd)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    for (const line of lines) {
      try {
        const e = JSON.parse(line);
        insert.run(
          e.id || Date.now().toString(36),
          e.ts || new Date().toISOString(),
          e.level        || 'full',
          e.tool         || 'unknown',
          e.summary      || '',
          e.content      || '',
          e.verbose_len  || 0,
          e.stored_len   || 0,
          e.tokens_saved || 0,
          e.session_id   || 'unknown',
          e.cwd          || ''
        );
      } catch (_) {}
    }

    // Keep JSONL as backup (renamed)
    try { fs.renameSync(MEM_LOG, MEM_LOG + '.bak'); } catch (_) {}
    process.stderr.write(`[stoneage] Migrated ${lines.length} entries: JSONL → SQLite\n`);
  } catch (_) {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Insert a single memory entry */
function insertEntry(db, entry) {
  db.prepare(`
    INSERT OR REPLACE INTO memories
      (id, ts, level, tool, summary, content, verbose_len, stored_len,
       tokens_saved, session_id, cwd, project_folder)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    entry.id, entry.ts, entry.level, entry.tool,
    entry.summary, entry.content,
    entry.verbose_len, entry.stored_len, entry.tokens_saved,
    entry.session_id, entry.cwd, entry.project_folder || ''
  );
}

/** Load last N entries ordered by time (for session-start context injection) */
function loadRecent(db, limit = 200) {
  return db.prepare(
    'SELECT * FROM memories ORDER BY ts DESC LIMIT ?'
  ).all(limit).reverse(); // reverse so oldest first for context
}

/** Full-text search across summary + content */
function searchMemories(db, query, limit = 20) {
  try {
    return db.prepare(`
      SELECT m.* FROM memories m
      JOIN memories_fts f ON m.rowid = f.rowid
      WHERE memories_fts MATCH ?
      ORDER BY m.ts DESC
      LIMIT ?
    `).all(query, limit);
  } catch (_) {
    // Fallback: LIKE search if FTS fails
    const q = '%' + query + '%';
    return db.prepare(`
      SELECT * FROM memories
      WHERE summary LIKE ? OR content LIKE ?
      ORDER BY ts DESC LIMIT ?
    `).all(q, q, limit);
  }
}

/** Delete all entries for a session */
function deleteSession(db, sessionId) {
  db.prepare('DELETE FROM memories WHERE session_id = ?').run(sessionId);
}

/** Get DB stats */
function getStats(db) {
  const total    = db.prepare('SELECT COUNT(*) AS c FROM memories').get().c;
  const sessions = db.prepare('SELECT COUNT(DISTINCT session_id) AS c FROM memories').get().c;
  const saved    = db.prepare('SELECT SUM(tokens_saved) AS s FROM memories').get().s || 0;
  const stored   = db.prepare('SELECT SUM(stored_len) AS s FROM memories').get().s || 0;
  const byTool   = db.prepare(
    'SELECT tool, COUNT(*) AS c FROM memories GROUP BY tool ORDER BY c DESC'
  ).all().reduce((m, r) => { m[r.tool] = r.c; return m; }, {});
  let fileSize = 0;
  try { fileSize = fs.existsSync(MEM_DB) ? fs.statSync(MEM_DB).size : 0; } catch (_) {}

  return { total_entries: total, sessions, tokens_saved: saved,
           tokens_stored: Math.ceil(stored / 4), by_tool: byTool,
           file_size: fileSize, db_path: MEM_DB };
}

module.exports = { openDB, insertEntry, loadRecent, searchMemories, deleteSession, getStats, MEM_DB, claudeDir };
