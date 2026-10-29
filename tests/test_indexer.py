import hashlib
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import unittest
from unittest.mock import patch

from extraction import decode_text, extract_pdf
from indexer import Index, fold, segments
from fixtures import pdf, scanned_pdf


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='文档 检索测试 ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / '资料 目录'
        self.root.mkdir()
        self.index = Index(self.base / 'state/index.sqlite3')
        self.root_id = self.index.choose(self.root)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_recursive_unicode_filename_and_case_insensitive_body(self):
        self.put('子目录/预算说明.MD', '这是完整原文。Alpha PROJECT 的预算是三万元。')
        result = self.index.update(self.root_id)
        self.assertEqual(result['added'], 1)
        hit = self.index.search('alpha 预算')['results'][0]
        self.assertEqual(hit['relative'], '子目录/预算说明.MD')
        excerpt = ''.join(s['text'] for s in hit['snippets'][0]['segments'])
        self.assertIn('Alpha PROJECT', excerpt)
        self.assertIn('预算', ''.join(s['text'] for s in hit['name_segments'] if s['hit']))

    def test_and_across_filename_and_body_and_literal_search(self):
        self.put('alpha.txt', 'Beta literal a+b <script>alert(1)</script>')
        self.put('other.txt', 'alpha only')
        self.index.update(self.root_id)
        self.assertEqual(self.index.search('ALPHA beta')['total'], 1)
        self.assertEqual(self.index.search('alpha missing')['total'], 0)
        self.assertEqual(self.index.search('a+b')['total'], 1)
        self.assertEqual(self.index.search("' OR 1=1 --")['total'], 0)
        hit = self.index.search('<script>')['results'][0]
        self.assertIn('<script>', ''.join(s['text'] for s in hit['snippets'][0]['segments']))

    def test_pdf_pages_and_cross_page_and(self):
        pdf(self.root / 'report.pdf', ['Alpha on the first page', 'Budget on the second page'])
        self.index.update(self.root_id)
        result = self.index.search('alpha budget')['results'][0]
        self.assertEqual(result['matched_pages'], [1, 2])
        budget = self.index.search('BUDGET')['results'][0]
        self.assertEqual(budget['snippets'][0]['page'], 2)
        self.assertIn('Budget', ''.join(x['text'] for x in budget['snippets'][0]['segments']))

    def test_scanned_pdf_explicit_warning_but_filename_searchable(self):
        scanned_pdf(self.root / 'scanned.pdf')
        self.index.update(self.root_id)
        hit = self.index.search('scanned')['results'][0]
        self.assertEqual(hit['snippets'], [])
        self.assertIn('OCR', hit['message'])
        self.assertEqual(self.index.search('never-in-images')['total'], 0)
        self.assertTrue(self.index.snapshot()['issues'])

    def test_mixed_pdf_retains_page_number_and_warns_blank_page(self):
        pdf(self.root / 'mixed.pdf', ['', 'Searchable second page'])
        self.index.update(self.root_id)
        hit = self.index.search('searchable')['results'][0]
        self.assertEqual(hit['matched_pages'], [2])
        self.assertIn('第 1 页', hit['message'])
        self.assertEqual(self.index.snapshot()['searchable'], 1)

    def test_corrupt_and_encrypted_pdf_do_not_block_other_documents(self):
        (self.root / 'broken.pdf').write_bytes(b'not a pdf')
        pdf(self.root / 'encrypted.pdf', ['Secret'], password='password')
        self.put('good.txt', 'survives failures')
        result = self.index.update(self.root_id)
        self.assertEqual(result['failed'], 2)
        self.assertEqual(self.index.search('survives')['total'], 1)
        self.assertIn('密码', self.index.search('encrypted')['results'][0]['message'])

    def test_add_modify_delete_and_same_metadata_content_change(self):
        path = self.put('a.txt', 'OLD old')
        self.index.update(self.root_id)
        original = path.stat()
        path.write_text('NEW new', encoding='utf-8')
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.put('新增.md', 'added value')
        result = self.index.update(self.root_id)
        self.assertEqual((result['modified'], result['added']), (1, 1))
        self.assertEqual(self.index.search('OLD')['total'], 0)
        self.assertEqual(self.index.search('new')['total'], 1)
        path.unlink()
        self.assertEqual(self.index.update(self.root_id)['deleted'], 1)
        self.assertEqual(self.index.search('new')['total'], 0)

    def test_unchanged_reuses_extraction_and_persists_after_restart(self):
        self.put('a.txt', 'persistent keyword')
        self.index.update(self.root_id)
        with patch('indexer.extract', side_effect=AssertionError('must reuse')):
            self.assertEqual(self.index.update(self.root_id)['unchanged'], 1)
        again = Index(self.index.database)
        self.assertEqual(again.search('persistent')['total'], 1)

    def test_read_failure_clears_old_body_but_retains_filename(self):
        path = self.put('a.txt', 'obsolete-word')
        self.put('b.md', 'still available')
        self.index.update(self.root_id)
        original = Path.open

        def fail_one(target, *args, **kwargs):
            if target == path:
                raise PermissionError('file locked')
            return original(target, *args, **kwargs)

        with patch.object(Path, 'open', fail_one):
            self.assertEqual(self.index.update(self.root_id)['failed'], 1)
        self.assertEqual(self.index.search('obsolete-word')['total'], 0)
        self.assertEqual(self.index.search('a.txt')['total'], 1)
        self.assertEqual(self.index.search('available')['total'], 1)

    def test_inaccessible_subtree_disables_old_body_without_false_deletion(self):
        self.put('private/a.txt', 'inaccessible body')
        self.put('good.md', 'public body')
        self.index.update(self.root_id)
        original = os.scandir

        def deny(path):
            if Path(path) == self.root / 'private':
                raise PermissionError('permission denied')
            return original(path)

        with patch('indexer.os.scandir', side_effect=deny):
            result = self.index.update(self.root_id)
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(self.index.search('inaccessible')['total'], 0)
        self.assertEqual(self.index.search('a.txt')['results'][0]['status'], 'error')
        self.assertIn('目录读取失败', self.index.snapshot()['issues'][0]['message'])

    def test_missing_root_preserves_snapshot_and_cancel_rolls_back(self):
        self.put('a.txt', 'before transaction')
        self.index.update(self.root_id)
        self.put('b.txt', 'after transaction')
        cancel = threading.Event()

        def progress(_):
            cancel.set()

        with self.assertRaisesRegex(ValueError, '取消'):
            self.index.update(self.root_id, progress, cancel)
        self.assertEqual(self.index.search('after')['total'], 0)
        moved = self.base / 'moved'
        self.root.rename(moved)
        with self.assertRaises(OSError):
            self.index.update(self.root_id)
        self.assertEqual(self.index.search('before')['total'], 1)

    def test_roots_are_separate_and_type_filter_paginates(self):
        self.put('a.md', 'keyword')
        self.put('b.txt', 'keyword')
        self.index.update(self.root_id)
        self.assertEqual(self.index.search('keyword', kind='md')['total'], 1)
        self.assertEqual(len(self.index.search('keyword', limit=1)['results']), 1)
        self.assertEqual(self.index.search('keyword', offset=1, limit=1)['results'][0]['name'], 'b.txt')
        other = self.base / 'other'
        other.mkdir()
        self.index.choose(other)
        self.assertEqual(self.index.search('keyword')['total'], 0)
        self.index.choose(self.root)
        self.assertEqual(self.index.search('keyword')['total'], 2)

    def test_original_rejects_changed_and_outside_paths(self):
        path = self.put('a.txt', 'original')
        self.index.update(self.root_id)
        identifier = self.index.search('original')['results'][0]['id']
        self.assertEqual(self.index.original(identifier)[2], b'original')
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError, '变化'):
            self.index.original(identifier)
        with self.index.connect() as db:
            db.execute('UPDATE documents SET relative=? WHERE id=?', ('../outside.txt', identifier))
        with self.assertRaises(ValueError):
            self.index.original(identifier)

    def test_limits_empty_file_and_unsupported_files(self):
        self.put('empty.txt', '')
        self.put('ignored.xlsx', 'not supported')
        self.put('.隐藏/valid.md', 'hidden directory searched')
        self.index.update(self.root_id)
        self.assertEqual(self.index.search('empty')['results'][0]['snippets'], [])
        self.assertEqual(self.index.search('hidden')['total'], 1)
        self.assertEqual(self.index.search('ignored')['total'], 0)
        with self.assertRaises(ValueError):
            self.index.search('x' * 201)
        with self.assertRaises(ValueError):
            self.index.choose('')

    def test_oversized_file_and_pdf_timeout_are_explicit(self):
        self.put('large.txt', 'content')
        with patch('indexer.MAX_TEXT_BYTES', 2):
            self.assertEqual(self.index.update(self.root_id)['failed'], 1)
        self.assertIn('上限', self.index.search('large')['results'][0]['message'])
        with self.assertRaisesRegex(ValueError, '超过'):
            extract_pdf(b'not a pdf', timeout=0)

    @unittest.skipUnless(os.name == 'nt', 'Windows junctions')
    def test_junction_does_not_recurse_into_other_directory(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'private.txt').write_text('outside sentinel')
        junction = self.root / 'linked'
        command = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
        self.assertEqual(command.returncode, 0, command.stderr)
        self.addCleanup(junction.rmdir)
        self.index.update(self.root_id)
        self.assertEqual(self.index.search('sentinel')['total'], 0)
        self.assertIn('目录联接', self.index.snapshot()['issues'][0]['message'])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_actual_windows_exclusive_handle(self):
        import ctypes
        from ctypes import wintypes
        path = self.put('locked.txt', 'busy file')
        self.put('good.txt', 'still works')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            self.assertEqual(self.index.update(self.root_id)['failed'], 1)
            self.assertEqual(self.index.search('works')['total'], 1)
        finally:
            kernel.CloseHandle(handle)


class ExtractionTests(unittest.TestCase):
    def test_encodings_and_binary_rejection(self):
        for encoding in ('utf-8-sig', 'utf-16', 'utf-32', 'gb18030'):
            self.assertEqual(decode_text('中文内容 Alpha'.encode(encoding)), '中文内容 Alpha')
        with self.assertRaises(ValueError):
            decode_text(b'\x00\x01binary')

    def test_highlights_preserve_original_and_literal_characters(self):
        text = 'Alpha <script> 中文 a+b ALPHA'
        parts = segments(text, [fold('alpha'), '<script>', 'a+b'])
        self.assertEqual(''.join(p['text'] for p in parts), text)
        self.assertEqual([p['text'] for p in parts if p['hit']], ['Alpha', '<script>', 'a+b', 'ALPHA'])


if __name__ == '__main__':
    unittest.main()
