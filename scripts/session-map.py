#!/usr/bin/env python3
"""Session map: visualize what Claude touched in this session."""

import sys, json, os, re, subprocess, math, base64, time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SENSITIVE = [
    '.env', '.env.*', '*.key', '*.pem', '*.p12', '*.pfx', '*.secret',
    'credentials', 'secrets/', 'private/', '.ssh/', 'payment/', 'billing/',
    'config/secrets',
]

SAFE_PREFIXES = ['/tmp/', '/var/', '/private/tmp/', '/private/var/']

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

scope_override = None
mode = 'terminal'  # terminal | html | live
idle_timeout = 600  # seconds; 0 = never auto-shutdown
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == '--scope' and i + 1 < len(args):
        scope_override = os.path.abspath(args[i + 1])
        i += 2
    elif args[i] == '--html':
        mode = 'html'
        i += 1
    elif args[i] == '--live':
        mode = 'live'
        i += 1
    elif args[i] == '--timeout' and i + 1 < len(args):
        try:
            idle_timeout = int(args[i + 1])
            if idle_timeout < 0:
                raise ValueError
        except ValueError:
            print(f'--timeout must be a non-negative integer, got: {args[i + 1]}')
            sys.exit(1)
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

def find_latest_session():
    jsonl_files = []
    for f in os.listdir(project_dir):
        fp = os.path.join(project_dir, f)
        if f.endswith('.jsonl') and os.path.isfile(fp):
            jsonl_files.append((fp, os.path.getmtime(fp)))
    if not jsonl_files:
        return None, None
    jsonl_files.sort(key=lambda x: x[1], reverse=True)
    fp = jsonl_files[0][0]
    return fp, os.path.basename(fp).replace('.jsonl', '')

session_file, session_id = find_latest_session()
if not session_file:
    print(f'No session files in {project_dir}.')
    sys.exit(1)

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

def plural(n, word):
    return f'{n} {word}' if n == 1 else f'{n} {word}s'

def rel_path(p):
    if p.startswith(cwd + '/'):
        return p[len(cwd) + 1:]
    return p

def escape_html(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

def file_sym(act):
    if act.get('isSensitive'):
        return '\u26a0'
    if act.get('creates', 0) > 0:
        return '+'
    if act.get('deletes', 0) > 0:
        return '-'
    if act.get('writes', 0) > 0:
        return '\u25cf'
    return '\u25cb'

# ---------------------------------------------------------------------------
# Parse session
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bash path extraction (ported from session-map-visualizer/src/parser.ts)
# ---------------------------------------------------------------------------

_PATH_PREFIX = r'(?:/|\.\.?/)'
_PATH_CHAR = r'[^\s;|&><\'"]+'

def extract_bash_paths(command):
    """Extract file paths from a bash command with write/delete classification."""
    seen = {}  # path -> {path, write, delete}

    def add(raw, is_write, is_delete):
        p = raw.replace("'", '').replace('"', '').replace('(', '').replace(')', '').strip()
        if not p or p == '/dev/null' or p.startswith('/dev/'):
            return
        if p in seen:
            if is_write:
                seen[p]['write'] = True
            if is_delete:
                seen[p]['delete'] = True
            return
        seen[p] = {'path': p, 'write': is_write, 'delete': is_delete}

    # 1. Redirect targets: > /path, >> /path (WRITE)
    for m in re.finditer(r'>{1,2}\s*(' + _PATH_PREFIX + _PATH_CHAR + ')', command):
        add(m.group(1), True, False)

    # 2. tee targets: tee [-a] /path (WRITE)
    for m in re.finditer(r'\btee\s+(?:-[a-zA-Z]\s+)*(' + _PATH_PREFIX + _PATH_CHAR + ')', command):
        add(m.group(1), True, False)

    # 3. curl -o /path, wget -O /path (WRITE)
    for m in re.finditer(r'\bcurl\b[^;|&]*?\s-o\s+(' + _PATH_PREFIX + _PATH_CHAR + ')', command):
        add(m.group(1), True, False)
    for m in re.finditer(r'\bwget\b[^;|&]*?\s-O\s+(' + _PATH_PREFIX + _PATH_CHAR + ')', command):
        add(m.group(1), True, False)

    # 4. rm [-rf] /path (DELETE)
    if re.search(r'\brm\b', command):
        for m in re.finditer(r'\brm\s+(?:-[a-zA-Z]+\s+)*(' + _PATH_PREFIX + r'[^\s;|&><\'"]+)', command):
            add(m.group(1), False, True)

    # 5. cp/mv: last path arg is WRITE, earlier paths are READ
    if re.search(r'\b(?:cp|mv)\b', command):
        cp_match = re.search(r'\b(?:cp|mv)\s+(?:-[a-zA-Z]+\s+)*(.*?)(?:[;|&]|$)', command)
        if cp_match:
            paths = re.findall(r'(' + _PATH_PREFIX + r'[^\s;|&><\'"]+)', cp_match.group(1))
            if len(paths) >= 2:
                for p in paths[:-1]:
                    add(p, False, False)
                add(paths[-1], True, False)

    # 6. Remaining paths not yet seen -> default to READ
    for m in re.finditer(r'(?:^|\s)(' + _PATH_PREFIX + _PATH_CHAR + ')', command):
        p = m.group(1).replace("'", '').replace('"', '').strip()
        if p and p not in seen:
            add(p, False, False)

    return list(seen.values())


def parse_session(sf):
    files = {}
    tools = {}
    web = {}
    total_calls = 0
    first_user_message = None
    session_start_ts = None

    def track_file(path, activity):
        if not is_real_path(path):
            return
        if path.startswith(claude_prefix):
            return
        if path not in files:
            sens = None if is_safe_dir(path) else is_sensitive(path)
            files[path] = {
                'reads': 0, 'writes': 0, 'creates': 0, 'deletes': 0,
                'isSensitive': bool(sens), 'sensitiveReason': sens or None,
            }
        files[path][activity] += 1

    def track_web(domain, url):
        web.setdefault(domain, {'count': 0, 'urls': []})
        web[domain]['count'] += 1
        if url not in web[domain]['urls']:
            web[domain]['urls'].append(url)

    def extract_domain(url):
        try:
            return url.split('//')[1].split('/')[0]
        except Exception:
            return url

    with open(sf, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue

            # Capture session start time
            if session_start_ts is None and record.get('timestamp'):
                session_start_ts = record['timestamp']

            # Extract first user message as session topic
            if record.get('type') == 'user' and first_user_message is None:
                msg = record.get('message', {})
                if isinstance(msg, dict):
                    content = msg.get('content', '')
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get('type') == 'text':
                                first_user_message = c.get('text', '')
                                break
                    elif isinstance(content, str):
                        first_user_message = content

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
                    bash_paths = extract_bash_paths(cmd)
                    for bp in bash_paths:
                        if bp['delete']:
                            track_file(bp['path'], 'deletes')
                        elif bp['write']:
                            track_file(bp['path'], 'writes')
                        else:
                            track_file(bp['path'], 'reads')
                    for m in re.finditer(r'https?://[^\s\'"<>]+', cmd):
                        url = m.group(0).rstrip(')')
                        track_web(extract_domain(url), url)
                elif name == 'WebFetch':
                    url = inp.get('url', '')
                    if url:
                        track_web(extract_domain(url), url)
                elif name == 'WebSearch':
                    q = inp.get('query', '')
                    if q:
                        track_web('web-search', q)

    # Truncate to first line, cap at 80 chars for display
    session_topic = None
    if first_user_message:
        topic = first_user_message.strip().split('\n')[0]
        session_topic = (topic[:77] + '...') if len(topic) > 80 else topic

    return files, tools, web, total_calls, session_topic, session_start_ts

# ---------------------------------------------------------------------------
# Git activity
# ---------------------------------------------------------------------------

def get_git_activity(since_ts):
    """Get commits and uncommitted changes since the session started."""
    commits = []
    uncommitted = []

    # Commits since session start
    if since_ts:
        try:
            result = subprocess.run(
                ['git', 'log', f'--since={since_ts}', '--format=%H%n%s%n%an%n%aI%n---'],
                capture_output=True, text=True, cwd=cwd
            )
            if result.returncode == 0 and result.stdout.strip():
                chunks = result.stdout.strip().split('---\n')
                for chunk in chunks:
                    chunk = chunk.strip().rstrip('---').strip()
                    if not chunk:
                        continue
                    parts = chunk.split('\n')
                    if len(parts) >= 4:
                        sha, msg, author, date = parts[0], parts[1], parts[2], parts[3]
                        # Get diffstat for this commit
                        stat_result = subprocess.run(
                            ['git', 'diff', '--shortstat', f'{sha}~1..{sha}'],
                            capture_output=True, text=True, cwd=cwd
                        )
                        stat = stat_result.stdout.strip() if stat_result.returncode == 0 else ''
                        commits.append({
                            'sha': sha[:8],
                            'message': msg,
                            'author': author,
                            'date': date,
                            'stat': stat,
                        })
        except Exception:
            pass

    # Uncommitted changes
    try:
        result = subprocess.run(
            ['git', 'diff', '--stat', 'HEAD'],
            capture_output=True, text=True, cwd=cwd
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line and '|' in line:
                    uncommitted.append(line)

        # Also staged changes
        result2 = subprocess.run(
            ['git', 'diff', '--stat', '--cached'],
            capture_output=True, text=True, cwd=cwd
        )
        if result2.returncode == 0 and result2.stdout.strip():
            for line in result2.stdout.strip().split('\n'):
                line = line.strip()
                if line and '|' in line and line not in uncommitted:
                    uncommitted.append(line)
    except Exception:
        pass

    return commits, uncommitted

# ---------------------------------------------------------------------------
# Blast radius calculation
# ---------------------------------------------------------------------------

def calc_blast_radius(files, cached_project_count=None):
    if cached_project_count is not None:
        total_project = cached_project_count
    else:
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

    sensitive = [p for p, act in files.items() if act.get('isSensitive')]

    scope_val = scope_override or cwd
    if not scope_val.endswith('/'):
        scope_val += '/'
    drift = []
    for p in files:
        resolved = p if p.startswith('/') else os.path.join(cwd, p)
        if not resolved.startswith(scope_val) and resolved != scope_val.rstrip('/'):
            if not is_safe_dir(resolved) and not resolved.startswith(claude_prefix):
                drift.append(p)

    return score, total_project, touched, sensitive, drift, scope_val

# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _make_activity_entry(path, act):
    """Build the activity dict used by both file list and treemap."""
    return {
        'path': path,
        'reads': act['reads'],
        'writes': act['writes'],
        'creates': act['creates'],
        'deletes': act['deletes'],
        'isSensitive': act.get('isSensitive', False),
        'sensitiveReason': act.get('sensitiveReason'),
    }

def build_file_tree(files):
    """Build a nested tree structure for the D3 treemap."""
    root = {'name': 'root', 'children': []}

    for file_path, activity in files.items():
        parts = [s for s in file_path.split('/') if s]
        current = root

        for idx, part in enumerate(parts):
            is_leaf = idx == len(parts) - 1
            if is_leaf:
                if 'children' not in current:
                    current['children'] = []
                entry = _make_activity_entry(file_path, activity)
                raw = activity['reads'] + activity['writes'] * 2 + activity['creates'] * 3 + activity['deletes'] * 3
                current['children'].append({
                    'name': part,
                    'path': file_path,
                    'activity': entry,
                    'value': max(1, math.sqrt(raw)),
                })
            else:
                if 'children' not in current:
                    current['children'] = []
                child = None
                for c in current['children']:
                    if c.get('name') == part and 'children' in c:
                        child = c
                        break
                if not child:
                    child = {'name': part, 'children': []}
                    current['children'].append(child)
                current = child

    return root

def serialize_session_data(files, tools, web, total_calls, score, total_project, touched, sensitive, drift, scope_val, topic=None, commits=None, uncommitted=None):
    """Serialize session data into the format expected by the HTML template."""
    file_activity = [_make_activity_entry(path, act) for path, act in files.items()]

    web_activity = []
    for domain, info in web.items():
        web_activity.append({
            'domain': domain,
            'urls': info['urls'],
            'count': info['count'],
        })

    return {
        'sessionId': session_id,
        'sessionFile': session_file,
        'cwd': cwd,
        'totalToolCalls': total_calls,
        'malformedLines': 0,
        'fileActivity': file_activity,
        'webActivity': web_activity,
        'toolBreakdown': tools,
        'homeDir': home,
        'blast': {
            'score': score,
            'totalProjectFiles': total_project,
            'touchedFiles': touched,
            'sensitiveFiles': sensitive,
            'scopeDriftFiles': drift,
            'inferredScope': scope_val.rstrip('/'),
        },
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'tree': build_file_tree(files),
        'sessionTopic': topic,
        'gitCommits': commits or [],
        'gitUncommitted': uncommitted or [],
    }

def blast_color_var(score):
    if score <= 3:
        return 'var(--created)'
    if score <= 6:
        return 'var(--modified)'
    return 'var(--deleted)'

def blast_desc(score):
    if score <= 3:
        return 'Minimal'
    if score <= 6:
        return 'Moderate'
    if score <= 8:
        return 'Significant'
    return 'High'

def generate_html(files, tools, web, total_calls, score, total_project, touched, sensitive, drift, scope_val, live=False, topic=None, commits=None, uncommitted=None, template=None):
    """Generate the HTML report by substituting data into the template."""
    if template is None:
        with open(os.path.join(SCRIPT_DIR, 'template.html'), 'r') as f:
            template = f.read()

    data = serialize_session_data(files, tools, web, total_calls, score, total_project, touched, sensitive, drift, scope_val, topic=topic, commits=commits, uncommitted=uncommitted)
    data_json = json.dumps(data, default=str)
    data_b64 = base64.b64encode(data_json.encode('utf-8')).decode('ascii')

    sid_display = escape_html(session_id[:8] + '...') if len(session_id) > 8 else escape_html(session_id)

    html = template.replace('{{DATA_B64}}', data_b64)
    html = html.replace('{{SESSION_ID}}', sid_display)
    html = html.replace('{{BLAST_COLOR}}', escape_html(blast_color_var(score)))
    html = html.replace('{{BLAST_DESC}}', escape_html(blast_desc(score)))
    html = html.replace('{{CWD}}', escape_html(cwd))
    html = html.replace('{{GENERATED_AT}}', escape_html(data['generatedAt']))

    if live:
        # Inject the flag that activates SSE in the client JS
        html = html.replace('var SESSION_DATA =', 'window.SESSION_MAP_LIVE = true;\nvar SESSION_DATA =')

    return html

# ---------------------------------------------------------------------------
# Live server (stdlib only)
# ---------------------------------------------------------------------------

# Idle timeout is set via --timeout flag (default 120s, 0 = disabled)

def _pidfile_path():
    """Return path to the PID file for the current project directory."""
    return os.path.join(project_dir, '.session-map-live.pid')

def _read_pidfile():
    """Read PID file. Returns (pid, port) or (None, None)."""
    pf = _pidfile_path()
    if not os.path.exists(pf):
        return None, None
    try:
        with open(pf) as f:
            data = json.load(f)
        return data.get('pid'), data.get('port')
    except Exception:
        return None, None

def _write_pidfile(pid, port):
    pf = _pidfile_path()
    with open(pf, 'w') as f:
        json.dump({'pid': pid, 'port': port, 'cwd': cwd, 'session': session_file}, f)

def _remove_pidfile():
    pf = _pidfile_path()
    try:
        os.unlink(pf)
    except OSError:
        pass

def _is_process_alive(pid):
    """Check if a process with given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

def _check_existing_server():
    """Check if a live server is already running for this project.
    Returns the URL if reusable, None otherwise."""
    pid, port = _read_pidfile()
    if pid is None:
        return None
    if not _is_process_alive(pid):
        _remove_pidfile()
        return None
    # Server is alive — verify it's actually responding
    try:
        import urllib.request
        resp = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2)
        resp.read()
        return f'http://127.0.0.1:{port}'
    except Exception:
        # Process exists but not responding on that port — stale
        _remove_pidfile()
        return None

def start_live_server(files, tools, web, total_calls, score, total_project, touched, sensitive, drift, scope_val, topic=None, commits=None, uncommitted=None):
    """Start a live-updating HTTP server using only Python stdlib."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading, signal

    # Check for existing server first
    existing_url = _check_existing_server()
    if existing_url:
        print(f'Live server already running: {existing_url}')
        print('Reusing existing server (refresh the browser tab).')
        # Open the browser to the existing server
        open_cmd = 'xdg-open' if sys.platform == 'linux' else 'open'
        try:
            subprocess.Popen([open_cmd, existing_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        return

    # Cache template at startup — no need to re-read from disk every tick
    template_path = os.path.join(SCRIPT_DIR, 'template.html')
    with open(template_path, 'r') as f:
        cached_template = f.read()

    current_html = [generate_html(files, tools, web, total_calls, score, total_project, touched, sensitive, drift, scope_val, live=True, topic=topic, commits=commits, uncommitted=uncommitted, template=cached_template)]
    subscribers = set()
    subscribers_lock = threading.Lock()
    shutdown_event = threading.Event()
    session_ended = [False]
    watcher_idle = [False]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def do_GET(self):
            # DNS rebinding protection — reject requests with unexpected Host headers
            host = (self.headers.get('Host') or '').split(':')[0]
            if host not in ('127.0.0.1', 'localhost', ''):
                self.send_response(421)
                self.end_headers()
                return

            # Strip query string for path matching
            path = self.path.split('?')[0]

            if path == '/':
                content = current_html[0].encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif path == '/events':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.send_header('X-Accel-Buffering', 'no')
                self.end_headers()

                event = threading.Event()
                with subscribers_lock:
                    subscribers.add(event)
                try:
                    while not shutdown_event.is_set():
                        fired = event.wait(timeout=25)
                        if fired:
                            event.clear()
                            try:
                                if session_ended[0]:
                                    self.wfile.write(b'event: session-ended\ndata: {}\n\n')
                                else:
                                    self.wfile.write(f'data: {{"timestamp": {int(time.time())}}}\n\n'.encode())
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                break
                            if session_ended[0]:
                                break
                        else:
                            try:
                                self.wfile.write(b': keepalive\n\n')
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                break
                except Exception:
                    pass
                finally:
                    with subscribers_lock:
                        subscribers.discard(event)
            else:
                self.send_response(404)
                self.end_headers()

    class ThreadedHTTPServer(HTTPServer):
        daemon_threads = True

        def server_bind(self):
            import socket as _socket
            self.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
            super().server_bind()

        def process_request(self, request, client_address):
            t = threading.Thread(target=self._handle_request, args=(request, client_address), daemon=True)
            t.start()

        def _handle_request(self, request, client_address):
            try:
                self.finish_request(request, client_address)
            except Exception:
                pass
            try:
                self.shutdown_request(request)
            except Exception:
                pass

    # Find available port
    port = 7377
    server = None
    for p in range(7377, 7388):
        try:
            server = ThreadedHTTPServer(('127.0.0.1', p), Handler)
            port = p
            break
        except OSError:
            continue

    if not server:
        print('No available ports in range 7377-7387. Kill other session-map servers or use a different port range.')
        sys.exit(1)

    _write_pidfile(os.getpid(), port)

    cached_total_project = [total_project]
    last_mtime = [os.path.getmtime(session_file)]
    last_change_time = [time.time()]

    def notify_subscribers():
        with subscribers_lock:
            for event in subscribers:
                event.set()

    def watch_file():
        while not shutdown_event.is_set():
            time.sleep(1)
            try:
                if not os.path.exists(session_file):
                    print('Session file removed.')
                    session_ended[0] = True
                    _remove_pidfile()
                    notify_subscribers()
                    return

                mtime = os.path.getmtime(session_file)
                if mtime > last_mtime[0]:
                    last_mtime[0] = mtime
                    last_change_time[0] = time.time()

                    if watcher_idle[0]:
                        watcher_idle[0] = False
                        print('Session activity resumed.')

                    f, t, w, tc, _topic, _ts = parse_session(session_file)
                    s, tp, tch, sens, dr, sv = calc_blast_radius(f, cached_project_count=cached_total_project[0])
                    gc, gu = get_git_activity(_ts)
                    current_html[0] = generate_html(f, t, w, tc, s, tp, tch, sens, dr, sv, live=True, commits=gc, uncommitted=gu, template=cached_template)
                    notify_subscribers()

                elif idle_timeout > 0 and not watcher_idle[0]:
                    idle_seconds = time.time() - last_change_time[0]
                    if idle_seconds > idle_timeout:
                        print(f'No session activity for {idle_timeout}s. Pausing watcher (server stays alive).')
                        watcher_idle[0] = True
            except Exception as e:
                print(f'[session-map] watcher error: {e}', file=sys.stderr)

    watcher = threading.Thread(target=watch_file, daemon=True)
    watcher.start()

    url = f'http://127.0.0.1:{port}'
    open_cmd = 'xdg-open' if sys.platform == 'linux' else 'open'
    try:
        subprocess.Popen([open_cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    print(f'Live mode: {url}')
    print('Server stays alive until Ctrl+C. Watcher pauses after inactivity, resumes on new activity.')

    # Signal handling — set event and let main thread handle shutdown
    def cleanup(sig, frame):
        shutdown_event.set()

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        while not shutdown_event.is_set():
            server.handle_request()
    finally:
        _remove_pidfile()
        server.server_close()

# ===========================================================================
# Main
# ===========================================================================

files, tools, web, total_calls, session_topic, session_start = parse_session(session_file)
git_commits, git_uncommitted = get_git_activity(session_start)
score, total_project, touched, sensitive_files, drift_files, scope_val = calc_blast_radius(files)

if mode == 'html':
    html = generate_html(files, tools, web, total_calls, score, total_project, touched, sensitive_files, drift_files, scope_val, topic=session_topic, commits=git_commits, uncommitted=git_uncommitted)
    out_path = f'/tmp/session-map-{int(time.time())}.html'
    with open(out_path, 'w') as f:
        f.write(html)
    open_cmd = 'xdg-open' if sys.platform == 'linux' else 'open'
    try:
        subprocess.Popen([open_cmd, out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f'Opened {out_path}')
    except Exception:
        print(f'Report ready: file://{out_path}')
    sys.exit(0)

if mode == 'live':
    start_live_server(files, tools, web, total_calls, score, total_project, touched, sensitive_files, drift_files, scope_val, topic=session_topic, commits=git_commits, uncommitted=git_uncommitted)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Terminal output (default)
# ---------------------------------------------------------------------------

desc = 'Minimal activity' if score <= 3 else 'Moderate activity' if score <= 6 else 'Significant activity' if score <= 8 else 'High activity'

lines = []
box_w = 36
lines.append('\u2554' + '\u2550' * box_w + '\u2557')
score_text = f'\U0001f4ca BLAST RADIUS: {score}/10'
score_pad = box_w - 2 - len(score_text)
desc_pad = box_w - 2 - len(desc) - 1
lines.append('\u2551 ' + score_text + ' ' * max(0, score_pad) + '\u2551')
lines.append('\u2551  ' + desc + ' ' * max(0, desc_pad) + ' \u2551')
lines.append('\u255a' + '\u2550' * box_w + '\u255d')
lines.append('')

if not files:
    lines.append('No file activity found in this session.')
else:
    sorted_files = sorted(files.items(), key=lambda x: (x[1]['writes'] + x[1]['creates'] + x[1]['deletes']) * 3 + x[1]['reads'], reverse=True)

    lines.append('\U0001f4c1 Files Touched:')
    for p, act in sorted_files:
        edits = act['writes'] + act['creates'] + act['deletes']
        reads = act['reads']
        sym = file_sym(act)
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
        lines.append('  \u26a0\ufe0f  SENSITIVE FILES:')
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
        lines.append('  \u26a1 SCOPE DRIFT:')
        for p in drift_files:
            lines.append(f'     {p}')
        lines.append('')

# File tree
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
            connector = '\u2514\u2500\u2500 ' if is_last else '\u251c\u2500\u2500 '
            child_prefix = '    ' if is_last else '\u2502   '
            val = node[key]

            if isinstance(val, dict) and any(isinstance(v, dict) for v in val.values()):
                lines.append(f'{prefix}{connector}{key}')
                render_tree(val, prefix + child_prefix)
            else:
                act = val
                edits = act['writes'] + act['creates'] + act['deletes']
                reads = act['reads']
                sym = file_sym(act)

                parts = []
                if edits > 0:
                    parts.append(plural(edits, 'edit'))
                if reads > 0:
                    parts.append(plural(reads, 'read'))
                stats = f'  ({", ".join(parts)})' if parts else ''
                lines.append(f'{prefix}{connector}{sym} {key}{stats}')

    lines.append('\U0001f333 File Tree:')
    lines.append(f'  {project_name}/')
    render_tree(tree, '  ')
    lines.append('')

# Web activity
if web:
    total_web = sum(v['count'] for v in web.values())
    domains = len(web)
    lines.append(f'\U0001f310 Web Activity ({plural(domains, "domain")}, {plural(total_web, "request")}):')

    if 'web-search' in web:
        ws = web['web-search']
        lines.append(f'  Searches ({plural(ws["count"], "query")}):')
        for q in ws['urls']:
            lines.append(f'    \U0001f50d "{q}"')

    for domain, info in sorted(
        ((d, v) for d, v in web.items() if d != 'web-search'),
        key=lambda x: x[1]['count'], reverse=True
    ):
        lines.append(f'  {domain} ({plural(info["count"], "request")}):')
        for url in info['urls']:
            lines.append(f'    \u2192 {url}')

    lines.append('')

# Tool breakdown
if tools:
    sorted_tools = sorted(tools.items(), key=lambda x: x[1], reverse=True)
    max_count = sorted_tools[0][1] if sorted_tools else 1

    lines.append(f'\U0001f527 Tool Calls ({total_calls}):')
    for name, count in sorted_tools:
        bar_len = max(1, round((count / max_count) * 20))
        bar = '\u2588' * bar_len
        lines.append(f'  {name:<14} {bar} {count}')
    lines.append('')

# Git activity
if git_commits or git_uncommitted:
    lines.append('\U0001f4cb Git Activity:')
    if git_commits:
        lines.append(f'  Commits ({len(git_commits)}):')
        for c in git_commits:
            lines.append(f'    {c["sha"]}  {c["message"]}')
            if c.get('stat'):
                lines.append(f'             {c["stat"]}')
    if git_uncommitted:
        lines.append(f'  Uncommitted changes:')
        for line in git_uncommitted:
            lines.append(f'    {line}')
    lines.append('')

# Footer
sid = session_id[:8] if len(session_id) > 8 else session_id
lines.append('\u2500' * 50)
lines.append(f'Session: {sid}  |  Calls: {total_calls}  |  Files: {touched}')

print('\n'.join(lines))
