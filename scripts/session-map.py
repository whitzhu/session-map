#!/usr/bin/env python3
"""Session map: visualize what Claude touched in this session."""

import sys, json, os, re, subprocess

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SENSITIVE = [
    '.env', '.env.*', '*.key', '*.pem', '*.p12', '*.pfx', '*.secret',
    'credentials', 'secrets/', 'private/', '.ssh/', 'payment/', 'billing/',
    'config/secrets',
]

SAFE_PREFIXES = ['/tmp/', '/var/', '/private/tmp/', '/private/var/']

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

scope_override = None
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == '--scope' and i + 1 < len(args):
        scope_override = os.path.abspath(args[i + 1])
        i += 2
    else:
        i += 1

# ---------------------------------------------------------------------------
# Discover session file
# ---------------------------------------------------------------------------

cwd = os.getcwd()
home = os.path.expanduser('~')
encoded = cwd.replace('/', '-')
project_dir = os.path.join(home, '.claude', 'projects', encoded)

if not os.path.isdir(project_dir):
    print(f'No session found for {cwd}. Have you run a Claude Code session here?')
    sys.exit(1)

jsonl_files = []
for f in os.listdir(project_dir):
    fp = os.path.join(project_dir, f)
    if f.endswith('.jsonl') and os.path.isfile(fp):
        jsonl_files.append((fp, os.path.getmtime(fp)))

if not jsonl_files:
    print(f'No session files in {project_dir}.')
    sys.exit(1)

jsonl_files.sort(key=lambda x: x[1], reverse=True)
session_file = jsonl_files[0][0]
session_id = os.path.basename(session_file).replace('.jsonl', '')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_sensitive(path):
    base = os.path.basename(path)
    norm = path.replace('\\', '/')
    for p in SENSITIVE:
        if p.endswith('/'):
            seg = p[:-1]
            if f'/{seg}/' in norm or norm.endswith(f'/{seg}'):
                return p
        elif p.startswith('*.'):
            if base.endswith(p[1:]):
                return p
        elif '.*' in p:
            prefix = p.split('.*')[0]
            if base == prefix or base.startswith(prefix + '.'):
                return p
        else:
            if base == p:
                return p
            idx = norm.find(f'/{p}')
            if idx >= 0:
                after = idx + len(f'/{p}')
                if after >= len(norm) or norm[after] in ('/', '.'):
                    return p
    return None

def is_real_path(p):
    if not p or not isinstance(p, str):
        return False
    segs = [s for s in p.split('/') if s]
    if not segs:
        return False
    if '*' in p or p.startswith('/dev/'):
        return False
    if len(segs) <= 1 and len(segs[-1]) <= 2:
        return False
    if '.' not in segs[-1] and os.path.isdir(p):
        return False
    return True

def is_safe_dir(p):
    for pfx in SAFE_PREFIXES:
        if p.startswith(pfx):
            return True
    return False

claude_prefix = os.path.join(home, '.claude/')

def track_file(path, activity):
    if not is_real_path(path):
        return
    if path.startswith(claude_prefix):
        return
    if path not in files:
        files[path] = {'reads': 0, 'writes': 0, 'creates': 0, 'deletes': 0}
    files[path][activity] += 1

def plural(n, word):
    return f'{n} {word}' if n == 1 else f'{n} {word}s'

def rel_path(p):
    if p.startswith(cwd + '/'):
        return p[len(cwd) + 1:]
    return p

# ---------------------------------------------------------------------------
# Parse session
# ---------------------------------------------------------------------------

files = {}
tools = {}
web = {}
total_calls = 0

for line in open(session_file, encoding='utf-8', errors='replace'):
    line = line.strip()
    if not line:
        continue
    try:
        record = json.loads(line)
    except Exception:
        continue
    if record.get('type') != 'assistant':
        continue
    content = record.get('message', {}).get('content', [])
    if not isinstance(content, list):
        continue
    for item in content:
        if not isinstance(item, dict) or item.get('type') != 'tool_use':
            continue
        name = item.get('name', '')
        inp = item.get('input', {})
        total_calls += 1
        tools[name] = tools.get(name, 0) + 1

        if name in ('Read', 'Glob', 'Grep'):
            p = inp.get('file_path') or inp.get('path', '')
            track_file(p, 'reads')
        elif name == 'Write':
            p = inp.get('file_path', '')
            if is_real_path(p):
                already = p in files
                exists = not already and os.path.exists(p)
                track_file(p, 'writes' if (already or exists) else 'creates')
        elif name in ('Edit', 'MultiEdit'):
            track_file(inp.get('file_path', ''), 'writes')
        elif name == 'Bash':
            cmd = inp.get('command', '')
            for m in re.finditer(r'>{1,2}\s*((?:/|\.\.?/)[^\s;|&]+)', cmd):
                track_file(m.group(1), 'writes')
            if re.search(r'\brm\b', cmd):
                for m in re.finditer(r'\brm\s+(?:-[a-zA-Z]+\s+)*((?:/|\.\.?/)[^\s;|&]+)', cmd):
                    track_file(m.group(1), 'deletes')
            for m in re.finditer(r'https?://[^\s\'"<>]+', cmd):
                url = m.group(0).rstrip(')')
                try:
                    domain = url.split('//')[1].split('/')[0]
                except Exception:
                    domain = url
                web.setdefault(domain, {'count': 0, 'urls': []})
                web[domain]['count'] += 1
                if url not in web[domain]['urls']:
                    web[domain]['urls'].append(url)
        elif name == 'WebFetch':
            url = inp.get('url', '')
            if url:
                try:
                    domain = url.split('//')[1].split('/')[0]
                except Exception:
                    domain = url
                web.setdefault(domain, {'count': 0, 'urls': []})
                web[domain]['count'] += 1
                if url not in web[domain]['urls']:
                    web[domain]['urls'].append(url)
        elif name == 'WebSearch':
            q = inp.get('query', '')
            if q:
                web.setdefault('web-search', {'count': 0, 'urls': []})
                web['web-search']['count'] += 1
                web['web-search']['urls'].append(q)

# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

try:
    result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=cwd)
    total_project = len([l for l in result.stdout.strip().split('\n') if l]) if result.returncode == 0 else 0
except Exception:
    total_project = 0

if total_project == 0:
    try:
        result = subprocess.run(
            ['find', '.', '-type', 'f', '-not', '-path', '*/node_modules/*', '-not', '-path', '*/.*'],
            capture_output=True, text=True, cwd=cwd
        )
        total_project = len([l for l in result.stdout.strip().split('\n') if l])
    except Exception:
        total_project = 1

if total_project == 0:
    total_project = 1

touched = len(files)
raw_score = round((touched / total_project) * 10)
score = max(1, min(10, raw_score))

if score <= 3:
    desc = 'Minimal activity'
elif score <= 6:
    desc = 'Moderate activity'
elif score <= 8:
    desc = 'Significant activity'
else:
    desc = 'High activity'

# ---------------------------------------------------------------------------
# Sensitive files
# ---------------------------------------------------------------------------

sensitive_files = []
for p in files:
    match = is_sensitive(p)
    if match:
        sensitive_files.append(p)

# ---------------------------------------------------------------------------
# Scope drift
# ---------------------------------------------------------------------------

scope = scope_override or cwd
if not scope.endswith('/'):
    scope += '/'

drift_files = []
for p in files:
    resolved = p if p.startswith('/') else os.path.join(cwd, p)
    if not resolved.startswith(scope) and resolved != scope.rstrip('/'):
        if not is_safe_dir(resolved) and not resolved.startswith(claude_prefix):
            drift_files.append(p)

# ---------------------------------------------------------------------------
# Render: blast radius box
# ---------------------------------------------------------------------------

lines = []
box_w = 36
lines.append('╔' + '═' * box_w + '╗')
score_text = f'📊 BLAST RADIUS: {score}/10'
score_pad = box_w - 2 - len(score_text)
desc_pad = box_w - 2 - len(desc) - 1
lines.append('║ ' + score_text + ' ' * max(0, score_pad) + '║')
lines.append('║  ' + desc + ' ' * max(0, desc_pad) + ' ║')
lines.append('╚' + '═' * box_w + '╝')
lines.append('')

# ---------------------------------------------------------------------------
# Render: modified files list
# ---------------------------------------------------------------------------

if not files:
    lines.append('No file activity found in this session.')
else:
    sorted_files = sorted(files.items(), key=lambda x: (x[1]['writes'] + x[1]['creates'] + x[1]['deletes']) * 3 + x[1]['reads'], reverse=True)

    lines.append('📁 Files Touched:')
    for p, act in sorted_files:
        edits = act['writes'] + act['creates'] + act['deletes']
        reads = act['reads']
        sens = is_sensitive(p)

        if sens:
            sym = '⚠'
        elif act['creates'] > 0:
            sym = '+'
        elif act['deletes'] > 0:
            sym = '-'
        elif act['writes'] > 0:
            sym = '●'
        else:
            sym = '○'

        display = rel_path(p)
        parts = []
        if edits > 0:
            parts.append(plural(edits, 'edit'))
        if reads > 0:
            parts.append(plural(reads, 'read'))
        stats = ', '.join(parts)

        lines.append(f'  {sym} {display}    {stats}')

    lines.append('')

    if sensitive_files:
        lines.append('  ⚠️  SENSITIVE FILES:')
        for p in sensitive_files:
            act = files[p]
            if act['creates'] > 0:
                access = 'created'
            elif act['writes'] > 0 or act['deletes'] > 0:
                access = 'modified'
            else:
                access = 'read'
            lines.append(f'     {rel_path(p)} ({access})')
        lines.append('')

    if drift_files:
        lines.append('  ⚡ SCOPE DRIFT:')
        for p in drift_files:
            lines.append(f'     {p}')
        lines.append('')

# ---------------------------------------------------------------------------
# Render: file tree
# ---------------------------------------------------------------------------

if files:
    project_name = os.path.basename(cwd)

    tree = {}
    for p in files:
        rp = rel_path(p)
        parts = rp.split('/')
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part + '/', {})
        node[parts[-1]] = files[p]

    def render_tree(node, prefix, is_root_call=False):
        keys = sorted(node.keys(), key=lambda k: (not k.endswith('/'), k))
        for i, key in enumerate(keys):
            is_last = (i == len(keys) - 1)
            connector = '└── ' if is_last else '├── '
            child_prefix = '    ' if is_last else '│   '
            val = node[key]

            if isinstance(val, dict) and any(isinstance(v, dict) for v in val.values()):
                lines.append(f'{prefix}{connector}{key}')
                render_tree(val, prefix + child_prefix)
            else:
                act = val
                edits = act['writes'] + act['creates'] + act['deletes']
                reads = act['reads']
                full_path = next((p for p in files if rel_path(p).endswith(key)), key)
                sens = is_sensitive(full_path)
                if sens:
                    sym = '⚠'
                elif act.get('creates', 0) > 0:
                    sym = '+'
                elif act.get('deletes', 0) > 0:
                    sym = '-'
                elif act.get('writes', 0) > 0:
                    sym = '●'
                else:
                    sym = '○'

                parts = []
                if edits > 0:
                    parts.append(plural(edits, 'edit'))
                if reads > 0:
                    parts.append(plural(reads, 'read'))
                stats = f'  ({", ".join(parts)})' if parts else ''
                lines.append(f'{prefix}{connector}{sym} {key}{stats}')

    lines.append('🌳 File Tree:')
    lines.append(f'  {project_name}/')
    render_tree(tree, '  ')
    lines.append('')

# ---------------------------------------------------------------------------
# Render: web activity
# ---------------------------------------------------------------------------

if web:
    total_web = sum(v['count'] for v in web.values())
    domains = len(web)
    lines.append(f'🌐 Web Activity ({plural(domains, "domain")}, {plural(total_web, "request")}):')

    if 'web-search' in web:
        ws = web['web-search']
        lines.append(f'  Searches ({plural(ws["count"], "query")}):')
        for q in ws['urls']:
            lines.append(f'    🔍 "{q}"')

    for domain, info in sorted(
        ((d, v) for d, v in web.items() if d != 'web-search'),
        key=lambda x: x[1]['count'], reverse=True
    ):
        lines.append(f'  {domain} ({plural(info["count"], "request")}):')
        for url in info['urls']:
            lines.append(f'    → {url}')

    lines.append('')

# ---------------------------------------------------------------------------
# Render: tool breakdown
# ---------------------------------------------------------------------------

if tools:
    sorted_tools = sorted(tools.items(), key=lambda x: x[1], reverse=True)
    max_count = sorted_tools[0][1] if sorted_tools else 1

    lines.append(f'🔧 Tool Calls ({total_calls}):')
    for name, count in sorted_tools:
        bar_len = max(1, round((count / max_count) * 20))
        bar = '█' * bar_len
        lines.append(f'  {name:<14} {bar} {count}')
    lines.append('')

# ---------------------------------------------------------------------------
# Render: footer
# ---------------------------------------------------------------------------

sid = session_id[:8] if len(session_id) > 8 else session_id
lines.append('─' * 50)
lines.append(f'Session: {sid}  |  Calls: {total_calls}  |  Files: {touched}')

print('\n'.join(lines))
