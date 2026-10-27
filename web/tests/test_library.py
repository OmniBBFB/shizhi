import io
import json
import tempfile
import unittest
from pathlib import Path

from web.model import Library
from web import view
from web.controller import Controller


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bv = self.root / 'BV144nc6KEA4'
        self.bv.mkdir()
        (self.bv / 'metadata.json').write_text(json.dumps({'data': {'title': '<script>alert(1)</script>', 'pages': [{'page': 1, 'part': '第一讲'}]}}))
        self.lib = Library(self.root)

    def test_live_discovery_and_part_titles(self):
        part = self.bv / 'P01'
        part.mkdir()
        (part / '讲义.pdf').write_bytes(b'%PDF-test')
        video = self.lib.catalog()[0]
        self.assertEqual(video['pdf_count'], 1)
        self.assertEqual(video['units'][0]['title'], '第一讲')
        (part / '第二份.pdf').write_bytes(b'%PDF-second')
        self.assertEqual(self.lib.catalog()[0]['pdf_count'], 2)
        (part / '讲义.pdf').unlink()
        self.assertEqual(self.lib.catalog()[0]['pdf_count'], 1)

    def test_path_traversal_and_private_files_are_rejected(self):
        (self.root / 'secret.txt').write_text('private')
        (self.bv / 'build.py').write_text('private')
        (self.bv / 'linked.txt').symlink_to(self.root / 'secret.txt')
        for path in ['../secret.txt', '/etc/passwd', 'BV144nc6KEA4/../secret.txt', 'BV144nc6KEA4/build.py', 'BV144nc6KEA4/linked.txt']:
            with self.subTest(path=path), self.assertRaises(FileNotFoundError):
                self.lib.safe_file(path)
        self.assertFalse(any(f.name == 'linked.txt' for f in self.lib.files(self.bv)))

    def test_malformed_metadata_still_lists_material(self):
        (self.bv / 'metadata.json').write_text('{invalid')
        (self.bv / 'notes.pdf').write_bytes(b'%PDF')
        video = self.lib.catalog()[0]
        self.assertEqual(video['title'], self.bv.name)
        self.assertEqual(video['pdf_count'], 1)
        self.assertTrue(video['warning'])

    def test_render_escapes_untrusted_source(self):
        video = self.lib.catalog()[0]
        rendered = view.shelf([video], '<img onerror=bad>')
        self.assertNotIn('<script>alert(1)</script>', rendered)
        self.assertIn('&lt;img onerror=bad&gt;', rendered)
        self.assertIn('&lt;script&gt;', view.plain_document('# <script>'))


class RoutesTests(LibraryTests):
    def request(self, target, headers=None, method='GET'):
        # Exercise real routing and file streaming without binding a network port.
        handler = object.__new__(Controller)
        handler.library = self.lib
        handler.path = target
        handler.headers = headers or {}
        handler.command = method
        handler.wfile = io.BytesIO()
        result = {'headers': {}}
        handler.send_response = lambda status: result.update(status=status)
        handler.send_header = lambda k, v: result['headers'].update({k: v})
        handler.end_headers = lambda: None
        handler.do_GET()
        result['body'] = handler.wfile.getvalue()
        return result

    def test_routes_empty_search_errors_and_api(self):
        self.assertEqual(self.request('/')['status'], 200)
        self.assertIn('还没有匹配的视频', self.request('/?q=no-such-title')['body'].decode())
        self.assertEqual(self.request('/?video=BVxxxxxxxxxx')['status'], 404)
        self.assertEqual(self.request('/?video=BV144nc6KEA4&tab=invalid')['status'], 400)
        self.assertEqual(self.request('/static/../../model.py')['status'], 404)
        self.assertEqual(len(json.loads(self.request('/api/videos')['body'])), 1)

    def test_pdf_byte_ranges_and_head(self):
        (self.bv / 'note.pdf').write_bytes(b'0123456789')
        path = '/files/BV144nc6KEA4/note.pdf'
        full = self.request(path)
        self.assertEqual(full['body'], b'0123456789')
        partial = self.request(path, {'Range': 'bytes=2-5'})
        self.assertEqual(partial['status'], 206)
        self.assertEqual(partial['body'], b'2345')
        self.assertEqual(partial['headers']['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(self.request(path, {'Range': 'bytes=-3'})['body'], b'789')
        self.assertEqual(self.request(path, {'Range': 'bytes=90-'})['status'], 416)
        self.assertEqual(self.request(path, method='HEAD')['body'], b'')
        self.assertEqual(self.request('/files/BV144nc6KEA4/%2e%2e/secret.txt')['status'], 404)

    def test_every_reading_tab(self):
        (self.bv / 'notes.md').write_text('# 总结\n内容 <script>bad()</script>')
        (self.bv / 'note.pdf').write_bytes(b'%PDF')
        (self.bv / 'transcript.jsonl').write_text(json.dumps({'start': 61, 'text': '字幕'}))
        for tab in ['pdf', 'text', 'transcript', 'files']:
            result = self.request('/?video=BV144nc6KEA4&tab='+tab)
            self.assertEqual(result['status'], 200)
            self.assertNotIn(b'<script>bad()', result['body'])
        self.assertIn('00:01:01', self.request('/?video=BV144nc6KEA4&tab=transcript')['body'].decode())

    def test_pdfjs_assets_mime_and_boundaries(self):
        for name in ['pdf-reader.mjs', 'vendor/pdfjs/pdf.min.mjs', 'vendor/pdfjs/pdf.worker.min.mjs']:
            result = self.request('/static/' + name)
            self.assertEqual(result['status'], 200)
            self.assertIn('javascript', result['headers']['Content-Type'])
            self.assertIn("worker-src 'self'", result['headers']['Content-Security-Policy'])
        for name in ['vendor/pdfjs/PROVENANCE.json', 'vendor/pdfjs/LICENSE',
                     'vendor/pdfjs/../../../../controller.py', 'vendor/pdfjs/missing.mjs']:
            self.assertEqual(self.request('/static/' + name)['status'], 404)

    def test_pdfjs_view_keeps_file_fallback(self):
        (self.bv / '讲义.pdf').write_bytes(b'%PDF')
        result = self.request('/?video=BV144nc6KEA4&tab=pdf')
        body = result['body'].decode()
        self.assertIn('data-pdf-url="/files/BV144nc6KEA4/', body)
        self.assertIn('type="module" src="/static/pdf-reader.mjs"', body)
        self.assertIn('<noscript>', body)
        self.assertIn('下载 PDF', body)
        self.assertNotIn('<object', body)
        self.assertIn("object-src 'none'", result['headers']['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()
