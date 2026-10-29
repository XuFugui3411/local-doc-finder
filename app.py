"""Loopback-only HTTP service. The UI and index never use an external service."""
import argparse
import hmac
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

from extraction import decode_text
from indexer import Index
from reader import docx_view

BASE = Path(__file__).resolve().parent


class Service:
    def __init__(self, database):
        self.index = Index(database)
        self.token = secrets.token_urlsafe(32)
        self.guard = threading.Lock()
        self.cancel = threading.Event()
        self.job = dict(state='idle', message='尚未运行索引任务', progress={})

    def status(self):
        with self.guard:
            job = json.loads(json.dumps(self.job))
        return {**self.index.snapshot(), 'job': job}

    def choose(self, folder):
        with self.guard:
            if self.job['state'] == 'running':
                raise ValueError('请先等待当前索引更新结束，或取消后再切换目录')
            identifier = self.index.choose(folder)
            self.job = dict(state='idle', message='资料目录已选择，点击更新索引后开始搜索', progress={})
            return identifier

    def start(self):
        with self.guard:
            if self.job['state'] == 'running':
                raise ValueError('已有索引任务在运行')
            root = self.index.current()
            if not root:
                raise ValueError('请先选择资料目录')
            self.cancel.clear()
            self.job = dict(state='running', message='正在递归扫描；更新完成前保留上次索引', progress={})

        def progress(values):
            with self.guard:
                self.job['progress'] = values

        def worker():
            try:
                result = self.index.update(root['id'], progress, self.cancel)
                with self.guard:
                    self.job = dict(state='done', message='索引已更新', progress=result)
            except Exception as exc:
                with self.guard:
                    self.job = dict(state='cancelled' if self.cancel.is_set() else 'error', message=str(exc), progress=self.job['progress'])

        threading.Thread(target=worker, name='document-indexer', daemon=True).start()


def child_command(*arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *arguments]
    return [sys.executable, str(BASE / 'app.py'), *arguments]


def pick_directory():
    with tempfile.TemporaryDirectory(prefix='local-doc-picker-') as directory:
        output = Path(directory) / 'chosen.json'
        subprocess.run(child_command('--pick-directory', str(output)),
                       timeout=180, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return json.loads(output.read_text(encoding='utf-8'))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        self.service = service
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalDocFinder/1.0'

    def log_message(self, *_):
        pass  # paths and queries do not go into console logs

    def response(self, code, data, kind='application/json; charset=utf-8', extra=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'; object-src 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorize(self, api=False, file=False):
        port = self.server.server_port
        host = self.headers.get('Host', '')
        if host not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
            raise PermissionError('只接受本机地址访问')
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            raise PermissionError('拒绝来自其他网站的请求')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PermissionError('拒绝跨站请求')
        token = self.server.service.token
        if api and not hmac.compare_digest(self.headers.get('X-Local-Token', ''), token):
            raise PermissionError('页面会话已失效，请重新打开本地页面')
        if file:
            jar = cookies.SimpleCookie()
            try:
                jar.load(self.headers.get('Cookie', ''))
                value = jar['local_doc_session'].value if 'local_doc_session' in jar else ''
            except cookies.CookieError:
                value = ''
            if not hmac.compare_digest(value, token) and not hmac.compare_digest(self.headers.get('X-Local-Token', ''), token):
                raise PermissionError('请先打开本地检索台')

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            route = parsed.path
            self.authorize(api=route.startswith('/api/'), file=route == '/document')
            service = self.server.service
            if route in {'/', '/index.html'}:
                html = (BASE / 'static/index.html').read_text(encoding='utf-8').replace('__SESSION_TOKEN__', service.token)
                return self.response(200, html.encode('utf-8'), 'text/html; charset=utf-8',
                                     {'Set-Cookie': f'local_doc_session={service.token}; Path=/; HttpOnly; SameSite=Strict'})
            if route in {'/app.js', '/style.css', '/reader.css', '/favicon.svg'}:
                kind = {'/app.js': 'text/javascript; charset=utf-8', '/style.css': 'text/css; charset=utf-8', '/reader.css': 'text/css; charset=utf-8', '/favicon.svg': 'image/svg+xml'}[route]
                return self.response(200, (BASE / 'static' / route[1:]).read_bytes(), kind)
            if route == '/api/status':
                return self.response(200, service.status())
            query = parse_qs(parsed.query)
            if route == '/api/search':
                result = service.index.search(query.get('q', [''])[0], query.get('kind', ['all'])[0], query.get('offset', ['0'])[0])
                return self.response(200, result)
            if route == '/document':
                name, kind, data = service.index.original(int(query.get('id', ['0'])[0]))
                if kind == 'docx':
                    if query.get('download') == ['1']:
                        return self.response(200, data, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                             {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name, safe='')})
                    return self.response(200, docx_view(name, data, int(query['id'][0])), 'text/html; charset=utf-8')
                if kind != 'pdf':
                    data = decode_text(data).encode('utf-8')
                return self.response(200, data, 'application/pdf' if kind == 'pdf' else 'text/plain; charset=utf-8',
                                     {'Content-Disposition': "inline; filename*=UTF-8''" + quote(name, safe='')})
            self.response(404, {'error': '页面不存在'})
        except PermissionError as exc:
            self.response(403, {'error': str(exc)})
        except FileNotFoundError as exc:
            self.response(404, {'error': str(exc)})
        except (ValueError, OSError) as exc:
            self.response(400, {'error': str(exc)})
        except Exception:
            self.response(500, {'error': '服务处理失败，请重新更新索引或重启服务'})

    def do_POST(self):
        try:
            self.authorize(api=True)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('请求必须是 JSON')
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 8192:
                raise ValueError('请求过大')
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('请求必须是 JSON 对象')
            route = urlsplit(self.path).path
            service = self.server.service
            if route == '/api/root':
                folder = body.get('path', '')
                if not isinstance(folder, str):
                    raise ValueError('目录必须是字符串')
                service.choose(folder)
                return self.response(200, service.status())
            if route == '/api/pick':
                return self.response(200, {'path': pick_directory()})
            if route == '/api/update':
                service.start()
                return self.response(202, {'ok': True})
            if route == '/api/cancel':
                service.cancel.set()
                return self.response(200, {'ok': True})
            self.response(404, {'error': '接口不存在'})
        except PermissionError as exc:
            self.response(403, {'error': str(exc)})
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            self.response(400, {'error': str(exc)})
        except Exception:
            self.response(500, {'error': '服务处理失败，请重试'})


def main():
    parser = argparse.ArgumentParser(description='Local Doc Finder：仅在本机运行的文档检索台')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LocalDocFinder')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--pick-directory', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.pick_directory:
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Tk()
        window.withdraw()
        selected = filedialog.askdirectory(parent=window, title='选择资料目录（将递归扫描子目录）', mustexist=True)
        window.destroy()
        args.pick_directory.write_text(json.dumps(selected, ensure_ascii=False), encoding='utf-8')
        return
    service = Service(args.data_dir / 'index.sqlite3')
    try:
        server = Server(('127.0.0.1', args.port), service)
    except OSError:
        if args.port != 8766:
            raise
        server = Server(('127.0.0.1', 0), service)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Local Doc Finder: {url}\nClose this console or press Ctrl+C to stop. Documents stay on this computer.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        service.cancel.set()
        server.server_close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
