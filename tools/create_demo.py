"""Create fake sample documents, never scan or rewrite a user's documents."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from fixtures import pdf, scanned_pdf, docx


def main():
    root = ROOT / 'output' / 'demo-documents'
    root.mkdir(parents=True, exist_ok=True)
    files = {
        '项目资料/春季项目笔记.md': '# 项目笔记\n\n检索不是替你思考，而是让你重新找到思考的起点。\nAlpha 项目本周完成预算复核，新增资料统一保存在本地文档库。\n预算总额三万元，周五完成初步评审。',
        '会议记录/四月讨论.txt': '会议主题：Alpha 项目的资料检索与预算安排。\n我们决定先查看命中的原文，再核对 PDF 页码和上下文。\n所有资料保存在本机，不向外部服务上传。',
        '阅读摘录/阅读清单.md': '# 阅读清单\n\n下次读到有用的句子，记得留下原文出处。\n英文检索示例：ALPHA、Alpha 和 alpha 视为相同关键词。',
        '会议记录/测试字符.txt': '<script>alert("fixture-only")</script>\n这是一段用来验证网页安全展示的测试文本。',
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    (root / '参考资料').mkdir(exist_ok=True)
    pdf(root / '参考资料/Alpha 项目说明.pdf', ['Project overview and source documents.', 'Alpha budget review: keep the original page context.'])
    scanned_pdf(root / '参考资料/扫描件示例.pdf')
    (root / 'Word资料').mkdir(exist_ok=True)
    docx(root / 'Word资料/项目纪要.docx', body='''<w:p><w:r><w:t>Wordcheck 项目纪要：正文与表格均可在本机检索。</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>预算</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>三万元</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>文档按段落和表格行定位，不使用固定页码。</w:t></w:r></w:p>''')
    print(str(root))


if __name__ == '__main__':
    main()
