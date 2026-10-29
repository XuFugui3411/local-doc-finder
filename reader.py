"""Escaped body-text view; DOCX layout and page numbers are not simulated."""
from html import escape
from extraction import extract_docx


def docx_view(name, data, identifier):
    units, warnings = extract_docx(data)
    blocks = ''.join(f'<section class="block" id="block-{number}"><h2>{escape(location)}</h2><pre>{escape(text)}</pre></section>'
                     for number, text, location in units)
    issues = ''.join(f'<p class="warning">{escape(warning)}</p>' for warning in warnings)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(name)} · 提取文本</title>
<link rel="stylesheet" href="/reader.css"></head><body><main><header><p class="eyebrow">LOCAL DOC FINDER</p>
<h1>{escape(name)}</h1><p>DOCX 提取文本视图 · 按正文段落和表格行定位，不是 Word 排版或固定页码。图片、文本框、页眉页脚和批注不在本视图中。</p>
<a href="/document?id={identifier}&amp;download=1">下载原 DOCX，用 Word / WPS 查看完整排版</a></header>{issues}{blocks}</main></body></html>'''.encode('utf-8')
