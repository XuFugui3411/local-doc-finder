"""Bounded text extraction. PDF parsing runs in a disposable child process."""
import io
import logging
import multiprocessing as mp
from docx_text import docx_in_process, MAX_DOCX_BYTES

MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_CHARS = 2_000_000
MAX_PAGES = 500


def decode_text(data):
    if data.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        text = data.decode('utf-32')
    elif data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = data.decode('utf-16')
    elif b'\x00' in data:
        raise ValueError('包含 NUL 字节，可能是二进制文件或无 BOM 的 UTF-16；请另存为 UTF-8')
    else:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('gb18030')
    if any(ord(c) < 32 and c not in '\r\n\t\f' for c in text):
        raise ValueError('含不支持的控制字符，可能不是文本文件')
    if len(text) > MAX_CHARS:
        raise ValueError('正文超过 200 万字符上限，未建立正文索引')
    return text


def pdf_in_process(data):
    from pypdf import PdfReader
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('PDF 已加密且需要密码，第一版不支持密码输入')
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f'PDF 超过 {MAX_PAGES} 页上限，未建立正文索引')
    pages, warnings, chars = [], [], 0
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content and len(content.get_data()) > 16 * 1024 * 1024:
            raise ValueError(f'第 {number} 页解压后的内容流超过 16 MiB 上限')
        text = page.extract_text() or ''
        chars += len(text)
        if chars > MAX_CHARS:
            raise ValueError('PDF 正文超过 200 万字符上限，未建立正文索引')
        pages.append((number, text))
        if not text.strip():
            warnings.append(f'第 {number} 页无可提取文字，可能是扫描页或空白页；第一版不提供 OCR')
    if not pages:
        warnings.append('PDF 没有页面')
    return pages, warnings


def _document_worker(data, connection, kind):
    try:
        result = {'ok': True, 'result': pdf_in_process(data) if kind == 'pdf' else docx_in_process(data, MAX_CHARS)}
    except Exception as exc:
        result = {'ok': False, 'error': str(exc) or type(exc).__name__}
    try:
        connection.send(result)
    except (BrokenPipeError, EOFError, OSError):
        pass  # parent timed out or cancelled; no traceback for a normal shutdown
    finally:
        connection.close()


def _extract_isolated(data, kind, timeout):
    ctx = mp.get_context('spawn')
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_document_worker, args=(data, child, kind), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise ValueError(f'{kind.upper()} 提取超过 {timeout} 秒，已停止该文件，继续其他文件')
        try:
            result = parent.recv()
        except EOFError as exc:
            raise ValueError(f'{kind.upper()} 提取进程异常退出') from exc
        if not result['ok']:
            raise ValueError(f'{kind.upper()} 提取失败：' + result['error'])
        return result['result']
    finally:
        parent.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)


def extract_pdf(data, timeout=30):
    return _extract_isolated(data, 'pdf', timeout)


def extract_docx(data, timeout=30):
    return _extract_isolated(data, 'docx', timeout)


def extract(data, kind):
    if kind == 'pdf':
        return extract_pdf(data)
    if kind == 'docx':
        return extract_docx(data)
    text = decode_text(data)
    return [(0, text)], ([] if text.strip() else ['文件为空或仅包含空白，仍可按文件名搜索'])
