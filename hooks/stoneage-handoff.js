#!/usr/bin/env node
/**
 * stoneage — Shared handoff generator
 *
 * Builds the markdown context-dump file that users paste into any
 * desktop AI coder (Cursor / Windsurf / Claude Code / Cline / Aider).
 *
 * Two callers:
 *   • viewer/server.js  (HTTP /handoff)
 *   • hooks/stoneage-observer.js  (write-on-every-tool-call)
 *
 * Exports:
 *   buildSessionLabels(sessions)   — unique labels + filesystem slugs
 *   generateHandoff(db, opts)      — returns markdown string
 *   writeAllHandoffs(db)           — writes combined + per-session .md files
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const { claudeDir } = require('./stoneage-config');
const { MEM_DB }    = require('./stoneage-db');

// ── Session naming (mirror of server.js helper) ──────────────────────────────
function folderBase(cwd) {
  if (!cwd) return 'local';
  const parts = cwd.replace(/[\\\/]+$/, '').split(/[\\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : 'local';
}
function safeSlug(s) {
  return (s || '').toLowerCase()
    .replace(/[^a-z0-9\-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40) || 'x';
}
function buildSessionLabels(sessions) {
  const entries = [...sessions.entries()].sort(
    (a, b) => (a[1].firstTs || '').localeCompare(b[1].firstTs || '')
  );
  const folderCount = new Map();
  for (const [, s] of entries) {
    const f = folderBase(s.cwd);
    folderCount.set(f, (folderCount.get(f) || 0) + 1);
  }
  const folderSeen = new Map();
  const out = new Map();
  for (const [sid, s] of entries) {
    const f   = folderBase(s.cwd);
    const dup = folderCount.get(f) > 1;
    const n   = (folderSeen.get(f) || 0) + 1;
    folderSeen.set(f, n);
    const sidTag = sid === 'unknown' ? 'sess' : sid.slice(0, 6);
    const label  = dup ? `${f} #${n} · ${sidTag}` : f;
    const slug   = dup ? `${safeSlug(f)}-${n}-${safeSlug(sidTag)}` : safeSlug(f);
    out.set(sid, { label, slug, folder: f, seq: n, sidTag });
  }
  return out;
}

// ── Generate handoff markdown ────────────────────────────────────────────────
function generateHandoff(db, opts = {}) {
  const { sessionFilter = null, limit = 100 } = opts;
  const where = sessionFilter ? 'WHERE session_id = ?' : '';
  const args  = sessionFilter ? [sessionFilter] : [];

  const entries = db.prepare(
    `SELECT * FROM memories ${where} ORDER BY ts DESC LIMIT ?`
  ).all(...args, limit).reverse();

  const bySession = new Map();
  for (const e of entries) {
    if (!bySession.has(e.session_id)) bySession.set(e.session_id, []);
    bySession.get(e.session_id).push(e);
  }

  const fileTouches = new Map();
  for (const e of entries) {
    if (['Write','Edit','MultiEdit','Read'].includes(e.tool)) {
      const m = e.summary.match(/\S+[\\\/][\S]+/);
      if (m) {
        const p = m[0];
        fileTouches.set(p, (fileTouches.get(p) || 0) + 1);
      }
    }
  }
  const topFiles = [...fileTouches.entries()]
    .sort((a,b) => b[1]-a[1]).slice(0, 15);

  let md = `# stoneage handoff\n\n`;
  md += `**Generated:** ${new Date().toISOString()}\n`;
  md += `**Source DB:** \`${MEM_DB}\`\n`;
  md += `**Scope:** ${sessionFilter ? `session ${sessionFilter}` : `all sessions (last ${limit} entries)`}\n\n`;
  md += `Paste this file into any AI coding assistant (Cursor, Windsurf, Claude Code, Cline, Aider, etc.) to hand over full working context from previous sessions.\n\n---\n\n`;

  md += `## Overview\n\n`;
  md += `- **Sessions in this handoff:** ${bySession.size}\n`;
  md += `- **Total memories:** ${entries.length}\n`;
  md += `- **Unique files touched:** ${fileTouches.size}\n`;
  md += `- **Compression:** stoneage-style (${entries[0]?.level || 'full'})\n\n`;

  md += `## Most-touched files\n\n`;
  for (const [fp, count] of topFiles) md += `- \`${fp}\` — ${count} touches\n`;
  md += `\n---\n\n## Sessions\n\n`;

  for (const [sid, evs] of bySession) {
    const cwd = evs[0]?.cwd || '';
    md += `### Session \`${sid}\`\n\n`;
    md += `- **cwd:** \`${cwd}\`\n`;
    md += `- **entries:** ${evs.length}\n`;
    md += `- **time range:** ${evs[0].ts} → ${evs[evs.length-1].ts}\n\n`;
    md += `| # | time | tool | action |\n|---|------|------|--------|\n`;
    for (const e of evs) {
      const t = e.ts.slice(11, 19);
      const summary = (e.summary || '').replace(/\|/g, '\\|').slice(0, 80);
      md += `| \`${e.id}\` | ${t} | ${e.tool} | ${summary} |\n`;
    }
    md += `\n`;
  }

  md += `---\n\n## Detailed memories (compressed)\n\n`;
  for (const e of entries.slice(-50)) {
    md += `### [mem:${e.id}] ${e.tool} · ${e.ts}\n`;
    md += `**session:** \`${e.session_id}\` · **saved:** ${e.tokens_saved} tok\n\n`;
    md += `${e.summary}\n\n`;
    if (e.content && e.content.trim()) {
      md += '```\n' + e.content.slice(0, 400) + '\n```\n\n';
    }
  }

  md += `---\n\n## Instructions to receiving AI\n\n`;
  md += `1. Treat each \`[mem:<id>]\` as an observation from a prior session\n`;
  md += `2. Files listed under "Most-touched files" are the project's working surface\n`;
  md += `3. Content is compressed (stoneage style) — expand as needed\n`;
  md += `4. Cite relevant memories: \`[mem:${entries[0]?.id||'xxx'}]\`\n\n`;
  md += `*Generated by stoneage · https://github.com/misterchange/stoneage*\n`;
  return md;
}

// ── Write all handoff files to ~/.claude/ ────────────────────────────────────
// Combined file + one per session. Called from both HTTP endpoint and hook.
function writeAllHandoffs(db, opts = {}) {
  const { limit = 100, onlySession = null } = opts;
  try { fs.mkdirSync(claudeDir, { recursive: true }); } catch (_) {}

  // Combined (all sessions)
  if (!onlySession) {
    const combined = generateHandoff(db, { limit });
    fs.writeFileSync(path.join(claudeDir, 'stoneage-handoff.md'), combined, 'utf8');
  }

  // Per-session files
  const rows = db.prepare(
    `SELECT session_id, MIN(cwd) cwd, MIN(ts) firstTs, MAX(ts) lastTs, COUNT(*) c
       FROM memories GROUP BY session_id`
  ).all();
  const sMap = new Map(rows.map(r =>
    [r.session_id, { firstTs: r.firstTs, lastTs: r.lastTs, cwd: r.cwd, count: r.c }]
  ));
  const labels = buildSessionLabels(sMap);

  for (const [sid, info] of labels) {
    if (onlySession && sid !== onlySession) continue;
    const md = generateHandoff(db, { sessionFilter: sid, limit: 500 });
    fs.writeFileSync(
      path.join(claudeDir, `stoneage-handoff-${info.slug}.md`),
      md, 'utf8'
    );
  }

  return { labels, combined: path.join(claudeDir, 'stoneage-handoff.md') };
}

module.exports = {
  buildSessionLabels,
  folderBase,
  safeSlug,
  generateHandoff,
  writeAllHandoffs,
};
