"""Controller: public reading and separately authenticated material uploads."""
import argparse
import json
import mimetypes
import os
import re
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .model import Library
from .uploads import Uploads, UploadError
from . import view

STATIC = Path(__file__).parent / 'static'
PDFJS = STATIC / 'vendor' / 'pdfjs'
PAGE_POLICY = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
               "script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; "
               "font-src 'self' blob: data:; img-src 'self' blob: data:; "
               "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def static_file(name):
    """Expose app assets and only the vendored PDF.js runtime resources."""
    if name in {'style.css', 'tokens.css', 'base.css', 'app.js', 'pdf-reader.mjs', 'upload.js'}:
        return STATIC / name
    path = Path(name)
    if '..' in path.parts or not name.startswith('vendor/pdfjs/'):
        raise FileNotFoundError(name)
    relative = path.relative_to('vendor/pdfjs')
    runtime = relative.as_posix() in {'pdf.min.mjs', 'pdf.worker.min.mjs'}
    support = (len(relative.parts) == 2 and relative.parts[0] in
               {'cmaps', 'standard_fonts', 'wasm'} and relative.suffix in
               {'.bcmap', '.ttf', '.pfb', '.wasm', '.bin', '.mjs'})
    target = STATIC / path
    if (not (runtime or support) or not target.is_file() or
            not target.resolve().is_relative_to(PDFJS.resolve()) or
            any(p.is_symlink() for p in [target, *target.parents] if p != STATIC and STATIC in p.parents)):
        raise FileNotFoundError(name)
    return target


class Controller(BaseHTTPRequestHandler):
    def __init__(self, *args, library, uploads=None, **kwargs):
        self.library = library
        self.uploads = uploads or Uploads(library)
        super().__init__(*args, **kwargs)

    def do_HEAD(self):
        self.do_GET()

    def send(self, status, content, mime='text/html; charset=utf-8'):
        body = content.encode('utf-8') if isinstance(content, str) else content
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', PAGE_POLICY)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def file(self, path, *, static=False):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        request_range = self.headers.get('Range')
        if request_range:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', request_range)
            if not match or not any(match.groups()):
                return self.range_error(size)
            a, b = match.groups()
            if not a:
                start = max(0, size - int(b))
            else:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            if start > end or start >= size:
                return self.range_error(size)
            status = 206
        with path.open('rb') as stream:
            self.send_response(status)
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            if path.suffix == '.mjs':
                mime = 'text/javascript; charset=utf-8'
            elif path.suffix == '.wasm':
                mime = 'application/wasm'
            if path.suffix in {'.md', '.tex', '.srt', '.vtt', '.jsonl', '.txt'}:
                mime = 'text/plain; charset=utf-8'
            self.send_header('Content-Type', mime)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', PAGE_POLICY if static else "default-src 'none'; sandbox")
            self.send_header('Content-Length', str(max(0, end - start + 1)))
            self.send_header('Accept-Ranges', 'bytes')
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD':
                return
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = stream.read(min(64 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def range_error(self, size):
        self.send_response(416)
        self.send_header('Content-Range', f'bytes */{size}')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        self.close_connection = True
        try:
            parsed = urlsplit(self.path)
            if parsed.path not in {'/api/collections', '/api/uploads'}:
                raise UploadError(404, '接口不存在。')
            self.uploads.authorize(self.headers.get('Authorization', ''))
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                raise UploadError(403, '请从本站上传页面提交文件。')
            if self.headers.get('Transfer-Encoding'):
                raise UploadError(400, '不支持分块编码，请使用带文件长度的上传请求。')
            try:
                length = int(self.headers.get('Content-Length', ''))
            except ValueError:
                raise UploadError(411, '上传请求需要 Content-Length。')
            if not 0 < length <= self.uploads.max_bytes:
                raise UploadError(413, '单个文件需大于 0 字节且不超过 128 MB。')
            self.connection.settimeout(60)
            if parsed.path == '/api/collections':
                if length > 4096:
                    raise UploadError(413, '资料集信息过长。')
                try:
                    data = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise UploadError(400, '资料集信息不是有效的 JSON。')
                if not isinstance(data, dict):
                    raise UploadError(400, '资料集信息格式不正确。')
                result = self.uploads.create_collection(data.get('title'))
            else:
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                result = self.uploads.save(params.get('collection', ''), params.get('part', ''),
                                           params.get('filename', ''), self.rfile, length)
            self.send(201, json.dumps(result, ensure_ascii=False), 'application/json; charset=utf-8')
        except UploadError as error:
            self.send(error.status, json.dumps({'error': str(error)}, ensure_ascii=False), 'application/json; charset=utf-8')
        except TimeoutError:
            self.send(408, '{"error":"上传超时，请检查网络后重试。"}', 'application/json; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self.send(500, '{"error":"材料无法写入，请检查挂载目录权限和剩余空间。"}', 'application/json; charset=utf-8')

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if path == '/healthz':
                return self.send(200, 'ok\n', 'text/plain; charset=utf-8')
            if path.startswith('/static/'):
                name = path.removeprefix('/static/')
                return self.file(static_file(name), static=True)
            if path.startswith('/files/'):
                return self.file(self.library.safe_file(path.removeprefix('/files/')))
            if path == '/upload':
                return self.send(200, view.upload(self.library.catalog()))
            if path not in {'/', '/api/videos'}:
                raise FileNotFoundError(path)
            videos = self.library.catalog()
            if path == '/api/videos':
                return self.send(200, json.dumps(videos, ensure_ascii=False), 'application/json; charset=utf-8')
            if not params.get('video'):
                kind = params.get('kind', 'all')
                return self.send(200, view.shelf(videos, params.get('q', ''), kind))
            video = next((v for v in videos if v['id'] == params['video']), None)
            if not video:
                raise FileNotFoundError(path)
            units = video['units']
            default_unit = next((u for u in units if u['pdfs']), units[0] if units else None)
            part = params.get('part', default_unit['id'] if default_unit else 'main')
            unit = next((u for u in units if u['id'] == part), None)
            if not unit and units:
                raise FileNotFoundError(path)
            if not unit:
                unit = {'id': 'main', 'title': '视频讲义', 'pdfs': [], 'documents': [], 'downloads': [], 'transcript': None}
            default_tab = 'pdf' if unit['pdfs'] else ('text' if unit['documents'] else 'files')
            tab = params.get('tab', default_tab)
            if tab not in {'pdf', 'text', 'transcript', 'files'}:
                return self.send(400, view.error('无法识别这个阅读标签', 400))
            return self.send(200, view.reader(self.library, video, unit, tab, params.get('doc')))
        except (FileNotFoundError, IsADirectoryError):
            self.send(404, view.error('这份材料没有找到', 404))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError, TypeError):
            self.send(500, view.error('材料暂时无法读取', 500))


def main():
    parser = argparse.ArgumentParser(description='浏览 BV 目录中的视频总结')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('SHIZHI_DATA_DIR', Path(__file__).resolve().parents[1] / 'data')))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error(f'材料目录不存在：{args.root}')
    library = Library(args.root)
    uploads = Uploads(library, os.environ.get('SHIZHI_UPLOAD_TOKEN', ''))
    server = ThreadingHTTPServer((args.host, args.port), partial(Controller, library=library, uploads=uploads))
    print(f'拾知 http://{args.host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
