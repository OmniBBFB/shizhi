import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from web.controller import Controller
from web.model import Library


class MetadataPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.collection = self.root / 'kb-notes'
        self.collection.mkdir()
        self.metadata = self.collection / 'metadata.json'
        self.metadata.write_text(json.dumps({'title': 'Before', 'unused_download_metadata': 'x' * 1_000_000}))
        self.library = Library(self.root)

    def test_clicking_between_pages_does_not_reparse_unchanged_metadata(self):
        with patch('web.model.json.loads', wraps=json.loads) as decode:
            for _ in range(4):
                self.assertEqual(self.library.catalog()[0]['title'], 'Before')
            self.assertEqual(decode.call_count, 1)

    def test_scp_metadata_replacement_and_new_files_are_visible_immediately(self):
        self.library.catalog()
        original = self.metadata.stat()
        replacement = self.collection / 'replacement.json'
        replacement.write_text(self.metadata.read_text().replace('Before', 'After!'))
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(self.metadata)
        (self.collection / 'new.pdf').write_bytes(b'%PDF')
        video = self.library.catalog()[0]
        self.assertEqual(video['title'], 'After!')
        self.assertEqual(video['pdf_count'], 1)
        (self.collection / 'new.pdf').unlink()
        self.assertEqual(self.library.catalog()[0]['pdf_count'], 0)

    def test_cached_metadata_is_not_used_after_replacement_with_a_symlink(self):
        self.library.catalog()
        private = self.root / 'private.json'
        private.write_text('{"title":"must not appear"}')
        self.metadata.unlink()
        self.metadata.symlink_to(private)
        video = self.library.catalog()[0]
        self.assertEqual(video['title'], 'kb-notes')
        self.assertTrue(video['warning'])


class FileRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        folder = self.root / 'kb-notes'
        folder.mkdir()
        self.path = folder / 'note.pdf'
        self.path.write_bytes(b'0123456789')

    def request(self, headers=None, *, static=False):
        handler = object.__new__(Controller)
        handler.headers = headers or {}
        handler.command = 'GET'
        handler.wfile = io.BytesIO()
        result = {'headers': {}}
        handler.send_response = lambda status: result.update(status=status)
        handler.send_header = lambda key, value: result['headers'].update({key: value})
        handler.end_headers = lambda: None
        handler.file(self.path, static=static)
        result['body'] = handler.wfile.getvalue()
        return result

    def test_static_assets_revalidate_without_retransmitting_the_body(self):
        first = self.request(static=True)
        self.assertIn('ETag', first['headers'])
        self.assertIn('must-revalidate', first['headers']['Cache-Control'])
        second = self.request({'If-None-Match': first['headers']['ETag']}, static=True)
        self.assertEqual(second['status'], 304)
        self.assertEqual(second['body'], b'')
        # Nginx gzip weakens strong ETags. Weak validators still match for GET.
        self.assertEqual(self.request({'If-None-Match': 'W/' + first['headers']['ETag']})['status'], 304)

    def test_changed_files_invalidate_cached_responses_and_preserve_ranges(self):
        first = self.request()
        self.assertIn('ETag', first['headers'])
        self.path.write_bytes(b'abcdefghij')
        second = self.request({'If-None-Match': first['headers']['ETag']})
        self.assertEqual(second['status'], 200)
        self.assertNotEqual(second['headers']['ETag'], first['headers']['ETag'])
        ranged = self.request({'Range': 'bytes=2-5', 'If-Range': second['headers']['ETag']})
        self.assertEqual((ranged['status'], ranged['body']), (206, b'cdef'))
        stale_range = self.request({'Range': 'bytes=2-5', 'If-Range': first['headers']['ETag']})
        self.assertEqual((stale_range['status'], stale_range['body']), (200, b'abcdefghij'))
