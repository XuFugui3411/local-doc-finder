"""Self-test the frozen runtime using generated documents and loopback HTTP."""
import io
import json
from pathlib import Path
import tempfile
import threading
import urllib.request
import zipfile


def run(report):
    from app import Service, Server, child_command
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from reader import docx_view
    checks = []
    with tempfile.TemporaryDirectory(prefix='LocalDocFinder 软件验证 ') as directory:
        root = Path(directory)
        docs = root / '资料'
        docs.mkdir()
        (docs / '中文 文档.txt').write_text('Alpha 本地检索', encoding='utf-8')
        (docs / 'notes.md').write_text('Markdown 原文', encoding='utf-8')
        with zipfile.ZipFile(docs / 'Word资料.docx', 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Alpha DOCX 正文</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>三万元</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        writer = PdfWriter()
        font = writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')}))
        for text in ('First page', 'Alpha budget second page'):
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            content = DecodedStreamObject()
            content.set_data(('BT /F1 12 Tf 40 700 Td (' + text + ') Tj ET').encode())
            page[NameObject('/Contents')] = writer._add_object(content)
        writer.write(docs / 'report.pdf')
        service = Service(root / 'state/index.sqlite3')
        identifier = service.choose(docs)
        result = service.index.update(identifier)
        assert result['added'] == 4 and result['failed'] == 0, result
        assert service.index.search('alpha')['total'] == 3
        pdf = service.index.search('alpha budget', kind='pdf')['results'][0]
        assert pdf['matched_pages'] == [2]
        word = service.index.search('alpha 三万元', kind='docx')['results'][0]
        assert word['snippets'][1]['location'] == '表格 1 · 第 1 行'
        checks.extend(['four formats', 'frozen PDF/DOCX child processes', 'PDF page 2', 'DOCX table location'])
        _, _, data = service.index.original(word['id'])
        assert b'block-2' in docx_view('test.docx', data, word['id'])
        checks.append('DOCX reader')
        server = Server(('127.0.0.1', 0), service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            for path in ('/', '/style.css', '/app.js', '/reader.css', '/favicon.svg'):
                with urllib.request.urlopen(url + path, timeout=5) as response:
                    assert response.status == 200 and response.read()
            request = urllib.request.Request(url + '/api/search?q=alpha', headers={'X-Local-Token':service.token})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert json.load(response)['total'] == 3
            checks.append('bundled web assets and HTTP search')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        (docs / '中文 文档.txt').write_text('changed marker', encoding='utf-8')
        (docs / 'notes.md').unlink()
        result = service.index.update(identifier)
        assert result['modified'] == 1 and result['deleted'] == 1
        checks.append('update and deletion')
        assert '--pick-directory' in child_command('--pick-directory', 'fixture.json')
        if getattr(__import__('sys'), 'frozen', False):
            assert child_command('--pick-directory', 'fixture.json')[1] == '--pick-directory'
        checks.append('frozen folder-picker command')
    report.write_text(json.dumps({'ok':True,'checks':checks}, ensure_ascii=False, indent=2), encoding='utf-8')
