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

// Load shared DB module (hooks dir is sibling of viewer dir)
const { openDB, loadRecent, searchMemories, deleteSession, getStats, MEM_DB } =
  require('../hooks/cave-mem-db');

const db = openDB();

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
