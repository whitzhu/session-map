---
name: session-map
description: What did Claude touch? Zero-dependency session report — blast radius score, file tree, sensitive file alerts, scope drift detection.
---

# /session-map

Visualize what Claude touched in this session — blast radius, file tree, sensitive accesses, and scope drift. Zero dependencies beyond Python 3.

## Usage

```
/session-map                      # Inline terminal report (default)
/session-map --html               # Open interactive HTML report in browser
/session-map --live               # Live-updating dashboard in browser
/session-map --live --timeout 0   # Live mode, never auto-shutdown
/session-map --live --timeout 600 # Auto-shutdown after 10min idle
/session-map --scope src/         # Check for scope drift outside src/
```

### Modes

- **Terminal** (default): Inline text report shown in the Claude session.
- **HTML** (`--html`): Generates a static interactive HTML report with D3 treemap heatmap, collapsible file tree, tool breakdown, and scope drift visualization. Opens in browser. Shows "Static snapshot" indicator.
- **Live** (`--live`): Starts a local HTTP server that auto-updates the HTML report every second as Claude works. Opens in browser. Shows green "Live" indicator. Keep it on another monitor to watch Claude in real time. Auto-shuts down after 120s of inactivity (configurable with `--timeout`). Reuses existing server if called again in the same directory.

Flags can be combined: `/session-map --live --scope src/`

## Instructions for Claude

When the user invokes `/session-map`:

1. Note any arguments (e.g., `--scope src/`, `--html`, `--live`).
2. Run the bash command below, passing all arguments.
3. For `--html` and `--live` modes, the script handles opening the browser. After running, tell the user it opened.
4. For terminal mode (no flags), do NOT add commentary. The Bash output is sufficient.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/session-map.py $ARGUMENTS
```

If the command fails with `python3: command not found`, tell the user: "This skill requires Python 3 (pre-installed on macOS and most Linux). Install it from https://python.org"

Note: `--live` mode runs a blocking server. It will run in the background. The user can stop it with Ctrl+C or by closing the terminal.

## Error handling

- If the script prints "No session found": the user hasn't run Claude Code in this directory.
- If blast radius shows 0 files: the session may be very new or empty.

## Installation

```bash
npx skills add whitzhu/session-map
```

No dependencies beyond `python3` (pre-installed on macOS and Linux). The HTML report loads D3.js from CDN for the treemap heatmap; everything else works offline.
