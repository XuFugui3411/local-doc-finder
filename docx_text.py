"""Read DOCX body paragraphs/tables without Office or external dependencies."""
import io
import re
import zipfile
from xml.etree import ElementTree as ET

MAX_DOCX_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_BLOCKS = 10_000
WORD_NAMESPACES = {'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
                   'http://purl.oclc.org/ooxml/wordprocessingml/main'}


def docx_in_process(data, max_chars=2_000_000):
    if data.startswith(b'\xd0\xcf\x11\xe0'):
        raise ValueError('可能是加密 Word 文档或旧 .doc 格式，请先解密或另存为 .docx')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            if len(package.infolist()) > 10_000:
                raise ValueError('DOCX 包内条目超过 10000 项上限')
            info = package.getinfo('word/document.xml')
            if info.flag_bits & 1:
                raise ValueError('DOCX 内容已加密，请先解除密码')
            if info.file_size > MAX_XML_BYTES:
                raise ValueError('DOCX 主正文 XML 超过 16 MiB 上限')
            with package.open(info) as stream:
                xml = stream.read(MAX_XML_BYTES + 1)
            if len(xml) > MAX_XML_BYTES:
                raise ValueError('DOCX 主正文 XML 超过大小上限')
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise ValueError('不是完整的 DOCX 文件，缺少或无法读取 word/document.xml') from exc
    # Do not interpret DTDs/entities; no external resources are fetched.
    probe = xml.replace(b'\x00', b'')
    if re.search(rb'<!\s*(?:DOCTYPE|ENTITY)\b', probe, re.I):
        raise ValueError('DOCX 正文包含不支持的 DTD 或实体声明')
    try:
        document = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('DOCX 正文 XML 损坏') from exc
    namespace = document.tag.removeprefix('{').split('}')[0]
    if namespace not in WORD_NAMESPACES:
        raise ValueError('不支持的 WordprocessingML 文档结构')
    q = lambda name: '{' + namespace + '}' + name
    body = document.find(q('body'))
    if body is None:
        raise ValueError('DOCX 缺少主文档正文')

    def text(element):
        if element.tag in {q('del'), q('moveFrom'), q('drawing'), q('pict'), q('object')}:
            return ''
        if element.tag == q('t'):
            return element.text or ''
        if element.tag == q('tab'):
            return '\t'
        if element.tag in {q('br'), q('cr')}:
            return '\n'
        return ''.join(text(child) for child in element)

    def cell_text(element):
        parts = []
        for child in element:
            if child.tag == q('p'):
                parts.append(text(child))
            elif child.tag == q('tbl'):
                for row in child.findall(q('tr')):
                    parts.append('\t'.join(cell_text(cell) for cell in row.findall(q('tc'))))
            elif child.tag not in {q('del'), q('moveFrom')}:
                nested = cell_text(child)
                if nested:
                    parts.append(nested)
        return '\n'.join(parts)

    units, chars, paragraph_count, table_count = [], 0, 0, 0

    def add(value, location):
        nonlocal chars
        if not value.strip():
            return
        chars += len(value)
        if chars > max_chars:
            raise ValueError('DOCX 正文超过 200 万字符上限，未建立正文索引')
        if len(units) >= MAX_BLOCKS:
            raise ValueError('DOCX 非空文本块超过 10000 项上限')
        units.append((len(units) + 1, value, location))

    def visit(container):
        nonlocal paragraph_count, table_count
        for child in container:
            if child.tag == q('p'):
                paragraph_count += 1
                add(text(child), f'正文段落 {paragraph_count}')
            elif child.tag == q('tbl'):
                table_count += 1
                for number, row in enumerate(child.findall(q('tr')), 1):
                    add('\t'.join(cell_text(cell) for cell in row.findall(q('tc'))), f'表格 {table_count} · 第 {number} 行')
            elif child.tag not in {q('del'), q('moveFrom'), q('sectPr')}:
                visit(child)

    visit(body)
    warnings = [] if units else ['DOCX 没有可提取的正文或表格文字；图片和文本框不提供 OCR，仍可按文件名搜索']
    return units, warnings
