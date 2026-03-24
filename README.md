# session-map

What did Claude touch? A zero-dependency Claude Code skill that shows exactly what happened in your session — blast radius score, interactive file tree, heatmap, sensitive file alerts, scope drift warnings, and web activity tracking.

| Terminal (`/session-map`) | HTML (`/session-map --html` or `--live`) |
|:---:|:---:|
| ![Terminal](https://github.com/user-attachments/assets/166c5c73-5644-4a06-a013-7613852ae52f) | ![HTML](https://github.com/user-attachments/assets/29e088cf-4647-4b36-95c0-67af7eac5fa0) |

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
/session-map --scope src/         # Flag files outside src/
```

---

### Terminal (default)

Quick inline report right in your Claude session. Shows blast radius, file tree, sensitive file alerts, scope drift, web activity, and tool breakdown.

### HTML Report (`--html`) and Live Dashboard (`--live`)

Interactive report that opens in your browser. `--html` generates a static snapshot; `--live` starts a local server that auto-refreshes as Claude works (keep it on another monitor).

**Blast radius, scope issues, and file tree** — see what was touched, with scope drift (purple sidebar) and activity bars:

![File tree with scope drift and editor picker](https://github.com/user-attachments/assets/40103d46-befb-446b-89f9-7a0015c82da4)

**Web activity and treemap heatmap** — block size = activity level, color = operation type. Click directories to zoom in:

![Web activity and treemap heatmap](https://github.com/user-attachments/assets/7014a6a5-6dc4-40bc-963a-ed0cc8209068)

**Tool breakdown** — which tools Claude used and how often:

![Tool calls breakdown](https://github.com/user-attachments/assets/17e5a2a1-d244-4b44-b8e6-20b01c8a3266)

**Git activity** — commits made during the session and uncommitted changes:

![Git activity](https://github.com/user-attachments/assets/b423a1ef-8506-462b-a195-de2d603325f5)

**Footer** — summary stats:

![Footer stats](https://github.com/user-attachments/assets/40a68f6f-9b61-4ffb-b3c1-668e7550c13a)

#### Features

- **Treemap heatmap** — color-coded by operation type (modified/created/deleted/read-only/sensitive). Click directories to zoom in.
- **Collapsible file tree** — files sorted by activity, with inline edit/read bars. Purple sidebar = scope drift, pink sidebar = sensitive file.
- **Open in editor** — click the arrow on any file to open it in VS Code, Cursor, Zed, Sublime, IntelliJ, or copy the path. Choice is saved in localStorage.
- **Scope drift & sensitive file alerts** — click any alert to jump to the file in the tree. Press Escape or click again to unhighlight.
- **Git activity** — commits during the session with diffstat, plus uncommitted changes.
- **Web activity** — URLs accessed via WebFetch, WebSearch, and bash commands.

#### Live mode extras

- **Green "Live" indicator** — shows connection status and human-readable time since last update.
- **Auto-refreshes** via Server-Sent Events when the session file changes (~1s latency).
- **Server stays alive** — watcher pauses after inactivity but server keeps running. Page never dies.
- **Reconnect button** — if server stops, page degrades to static snapshot with a Reconnect button.
- **Server reuse** — running `/session-map --live` again reuses the existing server.
- **DNS rebinding protection** — Host header validation on all requests.

| Indicator | Meaning |
|-----------|---------|
| Green dot, "Live" | Connected, receiving updates |
| Grey text, "Updated 2min 30s ago" | Connected, waiting for changes |
| Yellow dot, "Reconnecting..." | Server unreachable, retrying (3 attempts) |
| Grey dot, "Stopped" + Reconnect button | Server gone, page preserved as static snapshot |

## What it answers

1. **Did Claude touch files it shouldn't?** — sensitive file alerts (`.env`, `*.key`, `*.pem`), scope drift warnings
2. **How much did it change?** — blast radius score (1-10), edit/read counts per file
3. **What websites did it access?** — full URLs from WebFetch, WebSearch, and bash `curl`/`wget` commands
4. **Where did it work?** — file tree grouped by directory, treemap heatmap
5. **What did it commit?** — git commits during the session with diffstat

## How it works

The skill runs a Python 3 script that:

1. Finds the most recent Claude Code session JSONL for your working directory
2. Parses tool calls: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch
3. Extracts file paths from bash commands (redirects, `rm`, `cp`, `mv`, `tee`, `curl -o`)
4. Extracts URLs from bash commands (`curl`, `wget`, etc.)
5. Calculates blast radius based on files touched vs. project size
6. Detects sensitive files and scope drift
7. Collects git commits and uncommitted changes since session start
8. Renders the report (terminal, HTML, or live server)

**Zero dependencies.** No npm, no Bun, no build step. Just Python 3 (pre-installed on macOS and Linux) and a D3.js CDN load for the treemap.

## Security model

### What the parser tracks

| Source | Tracked as |
|--------|-----------|
| `Read`, `Glob`, `Grep` | File read |
| `Write` (new file) | File create |
| `Write` (existing), `Edit`, `MultiEdit` | File write |
| Bash: `> /path`, `tee`, `curl -o`, `cp`/`mv` dst | File write |
| Bash: `rm /path` | File delete |
| Bash: any `/path` argument | File read (fallback) |
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
