import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from app import Server, Service


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='HTTP 检索 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.docs = self.root / 'docs'
        self.docs.mkdir()
        (self.docs / '中文.txt').write_text('Alpha <script>alert(1)</script> 预算', encoding='utf-8')
        self.service = Service(self.root / 'state/index.sqlite3')
        identifier = self.service.choose(self.docs)
        self.service.index.update(identifier)
        self.server = Server(('127.0.0.1', 0), self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, body=None, headers=None, token=True):
        actual = {'X-Local-Token': self.service.token} if token else {}
        if body is not None:
            actual['Content-Type'] = 'application/json'
        actual.update(headers or {})
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=actual)
        return urllib.request.urlopen(request, timeout=5)

    def test_html_assets_status_and_original_text(self):
        with self.request('/') as response:
            self.assertEqual(response.status, 200)
            self.assertIn(self.service.token, response.read().decode())
            self.assertIn('SameSite=Strict', response.headers['Set-Cookie'])
            self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
        for path in ('/app.js', '/style.css', '/favicon.svg'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
        with self.request('/api/status') as response:
            self.assertEqual(json.load(response)['documents'], 1)
        with self.request('/api/search?q=ALPHA') as response:
            result = json.load(response)['results'][0]
        with self.request('/document?id=' + str(result['id'])) as response:
            self.assertIn('text/plain', response.headers['Content-Type'])
            self.assertIn('<script>', response.read().decode())

    def test_missing_token_foreign_origin_and_dns_rebinding_rejected(self):
        for path, headers, token in [('/api/status', {}, False), ('/api/status', {'Host': 'attacker.example'}, True),
                                      ('/api/update', {'Origin': 'https://attacker.example'}, True),
                                      ('/document?id=1', {}, False)]:
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.request(path, body={} if path == '/api/update' else None, headers=headers, token=token)
            self.assertEqual(raised.exception.code, 403)

    def test_post_root_and_errors_and_no_static_path_traversal(self):
        with self.request('/api/root', {'path': str(self.docs)}) as response:
            self.assertEqual(json.load(response)['root']['path'], str(self.docs))
        for path, body in [('/api/root', {'path': ''}), ('/api/root', {'path': []})]:
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.request(path, body)
            self.assertEqual(raised.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request('/../../app.py')
        self.assertEqual(raised.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
