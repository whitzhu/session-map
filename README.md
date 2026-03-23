# session-map

What did Claude touch? A zero-dependency Claude Code skill that shows you exactly what happened in your session — blast radius score, file tree, sensitive file alerts, scope drift warnings, and web activity tracking.

![Example output](https://github.com/user-attachments/assets/166c5c73-5644-4a06-a013-7613852ae52f)

## Install

```bash
npx skills add whitzhu/session-map
```

Or manually:

```bash
mkdir -p ~/.claude/skills/session-map
curl -fsSL https://raw.githubusercontent.com/whitzhu/session-map/main/SKILL.md \
  -o ~/.claude/skills/session-map/SKILL.md
```

## Usage

In any Claude Code session:

```
/session-map              # Session report
/session-map --scope src/ # Flag files outside src/
```

## What it shows

```
╔══════════════════════════════════╗
║  BLAST RADIUS: 5/10              ║
║  Moderate activity               ║
╚══════════════════════════════════╝

Modified Files:
  ● src/parser.ts    5 edits, 4 reads
  ● src/index.ts     7 edits, 1 read
  ○ src/terminal.ts  1 read

  ⚠ SENSITIVE FILES:
     .env (read)

  ⚡ SCOPE DRIFT:
     /etc/hosts

File Tree:
  my-project/
  ├── src/
  │   ├── ● parser.ts  (5 edits, 4 reads)
  │   ├── ● index.ts  (7 edits, 1 read)
  │   └── ○ terminal.ts  (1 read)
  └── ⚠ .env  (1 read)

Web Activity (1 domain, 2 requests):
  unpkg.com (2 requests):
    → https://unpkg.com/d3@7/dist/d3.min.js

Tool Calls (65):
  Read           ████████████████████ 20
  Edit           ████████████████ 16
  Bash           █████████ 9

──────────────────────────────────────────────────
Session: 344330a9  |  Calls: 65  |  Files: 13
```

## What it answers (in 2 seconds)

1. **Did Claude touch files it shouldn't?** — sensitive file alerts (`.env`, `*.key`, `*.pem`), scope drift warnings
2. **How much did it change?** — blast radius score (1–10), edit/read counts per file
3. **What websites did it access?** — full URLs from WebFetch, WebSearch, and bash `curl`/`wget` commands
4. **Where did it work?** — file tree grouped by directory

## How it works

The skill runs a Python 3 script (pre-installed on macOS and Linux) that:

1. Finds the most recent Claude Code session JSONL for your working directory
2. Parses tool calls: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch
3. Extracts file paths from bash commands (redirects, `rm`, `cp`, `mv`, `tee`, `curl -o`)
4. Extracts URLs from bash commands (`curl`, `wget`, etc.)
5. Calculates blast radius based on files touched vs. project size
6. Detects sensitive files and scope drift
7. Renders a deterministic report that Claude pastes inline

**Zero dependencies.** No npm install, no Bun, no build step. Just a single SKILL.md file.

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
- **Ghost writes**: Files written via Bash that are never read back don't appear at all

These are inherent limitations of session-log parsing. Filesystem-level monitoring is out of scope.

### Sensitive file patterns

`.env`, `.env.*`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `*.secret`, `credentials`, `secrets/`, `private/`, `.ssh/`, `payment/`, `billing/`, `config/secrets`

## Requirements

- Python 3 (pre-installed on macOS since Catalina and most Linux distributions)
- Claude Code

## License

MIT
