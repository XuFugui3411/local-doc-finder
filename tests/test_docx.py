import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from docx_text import docx_in_process
from fixtures import docx
from indexer import Index
import test_http

BODY = '''<w:p><w:r><w:t>Alpha 中文</w:t></w:r><w:r><w:t>正文</w:t></w:r><w:r><w:tab/><w:t>记录</w:t><w:br/><w:t>第二行</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>预算</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>三万元</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>负责人</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>小李</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:hyperlink><w:r><w:t>末尾内容</w:t></w:r></w:hyperlink></w:p>'''


class DocxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Word 资料 ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.docs = self.base / 'documents'
        self.docs.mkdir()
        self.index = Index(self.base / 'state/index.sqlite3')
        self.root_id = self.index.choose(self.docs)
        self.path = self.docs / '项目 资料.DOCX'

    def test_paragraph_run_table_order_and_line_breaks(self):
        docx(self.path, body=BODY)
        units, warnings = docx_in_process(self.path.read_bytes())
        self.assertEqual(warnings, [])
        self.assertEqual([u[2] for u in units], ['正文段落 1', '表格 1 · 第 1 行', '表格 1 · 第 2 行', '正文段落 2'])
        self.assertEqual(units[0][1], 'Alpha 中文正文\t记录\n第二行')
        self.assertEqual(units[1][1], '预算\t三万元')
        self.assertEqual(units[-1][1], '末尾内容')

    def test_docx_search_and_positions_and_filter(self):
        docx(self.path, body=BODY)
        (self.docs / 'other.txt').write_text('alpha 预算')
        self.index.update(self.root_id)
        hit = self.index.search('ALPHA 预算', kind='docx')['results'][0]
        self.assertEqual(hit['kind'], 'docx')
        self.assertEqual(hit['matched_pages'], [])
        self.assertEqual([s['location'] for s in hit['snippets']], ['正文段落 1', '表格 1 · 第 1 行'])
        self.assertTrue(all(s['page'] is None for s in hit['snippets']))
        self.assertEqual(self.index.search('alpha 预算')['total'], 2)
        self.assertEqual(self.index.search('小李')['results'][0]['snippets'][0]['block'], 3)

    def test_modify_delete_and_reuse(self):
        docx(self.path, paragraphs=['Oldneedle'])
        self.index.update(self.root_id)
        with patch('indexer.extract', side_effect=AssertionError('must reuse')):
            self.assertEqual(self.index.update(self.root_id)['unchanged'], 1)
        docx(self.path, paragraphs=['Newneedle'])
        self.index.update(self.root_id)
        self.assertEqual(self.index.search('oldneedle')['total'], 0)
        self.assertEqual(self.index.search('newneedle')['total'], 1)
        self.path.unlink()
        self.index.update(self.root_id)
        self.assertEqual(self.index.search('newneedle')['total'], 0)

    def test_corrupt_encrypted_empty_and_limits(self):
        for invalid in (b'bad ZIP', b'\xd0\xcf\x11\xe0Encrypted Office'):
            with self.assertRaises(ValueError):
                docx_in_process(invalid)
        docx(self.path, paragraphs=[''])
        self.assertIn('没有可提取', docx_in_process(self.path.read_bytes())[1][0])
        docx(self.path, paragraphs=['very long'])
        with self.assertRaisesRegex(ValueError, '上限'):
            docx_in_process(self.path.read_bytes(), max_chars=2)
        with patch('docx_text.MAX_XML_BYTES', 10):
            with self.assertRaisesRegex(ValueError, '上限'):
                docx_in_process(self.path.read_bytes())
        (self.docs / 'broken.docx').write_bytes(b'bad zip')
        self.assertEqual(self.index.update(self.root_id)['failed'], 1)
        self.assertIn('DOCX 提取失败', self.index.search('broken')['results'][0]['message'])

    def test_reject_dtd_and_ignore_deleted_text(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('word/document.xml', '<!DOCTYPE document [<!ENTITY x "bad">]><document/>')
        with self.assertRaisesRegex(ValueError, 'DTD'):
            docx_in_process(data.getvalue())
        docx(self.path, body='<w:p><w:del><w:r><w:t>deleted</w:t></w:r></w:del><w:ins><w:r><w:t>visible</w:t></w:r></w:ins></w:p>')
        self.assertEqual(docx_in_process(self.path.read_bytes())[0][0][1], 'visible')

    def test_legacy_database_migration_preserves_text_documents(self):
        (self.docs / 'old.txt').write_text('legacy text')
        self.index.update(self.root_id)
        with self.index.connect() as db:
            db.executescript('''ALTER TABLE pages RENAME TO old_pages;
                CREATE TABLE pages(doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                number INTEGER,text TEXT,text_fold TEXT,PRIMARY KEY(doc_id,number));
                INSERT INTO pages SELECT doc_id,number,text,text_fold FROM old_pages;
                DROP TABLE old_pages;''')
        upgraded = Index(self.index.database)
        self.assertEqual(upgraded.search('legacy')['total'], 1)
        docx(self.path, body=BODY)
        upgraded.update(self.root_id)
        self.assertEqual(upgraded.search('预算', kind='docx')['total'], 1)


class DocxHttpTests(unittest.TestCase):
    setUp = test_http.HttpTests.setUp
    stop = test_http.HttpTests.stop
    request = test_http.HttpTests.request
    def test_docx_reader_is_escaped_and_original_download_is_exact(self):
        path = self.docs / '原文 & 测试.docx'
        docx(path, paragraphs=['<script>alert(1)</script> Alpha'])
        self.service.index.update(self.service.index.current()['id'])
        hit = self.service.index.search('Alpha', kind='docx')['results'][0]
        with self.request('/document?id=' + str(hit['id'])) as response:
            html = response.read().decode('utf-8')
            self.assertIn('text/html', response.headers['Content-Type'])
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)
            self.assertIn('id="block-1"', html)
            self.assertIn('正文段落 1', html)
        with self.request('/document?id=' + str(hit['id']) + '&download=1') as response:
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(response.read(), path.read_bytes())
        with self.request('/reader.css') as response:
            self.assertEqual(response.status, 200)
