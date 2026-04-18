#!/usr/bin/env node
/**
 * cave-mem Memory Stream Viewer — server (SQLite edition)
 *
 * Serves the real-time memory stream UI and SSE endpoint.
 * Reads from ~/.claude/cave-mem-memory.db (Node 22 built-in SQLite).
 * Polls DB every 500ms and pushes new entries to SSE clients.
 *
 * Usage:
 *   node C:/Nitin/Nitins/cave-mem/viewer/server.js
 *   open http://localhost:37778
 */

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');

const PORT = process.env.PORT || 37778;

// Load shared DB + handoff modules (hooks dir is sibling of viewer dir)
const { openDB, loadRecent, searchMemories, deleteSession, getStats, MEM_DB } =
  require('../hooks/cave-mem-db');
const { buildSessionLabels: sharedBuildLabels, writeAllHandoffs } =
  require('../hooks/cave-mem-handoff');

const db = openDB();

// ── Session naming ────────────────────────────────────────────────────────────
// Consistent folder-based label w/ disambiguation when same folder has multiple
// sessions. Chronological order (earliest = #1). Also returns filesystem-safe
// slug used for per-session handoff filenames.
function folderBase(cwd) {
  if (!cwd) return 'local';
  const parts = cwd.replace(/[\\\/]+$/, '').split(/[\\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : 'local';
}
function safeSlug(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9\-]+/g, '-').replace(/^-+|-+$/g,'').slice(0,40) || 'x';
}
function buildSessionLabels(sessions) {
  // sessions: Map<sid, { count, tokensSaved, firstTs, lastTs, cwd }>
  const entries = [...sessions.entries()].sort(
    (a, b) => (a[1].firstTs || '').localeCompare(b[1].firstTs || '')
  );
  // Count occurrences of each folder, assign #N to duplicates
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

// ── SSE client registry ───────────────────────────────────────────────────────
const clients = new Set();

function broadcast(data) {
  const msg = `data: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) {
    try { res.write(msg); } catch (_) { clients.delete(res); }
  }
}

// ── Poll DB for new entries ───────────────────────────────────────────────────
let lastTs = new Date(0).toISOString();

function pollNewEntries() {
  try {
    const rows = db.prepare(
      'SELECT * FROM memories WHERE ts > ? ORDER BY ts ASC'
    ).all(lastTs);
    for (const entry of rows) {
      lastTs = entry.ts;
      broadcast({ type: 'entry', entry });
    }
  } catch (_) {}
}

// Initialise lastTs to current max — so we don't re-broadcast history
try {
  const row = db.prepare('SELECT MAX(ts) AS t FROM memories').get();
  if (row && row.t) lastTs = row.t;
} catch (_) {}

setInterval(pollNewEntries, 500);

// ── HTTP server ───────────────────────────────────────────────────────────────
const PUBLIC_DIR = path.join(__dirname, 'public');

const server = http.createServer((req, res) => {
  const url    = req.url.split('?')[0];
  const params = new URL('http://x' + req.url).searchParams;

  // ── SSE: real-time stream ──────────────────────────────────────────────────
  if (url === '/stream') {
    res.writeHead(200, {
      'Content-Type':  'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection':    'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });
    res.write(`data: ${JSON.stringify({ type: 'connected' })}\n\n`);

    // Send history (last 200 entries)
    const history = loadRecent(db, 200);
    for (const entry of history) {
      res.write(`data: ${JSON.stringify({ type: 'entry', entry, historical: true })}\n\n`);
    }
    res.write(`data: ${JSON.stringify({ type: 'history_end', count: history.length })}\n\n`);

    clients.add(res);
    req.on('close', () => clients.delete(res));
    return;
  }

  // ── Stats ──────────────────────────────────────────────────────────────────
  if (url === '/stats') {
    const s = getStats(db);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ...s, active_clients: clients.size, db_path: MEM_DB }, null, 2));
    return;
  }

  // ── Search ─────────────────────────────────────────────────────────────────
  if (url === '/search') {
    const q = params.get('q') || '';
    if (!q) { res.writeHead(400); res.end('Missing q'); return; }
    const results = searchMemories(db, q, 50);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(results));
    return;
  }

  // ── Clear all ──────────────────────────────────────────────────────────────
  if (url === '/clear' && req.method === 'POST') {
    try { db.exec('DELETE FROM memories'); } catch (_) {}
    broadcast({ type: 'cleared' });
    res.writeHead(200); res.end('OK');
    return;
  }

  // ── Graph data (nodes + edges) ─────────────────────────────────────────────
  if (url === '/graph-data') {
    const sessionFilter = params.get('session'); // optional: filter to 1 session
    const where = sessionFilter ? 'WHERE session_id = ?' : '';
    const args  = sessionFilter ? [sessionFilter] : [];

    const entries = db.prepare(
      `SELECT id, ts, tool, summary, content, session_id, cwd,
              verbose_len, stored_len, tokens_saved
         FROM memories ${where}
         ORDER BY ts ASC`
    ).all(...args);

    // Build nodes: sessions + unique file paths
    const sessions = new Map();  // sid → { count, tokensSaved, firstTs }
    const files    = new Map();  // path → { count, sessions:Set, tool }
    const edges    = [];         // { from, to, value }

    // Helper: extract file path from memory summary
    const extractPath = (e) => {
      if (['Write','Edit','MultiEdit','Read'].includes(e.tool)) {
        const m = e.summary.match(/\S+[\\\/][\S]+/);
        return m ? m[0].replace(/[\.\,\;\:]+$/, '') : null;
      }
      return null;
    };

    for (const e of entries) {
      const sid = e.session_id;
      if (!sessions.has(sid)) {
        sessions.set(sid, { count: 0, tokensSaved: 0, firstTs: e.ts, lastTs: e.ts, cwd: e.cwd });
      }
      const s = sessions.get(sid);
      s.count        += 1;
      s.tokensSaved  += e.tokens_saved || 0;
      s.lastTs        = e.ts;

      const fpath = extractPath(e);
      if (fpath) {
        if (!files.has(fpath)) {
          files.set(fpath, { count: 0, sessions: new Set(), tool: e.tool });
        }
        const f = files.get(fpath);
        f.count += 1;
        f.sessions.add(sid);
      }
    }

    // Build vis-network payload
    const nodes = [];
    const colors = { session: '#58a6ff', file: '#3fb950', shared: '#f0883e' };

    const labels = buildSessionLabels(sessions);

    for (const [sid, s] of sessions) {
      const info = labels.get(sid);
      nodes.push({
        id: 'S:' + sid,
        label: info.label,
        group: 'session',
        value: s.count,
        title: `${info.label}\nsession: ${sid}\nslug: ${info.slug}\n${s.count} entries\n${s.tokensSaved} tokens saved\ncwd: ${s.cwd || '-'}\nrange: ${s.firstTs.slice(0,16)} → ${s.lastTs.slice(0,16)}`,
        color: { background: '#1f6feb', border: '#58a6ff' },
        slug: info.slug,
      });
    }

    for (const [fp, f] of files) {
      const shared = f.sessions.size > 1;
      const short  = fp.split(/[\\\/]/).pop();
      nodes.push({
        id: 'F:' + fp,
        label: short,
        group: shared ? 'shared-file' : 'file',
        value: f.count,
        title: `${fp}\n${f.count} touches\n${f.sessions.size} session(s)`,
        color: shared
          ? { background: '#c16c1a', border: '#f0883e' }
          : { background: '#1f6f31', border: '#3fb950' },
      });

      // edge: session → file (one per session touching this file)
      for (const sid of f.sessions) {
        edges.push({
          from: 'S:' + sid,
          to:   'F:' + fp,
          value: f.count,
          color: { color: '#30363d', opacity: 0.6 },
        });
      }
    }

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      nodes, edges,
      stats: {
        sessions: sessions.size,
        files:    files.size,
        shared_files: [...files.values()].filter(f => f.sessions.size > 1).length,
        entries:  entries.length,
      },
    }));
    return;
  }

  // ── Handoff markdown dump (THE copy-paste URL) ─────────────────────────────
  if (url === '/handoff' || url === '/handoff.md' || url === '/handoff.txt') {
    const sessionFilter = params.get('session');
    const limit         = parseInt(params.get('limit') || '100', 10);

    const where = sessionFilter ? 'WHERE session_id = ?' : '';
    const args  = sessionFilter ? [sessionFilter] : [];

    const entries = db.prepare(
      `SELECT * FROM memories ${where} ORDER BY ts DESC LIMIT ?`
    ).all(...args, limit);

    // Group by session
    const bySession = new Map();
    for (const e of entries.reverse()) {
      if (!bySession.has(e.session_id)) bySession.set(e.session_id, []);
      bySession.get(e.session_id).push(e);
    }

    // File touch frequency across all
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
      .sort((a,b) => b[1]-a[1])
      .slice(0, 15);

    const now = new Date().toISOString();
    let md = `# cave-mem handoff\n\n`;
    md += `**Generated:** ${now}\n`;
    md += `**Source DB:** \`${MEM_DB}\`\n`;
    md += `**Scope:** ${sessionFilter ? `session ${sessionFilter}` : `all sessions (last ${limit} entries)`}\n\n`;
    md += `Paste this file into any AI coding assistant (Cursor, Windsurf, Claude Code, `;
    md += `Copilot Chat, etc.) to hand over full working context from previous sessions.\n\n`;
    md += `---\n\n`;

    md += `## Overview\n\n`;
    md += `- **Sessions in this handoff:** ${bySession.size}\n`;
    md += `- **Total memories:** ${entries.length}\n`;
    md += `- **Unique files touched:** ${fileTouches.size}\n`;
    md += `- **Compression:** caveman-style (${entries[0]?.level || 'full'})\n\n`;

    md += `## Most-touched files\n\n`;
    for (const [fp, count] of topFiles) {
      md += `- \`${fp}\` — ${count} touches\n`;
    }
    md += `\n---\n\n`;

    md += `## Sessions\n\n`;
    for (const [sid, evs] of bySession) {
      const cwd = evs[0]?.cwd || '';
      md += `### Session \`${sid}\`\n\n`;
      md += `- **cwd:** \`${cwd}\`\n`;
      md += `- **entries:** ${evs.length}\n`;
      md += `- **time range:** ${evs[0].ts} → ${evs[evs.length-1].ts}\n\n`;

      md += `| # | time | tool | action |\n|---|------|------|--------|\n`;
      for (const e of evs) {
        const t = e.ts.slice(11, 19);
        const summary = e.summary.replace(/\|/g, '\\|').slice(0, 80);
        md += `| \`${e.id}\` | ${t} | ${e.tool} | ${summary} |\n`;
      }
      md += `\n`;
    }

    md += `---\n\n## Detailed memories (compressed)\n\n`;
    for (const e of entries.slice(0, 50)) {
      md += `### [mem:${e.id}] ${e.tool} · ${e.ts}\n`;
      md += `**session:** \`${e.session_id}\` · **saved:** ${e.tokens_saved} tok\n\n`;
      md += `${e.summary}\n\n`;
      if (e.content && e.content.trim()) {
        md += '```\n' + e.content.slice(0, 400) + '\n```\n\n';
      }
    }

    md += `---\n\n`;
    md += `## Instructions to receiving AI\n\n`;
    md += `1. Treat each \`[mem:<id>]\` as an observation from a prior session\n`;
    md += `2. The files listed under "Most-touched files" are the project's working surface\n`;
    md += `3. Content is compressed (caveman style) — expand as needed\n`;
    md += `4. If a user question maps to a mem id, cite it: \`[mem:${entries[0]?.id||'xxx'}]\`\n`;
    md += `5. Check \`${MEM_DB}\` via the cave-mem viewer for live updates\n\n`;
    md += `*Generated by cave-mem · https://github.com/misterchange/cave-mem*\n`;

    // Also persist to disk so users can hand AIs the file path (no server needed)
    try {
      const claudeDir = path.dirname(MEM_DB);
      let outName = 'cave-mem-handoff.md';
      if (sessionFilter) {
        // Look up slug from all sessions for stable filename
        const all = db.prepare('SELECT session_id, cwd, MIN(ts) firstTs, MAX(ts) lastTs, COUNT(*) c, SUM(tokens_saved) ts2 FROM memories GROUP BY session_id').all();
        const sMap = new Map(all.map(r => [r.session_id, { firstTs:r.firstTs, lastTs:r.lastTs, cwd:r.cwd, count:r.c, tokensSaved:r.ts2 }]));
        const slug = buildSessionLabels(sMap).get(sessionFilter)?.slug || sessionFilter.slice(0,8);
        outName = `cave-mem-handoff-${slug}.md`;
      }
      fs.writeFileSync(path.join(claudeDir, outName), md, 'utf8');
    } catch (_) {}

    res.writeHead(200, { 'Content-Type': 'text/markdown; charset=utf-8' });
    res.end(md);
    return;
  }

  // ── Sessions list with stable slugs + per-session file paths + URLs ───────
  if (url === '/sessions') {
    const rows = db.prepare(
      `SELECT session_id, MIN(cwd) cwd, MIN(ts) firstTs, MAX(ts) lastTs,
              COUNT(*) entries, SUM(tokens_saved) tokens_saved
         FROM memories GROUP BY session_id ORDER BY MIN(ts) ASC`
    ).all();
    const sMap = new Map(rows.map(r => [r.session_id,
      { firstTs: r.firstTs, lastTs: r.lastTs, cwd: r.cwd, count: r.entries, tokensSaved: r.tokens_saved }]));
    const labels = buildSessionLabels(sMap);
    const claudeDir = path.dirname(MEM_DB);
    const origin    = `http://localhost:${PORT}`;
    const out = rows.map(r => {
      const info = labels.get(r.session_id);
      return {
        session_id:  r.session_id,
        label:       info.label,
        slug:        info.slug,
        folder:      info.folder,
        cwd:         r.cwd,
        first_ts:    r.firstTs,
        last_ts:     r.lastTs,
        entries:     r.entries,
        tokens_saved: r.tokens_saved,
        handoff_url:  `${origin}/handoff?session=${encodeURIComponent(r.session_id)}`,
        handoff_file: path.join(claudeDir, `cave-mem-handoff-${info.slug}.md`),
      };
    });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(out, null, 2));
    return;
  }

  // ── Handoff file path (tells user where the context file lives on disk) ────
  if (url === '/handoff-path') {
    const claudeDir = path.dirname(MEM_DB);
    const filePath  = path.join(claudeDir, 'cave-mem-handoff.md');
    let size = 0, mtime = null;
    try { const st = fs.statSync(filePath); size = st.size; mtime = st.mtime.toISOString(); } catch(_) {}
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      db_path:     MEM_DB,
      handoff_md:  filePath,
      size_bytes:  size,
      last_written: mtime,
      instructions: 'Paste the handoff_md path into any AI: "Read <path> and use as project context."',
    }, null, 2));
    return;
  }

  // ── Delete session ─────────────────────────────────────────────────────────
  if (url === '/delete-session' && req.method === 'POST') {
    const sid = params.get('id');
    if (!sid) { res.writeHead(400); res.end('Missing id'); return; }
    try {
      deleteSession(db, sid);
      broadcast({ type: 'session_deleted', session_id: sid });
      res.writeHead(200); res.end('OK');
    } catch (e) { res.writeHead(500); res.end(e.message); }
    return;
  }

  // ── Static files ───────────────────────────────────────────────────────────
  const filePath = url === '/' ? '/index.html' : url;
  const fullPath = path.join(PUBLIC_DIR, filePath);
  try {
    const content = fs.readFileSync(fullPath);
    const ext     = path.extname(fullPath);
    const types   = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' };
    res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain' });
    res.end(content);
  } catch (_) {
    res.writeHead(404); res.end('Not found');
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`cave-mem memory stream viewer`);
  console.log(`  http://localhost:${PORT}`);
  console.log(`  database: ${MEM_DB}`);
  console.log(`  press Ctrl+C to stop`);
});
