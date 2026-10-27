from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from web.controller import Controller
from web.model import Library
from web.uploads import UploadError, Uploads


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library = Library(self.root)
        self.uploads = Uploads(self.library, 'test-upload-secret')
        handler = partial(Controller, library=self.library, uploads=self.uploads)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=b'', authorized=True, headers=None):
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        all_headers = {'Authorization': 'Bearer test-upload-secret'} if authorized else {}
        all_headers.update(headers or {})
        connection.request(method, path, body=body, headers=all_headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def collection(self):
        status, data, _ = self.request('POST', '/api/collections', json.dumps({'title': '学习笔记'}).encode())
        self.assertEqual(status, 201)
        return json.loads(data)['id']

    def upload_path(self, collection, filename='中文笔记.md', part=''):
        return '/api/uploads?' + urlencode({'collection': collection, 'part': part, 'filename': filename})

    def test_authenticated_upload_is_immediately_readable_without_login(self):
        collection = self.collection()
        text = '# 学习笔记\n<script>alert(1)</script>'.encode()
        status, body, _ = self.request('POST', self.upload_path(collection), text)
        self.assertEqual(status, 201)
        material = json.loads(body)
        self.assertEqual(self.request('GET', material['url'], authorized=False)[:2], (200, text))
        status, page, _ = self.request('GET', '/?' + urlencode({'video': collection}), authorized=False)
        self.assertEqual(status, 200)
        self.assertIn('&lt;script&gt;', page.decode())
        self.assertNotIn('观看原视频', page.decode())
        catalog = json.loads(self.request('GET', '/api/videos', authorized=False)[1])
        self.assertEqual(catalog[0]['title'], '学习笔记')
        self.assertTrue((self.root / collection / '中文笔记.md').is_file())

    def test_missing_wrong_and_disabled_token_cannot_write(self):
        for headers in [{}, {'Authorization': 'Bearer wrong'}]:
            self.assertEqual(self.request('POST', '/api/collections', b'{"title":"x"}', authorized=False, headers=headers)[0], 401)
        self.assertEqual(list(self.root.iterdir()), [])
        self.uploads.token = ''
        self.assertEqual(self.request('POST', '/api/collections', b'{"title":"x"}')[0], 503)
        self.assertEqual(self.request('GET', '/', authorized=False)[0], 200)

    def test_duplicate_preserves_original_and_never_leaves_temporary_files(self):
        collection = self.collection()
        path = self.upload_path(collection, 'note.pdf')
        self.assertEqual(self.request('POST', path, b'%PDF-original')[0], 201)
        self.assertEqual(self.request('POST', path, b'%PDF-new')[0], 409)
        self.assertEqual((self.root / collection / 'note.pdf').read_bytes(), b'%PDF-original')
        self.assertEqual(list(self.root.rglob('.upload-*')), [])

    def test_private_types_traversal_and_symlink_targets_are_rejected(self):
        collection = self.collection()
        for filename in ['../outside.pdf', '/etc/passwd', '.env', 'script.py', 'meta.json', 'sub\\note.pdf']:
            self.assertEqual(self.request('POST', self.upload_path(collection, filename), b'content')[0], 400, filename)
        self.assertEqual(self.request('POST', self.upload_path('../escape', 'note.pdf'), b'content')[0], 400)
        self.assertEqual(self.request('POST', self.upload_path(collection, 'note.pdf', '../P01'), b'content')[0], 400)
        (self.root / collection / 'P01').symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.request('POST', self.upload_path(collection, 'note.pdf', 'P01'), b'content')[0], 400)
        self.assertFalse((self.root / 'note.pdf').exists())

    def test_oversized_empty_and_interrupted_uploads_are_not_published(self):
        collection = self.collection()
        path = self.upload_path(collection, 'note.pdf')
        self.assertEqual(self.request('POST', path, b'')[0], 413)
        self.assertEqual(self.request('POST', path, b'x', headers={'Content-Length': str(128 * 1024 * 1024 + 1)})[0], 413)
        with self.assertRaises(UploadError):
            self.uploads.save(collection, '', 'note.pdf', io.BytesIO(b'partial'), 100)
        self.assertFalse((self.root / collection / 'note.pdf').exists())
        self.assertEqual(list(self.root.rglob('.upload-*')), [])

    def test_existing_video_part_accepts_scp_and_web_files(self):
        video = self.root / 'BV144nc6KEA4'
        video.mkdir()
        (video / 'metadata.json').write_text('{"title":"已有视频"}')
        path = self.upload_path(video.name, 'note.pdf', 'P01')
        self.assertEqual(self.request('POST', path, b'%PDF')[0], 201)
        # Simulates a file copied directly into the same mounted material folder.
        (video / 'P01/scp-note.md').write_text('# SCP 笔记')
        unit = self.library.catalog()[0]['units'][0]
        self.assertEqual(unit['id'], 'P01')
        self.assertEqual(len(unit['pdfs']), 1)
        self.assertEqual(unit['documents'][0]['name'], 'scp-note.md')

    def test_cross_origin_and_malformed_requests_fail_without_creating_data(self):
        self.assertEqual(self.request('POST', '/api/collections', b'{"title":"x"}', headers={'Origin': 'https://other.example'})[0], 403)
        for body in [b'null', b'[]', b'{"title":" "}', b'not-json']:
            self.assertEqual(self.request('POST', '/api/collections', body)[0], 400)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
