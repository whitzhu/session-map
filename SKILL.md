---
name: session-map
description: What did Claude touch? Zero-dependency session report — blast radius score, file tree, sensitive file alerts, scope drift detection.
---

# /session-map

Visualize what Claude touched in this session — blast radius, file tree, sensitive accesses, and scope drift. Zero dependencies.

## Usage

```
/session-map              # Inline terminal report (default)
/session-map --scope src/ # Check for scope drift outside src/
```

## Instructions for Claude

When the user invokes `/session-map`:

1. Note any arguments (e.g., `--scope src/`).
2. Run the bash command below. If `--scope` was passed, append it: `--scope src/`
3. Do NOT add commentary or re-interpret the output. The Bash tool output is sufficient.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/session-map.py $ARGUMENTS
```

If the command fails with `python3: command not found`, tell the user: "This skill requires Python 3 (pre-installed on macOS and most Linux). Install it from https://python.org"

## Error handling

- If the script prints "No session found": the user hasn't run Claude Code in this directory.
- If blast radius shows 0 files: the session may be very new or empty.

## Installation

```bash
npx skills add whitzhu/session-map
```

No dependencies beyond `python3` (pre-installed on macOS and Linux).
