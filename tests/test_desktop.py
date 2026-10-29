import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
from desktop import InstanceLock, session_url


class DesktopTests(unittest.TestCase):
    def test_single_instance_lock_releases_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = InstanceLock(Path(folder)), InstanceLock(Path(folder))
            self.assertTrue(a.acquire())
            self.assertFalse(b.acquire())
            a.release()
            self.assertTrue(b.acquire())
            b.release()

    def test_frozen_folder_picker_does_not_try_to_run_a_py_file(self):
        with patch.object(app.sys,'frozen',True,create=True), patch.object(app.sys,'executable','fixture.exe'):
            self.assertEqual(app.child_command('--pick-directory','target.json'), ['fixture.exe','--pick-directory','target.json'])

    def test_existing_session_only_opens_loopback_http(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.json'
            for url in ('https://example.com','http://example.com:8766','file:///private','http://127.0.0.1:8766/?external=1'):
                path.write_text(json.dumps({'url':url}))
                with self.assertRaises(ValueError):
                    session_url(path)
            path.write_text(json.dumps({'url':'http://127.0.0.1:8766'}))
            self.assertEqual(session_url(path),'http://127.0.0.1:8766')
