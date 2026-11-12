"""Real Word/PDF conversion and upload-boundary checks; no paid model calls."""
import base64
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
import io

from manuscript_upload import extract_upload, MAX_FILE_BYTES, MAX_TEXT_BYTES

TEXT = 'Manuscript upload validation. We compare language models under equivalent hardware and decoding settings. '


def docx_bytes(text):
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:body></w:document>')
    return buffer.getvalue()


def payload(name, content):
    return {'filename': name, 'content_base64': base64.b64encode(content).decode()}


def fixtures(folder):
    directory = Path(folder)
    document = directory / 'manuscript.docx'
    document.write_bytes(docx_bytes(TEXT * 5))
    (directory / 'manuscript.docs').write_bytes(document.read_bytes())
    for extension in ['doc:MS Word 97', 'pdf:writer_pdf_Export']:
        subprocess.run(['libreoffice', f'-env:UserInstallation={(directory / "fixture-profile").as_uri()}',
                        '--headless', '--convert-to', extension, '--outdir', folder, str(document)],
                       check=True, capture_output=True, timeout=60)
    return [directory / f'manuscript.{suffix}' for suffix in ['doc', 'docx', 'docs', 'pdf']]


def invalid(value, message):
    try:
        extract_upload(value)
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError('Invalid upload accepted')


def main():
    assert extract_upload(payload('中文.DOCX', docx_bytes('中文稿件与证据。')))['text'] == '中文稿件与证据。'
    with tempfile.TemporaryDirectory() as folder:
        for path in fixtures(folder):
            assert path.exists(), path
            result = extract_upload(payload(path.name, path.read_bytes()))
            assert TEXT.strip() in ' '.join(result['text'].split()), path
            assert result['characters'] > 200
    invalid([], '无效')
    invalid(payload('script.exe', b'hello'), '请选择')
    invalid({'filename':'test.pdf','content_base64':'!'}, '传输无效')
    invalid(payload('test.pdf', b'not a PDF'), '有效的 PDF')
    invalid(payload('test.doc', b'not a Word file'), '有效的 Word')
    invalid(payload('empty.pdf', b''), '非空')
    invalid(payload('broken.docx', b'PKbroken'), '无法读取')
    invalid(payload('empty.docx', docx_bytes('')), '未提取到正文')
    invalid(payload('large.docx', docx_bytes('x' * (MAX_TEXT_BYTES + 1))), '1.5 MB')
    invalid(payload('bomb.docx', docx_bytes('x' * (10 * 1024 * 1024 + 1))), '解压后的正文过大')
    invalid(payload('large.pdf', b'x' * (MAX_FILE_BYTES + 1)), '15 MB')
    with patch('manuscript_upload.subprocess.run', side_effect=subprocess.TimeoutExpired('pdftotext', 60)):
        invalid(payload('timeout.pdf', b'%PDF-1.4'), '转换超时')
    with patch('manuscript_upload.subprocess.run'):
        invalid(payload('missing.pdf', b'%PDF-1.4'), '无法转换')
    print('passed: real DOC/DOCX/DOCS/PDF, Unicode, corrupt/empty/oversized files, expanded XML limit and converter timeout')


if __name__ == '__main__':
    main()
