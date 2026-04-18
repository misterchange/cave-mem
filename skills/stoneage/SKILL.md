---
name: stoneage
description: "Activate combined stoneage-style token compression + persistent cross-session memory. Usage: /stoneage [lite|full|ultra|off|search <query>]"
type: user-invocable
---

# stoneage

Combines **stoneage** (output-token compression) and **claude-mem** (cross-session memory) into a single plugin.

## Quick Reference

| Command | Effect |
|---------|--------|
| `/stoneage` | Activate at default level (full) |
| `/stoneage lite` | Lite compression — minor reduction, high readability |
| `/stoneage full` | Full compression — ~75% token reduction (default) |
| `/stoneage ultra` | Ultra compression — extreme brevity |
| `/stoneage off` | Disable stoneage entirely |
| `/stoneage search <q>` | Search past session memory |
| `stop stoneage` | Deactivate (prose phrase) |
| `normal mode` | Deactivate (prose phrase) |

## How It Works

### Stoneage Layer (output compression)
- Drops articles, filler words, pleasantries, hedging
- Keeps all technical substance intact
- Fragments OK · short synonyms · code blocks unchanged
- Pattern: `[thing] [action] [reason]. [next step].`

### Memory Layer (cross-session persistence)
- Tool results, file edits, errors+fixes captured automatically
- Stored in stoneage-compressed format (matches active level)
- Cite stored facts with `[mem:<id>]` prefix
- Wrap sensitive content in `<private>…</private>` to exclude from storage

### Why stoneage Beats Running Both Separately
- Single combined context injection < 2× individual outputs (deduplication)
- One flag file (`.stoneage-active`) instead of two (`.stoneage-active` + mem state)
- Memory stored at the active compression level — tokens saved at write AND read time

## Configuration

`~/.claude/.stoneage-config.json`
```json
{ "compression": "full" }
```

## Compression Level Details

| **Level** | Token Reduction | Readability | Best For |
|-----------|----------------|-------------|----------|
| **lite** | ~30% | High | Long explanations, docs |
| **full** | ~75% | Good | Daily coding sessions |
| **ultra** | ~90% | Terse | Quick answers, debugging |

## Boundaries

- Code blocks, commit messages, PRs: always written in full
- Security warnings, irreversible action confirmations: always explicit
- User asks to clarify or repeats question: drop compression for that response, resume after
