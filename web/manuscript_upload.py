"""Extract uploaded Word/PDF manuscripts using local tools; never call a model."""
import base64
import binascii
from pathlib import Path
import subprocess
import tempfile
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
import io

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_TEXT_BYTES = 1_500_000
MAX_REQUEST_BYTES = 4 * ((MAX_FILE_BYTES + 2) // 3) + 4096


def extract_upload(payload):
    if not isinstance(payload, dict):
        raise ValueError('上传内容无效。')
    name, encoded = payload.get('filename'), payload.get('content_base64')
    suffix = Path(name).suffix.lower() if isinstance(name, str) else ''
    if suffix not in {'.doc', '.docx', '.docs', '.pdf'}:
        raise ValueError('请选择 DOC、DOCX、DOCS 或 PDF 文件。')
    if not isinstance(encoded, str) or len(encoded) > MAX_REQUEST_BYTES - 4096:
        raise ValueError('上传文件不能超过 15 MB。')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('文件传输无效，请重新选择文件。') from None
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('请选择非空且不超过 15 MB 的文件。')
    try:
        if suffix in {'.docx', '.docs'} and content.startswith(b'PK'):
            with ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo('word/document.xml')
                if info.file_size > 10 * 1024 * 1024:
                    raise ValueError('Word 文档解压后的正文过大，请精简后上传。')
                root = ET.fromstring(archive.read(info))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text = '\n'.join(''.join('\t' if node.tag.endswith('}tab') else '\n' if node.tag.endswith('}br') else node.text or ''
                                     for node in paragraph.iter() if node.tag in {f'{{{ns["w"]}}}t', f'{{{ns["w"]}}}tab', f'{{{ns["w"]}}}br'})
                             for paragraph in root.findall('.//w:p', ns))
        else:
            is_pdf = suffix == '.pdf'
            if is_pdf and not content.startswith(b'%PDF-'):
                raise ValueError('文件内容不是有效的 PDF。')
            if not is_pdf and not content.startswith((b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', b'{\\rtf')):
                raise ValueError('文件内容不是有效的 Word 文档；DOCS 请使用 DOCX 或 DOC 文档内容。')
            with tempfile.TemporaryDirectory(prefix='iclr-upload-') as folder:
                directory = Path(folder)
                source = directory / ('manuscript.pdf' if is_pdf else 'manuscript.doc')
                source.write_bytes(content)
                output = directory / 'manuscript.txt'
                if is_pdf:
                    command = ['pdftotext', '-layout', '-enc', 'UTF-8', str(source), str(output)]
                else:
                    command = ['libreoffice', f'-env:UserInstallation={(directory / "profile").as_uri()}',
                               '--headless', '--convert-to', 'txt:Text (encoded):UTF8', '--outdir', folder, str(source)]
                subprocess.run(command, capture_output=True, timeout=60, check=True)
                if not output.exists():
                    raise ValueError('文档无法转换，请检查文件是否损坏或受密码保护。')
                if output.stat().st_size > MAX_TEXT_BYTES:
                    raise ValueError('提取后的文本超过 1.5 MB，请精简后上传。')
                text = output.read_text(encoding='utf-8-sig')
    except (BadZipFile, KeyError, ET.ParseError, UnicodeError, subprocess.CalledProcessError):
        raise ValueError('文档无法读取，请检查文件是否损坏或受密码保护。') from None
    except subprocess.TimeoutExpired:
        raise ValueError('文档转换超时，请缩小文件后重试。') from None
    except FileNotFoundError:
        raise ValueError('服务器缺少文档转换工具，请联系管理员。') from None
    text = text.replace('\x00', '').replace('\f', '\n\n').strip()
    if not text:
        raise ValueError('未提取到正文；扫描版 PDF 或图片文档请先进行 OCR，再上传或粘贴完整文本。')
    if len(text.encode('utf-8')) > MAX_TEXT_BYTES:
        raise ValueError('提取后的文本超过 1.5 MB，请精简后上传。')
    return {'text': text, 'characters': len(text)}
