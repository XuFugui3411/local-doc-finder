from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject
import zipfile
from xml.sax.saxutils import escape


def docx(path, body=None, paragraphs=None):
    if body is None:
        body = ''.join('<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>' for text in paragraphs or [])
    xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '</w:body></w:document>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as package:
        package.writestr('word/document.xml', xml)
        package.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')


def pdf(path, texts, password=None):
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})})
        stream = DecodedStreamObject()
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(('BT /F1 12 Tf 40 720 Td (' + escaped + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if password:
        writer.encrypt(password, algorithm='RC4-128')
    writer.write(path)


def scanned_pdf(path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    image = DecodedStreamObject()
    image.set_data(b'\x90\x90\x90')
    image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                  NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                  NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im0'): writer._add_object(image)})})
    stream = DecodedStreamObject()
    stream.set_data(b'q 200 0 0 200 0 0 cm /Im0 Do Q')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)
