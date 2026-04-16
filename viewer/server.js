#!/usr/bin/env node
/**
 * cave-mem Memory Stream Viewer — server
 *
 * Serves the real-time memory stream UI and SSE endpoint.
 * Watches ~/.claude/cave-mem-memory.jsonl and pushes new entries
 * to all connected browser clients via Server-Sent Events.
 *
 * Usage:
 *   node C:/Nitin/Nitins/cave-mem/viewer/server.js
 *   open http://localhost:37778
 */

'use strict';

const http   = require('http');
const fs     = require('fs');
const path   = require('path');
const os     = require('os');

const PORT       = 37778;
const MEM_LOG    = path.join(os.homedir(), '.claude', 'cave-mem-memory.jsonl');
const PUBLIC_DIR = path.join(__dirname, 'public');

// ── SSE client registry ───────────────────────────────────────────────────────
const clients = new Set();

function broadcast(data) {
  const msg = `data: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) {
    try { res.write(msg); } catch (_) { clients.delete(res); }
  }
}

// ── Watch JSONL for new lines ─────────────────────────────────────────────────
let lastSize = 0;
try { lastSize = fs.existsSync(MEM_LOG) ? fs.statSync(MEM_LOG).size : 0; } catch (_) {}

function watchLog() {
  const dir = path.dirname(MEM_LOG);
  fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(MEM_LOG)) fs.writeFileSync(MEM_LOG, '');

  fs.watch(MEM_LOG, () => {
    try {
      const stat = fs.statSync(MEM_LOG);
      if (stat.size <= lastSize) return;
      const fd  = fs.openSync(MEM_LOG, 'r');
      const buf = Buffer.alloc(stat.size - lastSize);
      fs.readSync(fd, buf, 0, buf.length, lastSize);
      fs.closeSync(fd);
      lastSize = stat.size;

      const lines = buf.toString('utf8').split('\n').filter(l => l.trim());
      for (const line of lines) {
        try {
          const entry = JSON.parse(line);
          broadcast({ type: 'entry', entry });
        } catch (_) {}
      }
    } catch (_) {}
  });
}

// ── Load existing entries ─────────────────────────────────────────────────────
function loadHistory() {
  try {
    if (!fs.existsSync(MEM_LOG)) return [];
    return fs.readFileSync(MEM_LOG, 'utf8')
      .split('\n')
      .filter(l => l.trim())
      .map(l => { try { return JSON.parse(l); } catch (_) { return null; } })
      .filter(Boolean)
      .slice(-200);  // last 200 entries
  } catch (_) { return []; }
}

// ── HTTP server ───────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];

  // SSE endpoint
  if (url === '/stream') {
    res.writeHead(200, {
      'Content-Type':  'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection':    'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });
    res.write(`data: ${JSON.stringify({ type: 'connected' })}\n\n`);

    // Send history on connect
    const history = loadHistory();
    for (const entry of history) {
      res.write(`data: ${JSON.stringify({ type: 'entry', entry, historical: true })}\n\n`);
    }
    res.write(`data: ${JSON.stringify({ type: 'history_end', count: history.length })}\n\n`);

    clients.add(res);
    req.on('close', () => clients.delete(res));
    return;
  }

  // Stats endpoint
  if (url === '/stats') {
    const entries = loadHistory();
    const totalSaved  = entries.reduce((s, e) => s + (e.tokens_saved || 0), 0);
    const totalStored = entries.reduce((s, e) => s + Math.ceil((e.stored_len || 0) / 4), 0);
    const byTool = entries.reduce((m, e) => {
      m[e.tool] = (m[e.tool] || 0) + 1; return m;
    }, {});
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      total_entries:  entries.length,
      tokens_saved:   totalSaved,
      tokens_stored:  totalStored,
      active_clients: clients.size,
      by_tool:        byTool,
      log_path:       MEM_LOG,
    }, null, 2));
    return;
  }

  // Clear log endpoint
  if (url === '/clear' && req.method === 'POST') {
    try { fs.writeFileSync(MEM_LOG, ''); lastSize = 0; } catch (_) {}
    broadcast({ type: 'cleared' });
    res.writeHead(200); res.end('OK');
    return;
  }

  // Serve static files
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

watchLog();
server.listen(PORT, '127.0.0.1', () => {
  console.log(`cave-mem memory stream viewer`);
  console.log(`  http://localhost:${PORT}`);
  console.log(`  watching: ${MEM_LOG}`);
  console.log(`  press Ctrl+C to stop`);
});
