"""Run code on, and copy files to, a live Kaggle notebook through its Jupyter server URL.

The URL (Kaggle notebook -> "Run" menu -> connect from an editor / Jupyter server URL) goes in .env as
KAGGLE_COMPATIBLE_URL. It works like a password for the session and stops working when the session ends.

Usage:
  python scripts/kaggle_remote.py run "import torch; print(torch.cuda.device_count())"
  python scripts/kaggle_remote.py run-file some_script.py
  python scripts/kaggle_remote.py put local/file.jsonl remote/name.jsonl     # into /kaggle/working
  python scripts/kaggle_remote.py get remote/name.jsonl local/file.jsonl
"""
import base64
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parents[1]
UA = 'Mozilla/5.0 (research evaluation script)'


def base_url():
    for path in (ROOT / '.env', ROOT / 'apps/romanized-data-collection/backend/.env'):
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.startswith('KAGGLE_COMPATIBLE_URL='):
                    return line.split('=', 1)[1].strip().strip('"\'').rstrip('/')
    raise SystemExit('KAGGLE_COMPATIBLE_URL is not set in .env')


def http(method, path, body=None):
    req = urllib.request.Request(base_url() + path, method=method, headers={'User-Agent': UA, 'Content-Type': 'application/json'},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read() or b'null')


def kernel_id():
    kernels = http('GET', '/api/kernels')
    if not kernels:
        return http('POST', '/api/kernels', {'name': 'python3'})['id']
    return kernels[0]['id']


def run(code, timeout=6 * 3600, quiet=False):
    """Execute code on the notebook's kernel and stream its output. Returns True if it finished without error."""
    ws_url = base_url().replace('https://', 'wss://') + f'/api/kernels/{kernel_id()}/channels'
    ws = websocket.create_connection(ws_url, header=[f'User-Agent: {UA}'], timeout=60)
    msg_id = uuid.uuid4().hex
    ws.send(json.dumps({
        'header': {'msg_id': msg_id, 'username': 'remote', 'session': uuid.uuid4().hex, 'msg_type': 'execute_request',
                   'version': '5.3', 'date': time.strftime('%Y-%m-%dT%H:%M:%S')},
        'parent_header': {}, 'metadata': {}, 'channel': 'shell',
        'content': {'code': code, 'silent': False, 'store_history': False, 'user_expressions': {}, 'allow_stdin': False}}))
    ok, end = True, time.time() + timeout
    while time.time() < end:
        try:
            msg = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue  # long-running cell: keep waiting
        if msg.get('parent_header', {}).get('msg_id') != msg_id:
            continue
        kind, content = msg['msg_type'], msg['content']
        if kind == 'stream' and not quiet:
            print(content['text'], end='', flush=True)
        elif kind in ('execute_result', 'display_data') and not quiet:
            print(content['data'].get('text/plain', ''), flush=True)
        elif kind == 'error':
            ok = False
            print('\n'.join(content['traceback'][-3:]), file=sys.stderr)
        elif kind == 'status' and content['execution_state'] == 'idle':
            break
    ws.close()
    return ok


def put(local, remote):
    data = base64.b64encode(Path(local).read_bytes()).decode()
    http('PUT', f'/api/contents/{remote}', {'type': 'file', 'format': 'base64', 'content': data})
    print(f'uploaded {local} -> /kaggle/working/{remote}')


def get(remote, local):
    d = http('GET', f'/api/contents/{remote}?content=1&format=base64&type=file')
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    Path(local).write_bytes(base64.b64decode(d['content']))
    print(f'downloaded /kaggle/working/{remote} -> {local}')


if __name__ == '__main__':
    cmd, *rest = sys.argv[1:]
    if cmd == 'run':
        sys.exit(0 if run(rest[0]) else 1)
    if cmd == 'run-file':
        sys.exit(0 if run(Path(rest[0]).read_text(encoding='utf-8')) else 1)
    if cmd == 'put':
        put(*rest)
    elif cmd == 'get':
        get(*rest)
