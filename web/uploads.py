"""Authenticated, bounded writes to the mounted material directory."""
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile

from .model import COLLECTION, PART, PUBLIC


class UploadError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Uploads:
    def __init__(self, library, token='', max_bytes=128 * 1024 * 1024):
        self.library = library
        self.token = token
        self.max_bytes = max_bytes

    def authorize(self, authorization):
        if not self.token:
            raise UploadError(503, '上传尚未启用，请先配置服务器上传口令。')
        expected = ('Bearer ' + self.token).encode('utf-8')
        if not hmac.compare_digest(authorization.encode('utf-8'), expected):
            raise UploadError(401, '上传口令不正确，请重新输入。')

    def create_collection(self, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise UploadError(400, '资料集名称需要填写 1 至 200 个字符。')
        collection = 'kb-' + secrets.token_hex(8)
        folder = self.library.root / collection
        folder.mkdir(mode=0o755)
        try:
            metadata = folder / 'metadata.json'
            metadata.write_text(json.dumps({'title': title.strip()}, ensure_ascii=False), encoding='utf-8')
            metadata.chmod(0o644)
        except OSError:
            # Never expose a partly written collection after a failed create.
            metadata.unlink(missing_ok=True)
            folder.rmdir()
            raise
        return {'id': collection, 'title': title.strip()}

    def destination(self, collection, part, name):
        if not COLLECTION.fullmatch(collection):
            raise UploadError(400, '资料集标识不正确，请重新选择。')
        if part and not PART.fullmatch(part):
            raise UploadError(400, '讲次应为 P01、P02 这样的目录名，或留空。')
        if (not name or name.startswith('.') or name.endswith((' ', '.')) or
                any(c in name for c in '/\\\x00:') or len(name.encode('utf-8')) > 240 or
                Path(name).suffix.lower() not in PUBLIC):
            raise UploadError(400, '文件名或类型不支持，请选择 PDF、笔记、字幕、图片、TeX 或 ZIP。')
        folder = self.library.root / collection
        if folder.is_symlink() or not folder.is_dir():
            raise UploadError(404, '资料集不存在，请刷新页面后重新选择。')
        if part:
            folder = folder / part
            if folder.is_symlink():
                raise UploadError(400, '不能向符号链接目录上传。')
            folder.mkdir(mode=0o755, exist_ok=True)
        if not folder.resolve().is_relative_to(self.library.root):
            raise UploadError(400, '目标目录超出材料范围。')
        return folder / name

    def save(self, collection, part, name, stream, length):
        if not 0 < length <= self.max_bytes:
            raise UploadError(413, f'单个文件需大于 0 字节且不超过 {self.max_bytes // 1024 // 1024} MB。')
        target = self.destination(collection, part, name)
        # A hidden temporary file never appears in the live catalog. Hard-linking
        # publishes a complete file atomically and refuses any existing name.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.upload-', dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                remaining = length
                while remaining:
                    block = stream.read(min(64 * 1024, remaining))
                    if not block:
                        raise UploadError(400, '文件未传输完整，请重新上传。')
                    output.write(block)
                    remaining -= len(block)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o644)
            try:
                os.link(temporary, target)
            except FileExistsError:
                raise UploadError(409, '已存在同名文件，请改名后重试；原文件已保留。')
            return {'name': name, 'url': self.library.link(target), 'bytes': length}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
