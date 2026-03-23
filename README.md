# session-map

What did Claude touch? A zero-dependency Claude Code skill that shows exactly what happened in your session — blast radius score, interactive file tree, heatmap, sensitive file alerts, scope drift warnings, and web activity tracking.

| Terminal (`/session-map`) | HTML (`/session-map --html`) |
|:---:|:---:|
| ![Terminal](https://github.com/user-attachments/assets/166c5c73-5644-4a06-a013-7613852ae52f) | ![HTML](https://github.com/user-attachments/assets/e75f9bb4-0273-4b3a-a4a1-bdf212bd0300) |

## Install

```bash
npx skills add whitzhu/session-map
```

Or manually:

```bash
mkdir -p ~/.claude/skills/session-map
curl -fsSL https://raw.githubusercontent.com/whitzhu/session-map/main/SKILL.md \
  -o ~/.claude/skills/session-map/SKILL.md
mkdir -p ~/.claude/skills/session-map/scripts
curl -fsSL https://raw.githubusercontent.com/whitzhu/session-map/main/scripts/session-map.py \
  -o ~/.claude/skills/session-map/scripts/session-map.py
curl -fsSL https://raw.githubusercontent.com/whitzhu/session-map/main/scripts/template.html \
  -o ~/.claude/skills/session-map/scripts/template.html
```

## Usage

In any Claude Code session:

```
/session-map                      # Terminal report (default)
/session-map --html               # Interactive HTML report in browser
/session-map --live               # Live dashboard — auto-refreshes as Claude works
/session-map --live --timeout 0   # Live mode, never auto-shutdown (overnight sessions)
/session-map --live --timeout 600 # Auto-shutdown after 10 min idle
/session-map --scope src/         # Flag files outside src/
```

---

### Terminal (default)

Quick inline report right in your Claude session. Shows blast radius, file tree, sensitive file alerts, scope drift, web activity, and tool breakdown.

*(The terminal report is the same as the hero image above.)*

### HTML Report (`--html`)

Interactive report that opens in your browser. Includes everything from the terminal report plus a D3 treemap heatmap with zoom, collapsible file tree with activity bars, and click-to-open-in-editor support.

![HTML report — file tree and issues](https://github.com/user-attachments/assets/e75f9bb4-0273-4b3a-a4a1-bdf212bd0300)

![HTML report — treemap heatmap](https://github.com/user-attachments/assets/76a6f2f6-806a-4bba-bb3a-ff4fc274b7d8)

Features:
- **Treemap heatmap** — block size = activity level, color = operation type (modified/created/deleted/read-only/sensitive). Click directories to zoom in.
- **Collapsible file tree** — files sorted by activity, with inline edit/read bars. Purple sidebar = scope drift, pink sidebar = sensitive file.
- **Open in editor** — click the arrow on any file to open it in VS Code, Cursor, Zed, Sublime, IntelliJ, or copy the path. Choice is saved.
- **Scope drift & sensitive file alerts** — click any alert to jump to the file in the tree.
- **Static snapshot indicator** — header shows "Static snapshot" so you know it won't update.

### Live Dashboard (`--live`)

Same interactive HTML report, but served from a local server that **auto-refreshes every second** as Claude works. Keep it on another monitor to watch Claude in real time — especially useful with `--dangerously-skip-permissions`.

*(Same HTML report as above, with a green "Live" indicator in the header instead of "Static snapshot".)*

Features:
- **Green "Live" indicator** in the header — shows connection status and time since last update.
- **Auto-refreshes** via Server-Sent Events when the session file changes (~1s latency).
- **Auto-shutdown** after 120s of inactivity (configurable with `--timeout`). Use `--timeout 0` for overnight sessions.
- **Server reuse** — running `/session-map --live` again in the same project reuses the existing server instead of spinning up a new one.
- **Auto-cleanup** — PID file removed on shutdown. Server stops if session file is deleted.

Connection states:
| Indicator | Meaning |
|-----------|---------|
| Green dot, "Live" | Connected, receiving updates |
| Grey text, "Updated Xs ago" | Connected, waiting for changes |
| Yellow dot, "Connection lost" | Reconnecting automatically |
| Red dot, "Session ended" | Session file removed, server stopping |

## What it answers

1. **Did Claude touch files it shouldn't?** — sensitive file alerts (`.env`, `*.key`, `*.pem`), scope drift warnings
2. **How much did it change?** — blast radius score (1-10), edit/read counts per file
3. **What websites did it access?** — full URLs from WebFetch, WebSearch, and bash `curl`/`wget` commands
4. **Where did it work?** — file tree grouped by directory, treemap heatmap

## How it works

The skill runs a Python 3 script that:

1. Finds the most recent Claude Code session JSONL for your working directory
2. Parses tool calls: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch
3. Extracts file paths from bash commands (redirects, `rm`, `cp`, `mv`, `tee`, `curl -o`)
4. Extracts URLs from bash commands (`curl`, `wget`, etc.)
5. Calculates blast radius based on files touched vs. project size
6. Detects sensitive files and scope drift
7. Renders the report (terminal, HTML, or live server)

**Zero dependencies.** No npm, no Bun, no build step. Just Python 3 (pre-installed on macOS and Linux) and a D3.js CDN load for the treemap.

## Security model

### What the parser tracks

| Source | Tracked as |
|--------|-----------|
| `Read`, `Glob`, `Grep` | File read |
| `Write` (new file) | File create |
| `Write` (existing), `Edit`, `MultiEdit` | File write |
| Bash: `> /path`, `tee`, `curl -o` | File write |
| Bash: `rm /path` | File delete |
| Bash: `curl https://...` | Web request |
| `WebFetch` | Web request |
| `WebSearch` | Web search |

### What it cannot track

- **Script-internal writes**: `bun run script.ts` may write files not visible in the session log
- **Obfuscated commands**: `python3 -c "open('/tmp/.x','w').write(secret)"` bypasses string parsing
- **Ghost writes**: Files written via Bash that are never read back don't appear

These are inherent limitations of session-log parsing. Filesystem-level monitoring is out of scope.

### Sensitive file patterns

`.env`, `.env.*`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `*.secret`, `credentials`, `secrets/`, `private/`, `.ssh/`, `payment/`, `billing/`, `config/secrets`

## Requirements

- Python 3 (pre-installed on macOS since Catalina and most Linux distributions)
- Claude Code

## License

MIT
