import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from web.model import Library


class ExportTests(unittest.TestCase):
    def test_snapshot_preserves_catalog_and_excludes_nonreading_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            video = source / 'BV144nc6KEA4'
            part = video / 'P01'
            part.mkdir(parents=True)
            (video / 'metadata.json').write_text(json.dumps({'title': '课程', 'pages': [{'page': 1, 'part': '第一讲'}]}))
            (video / 'cover.jpg').write_bytes(b'cover')
            (part / 'note.pdf').write_bytes(b'%PDF')
            (part / 'notes.md').write_text('# 学习笔记')
            (part / 'transcript.jsonl').write_text('{"start": 0, "text": "字幕"}')
            (part / 'source.mp4').write_bytes(b'video')
            (part / '.env').write_text('secret')
            (part / 'build.py').write_text('private')
            (part / 'frames').mkdir()
            (part / 'frames/frame.jpg').write_bytes(b'frame')
            (part / 'linked.txt').symlink_to(part / '.env')
            (video / 'P02').symlink_to(part, target_is_directory=True)
            (source / 'other').mkdir()
            (source / 'other/private.pdf').write_bytes(b'private')
            archive = root / 'reading.tar.gz'
            subprocess.run([sys.executable, 'scripts/export_data.py', '--source', str(source), '--output', str(archive)], check=True, capture_output=True)
            destination = root / 'restored'
            destination.mkdir()
            with tarfile.open(archive) as bundle:
                self.assertEqual(set(bundle.getnames()), {
                    'BV144nc6KEA4/metadata.json', 'BV144nc6KEA4/cover.jpg',
                    'BV144nc6KEA4/P01/note.pdf', 'BV144nc6KEA4/P01/notes.md',
                    'BV144nc6KEA4/P01/transcript.jsonl'})
                # The archive was just produced from this fixture and names were checked.
                bundle.extractall(destination)
            self.assertEqual(Library(source).catalog(), Library(destination).catalog())

    def test_health_check_does_not_require_reading_the_catalog(self):
        from web.tests.test_library import RoutesTests
        case = RoutesTests()
        case.setUp()
        try:
            case.lib.catalog = lambda: self.fail('health check scanned the library')
            self.assertEqual(case.request('/healthz')['body'], b'ok\n')
        finally:
            case.doCleanups()
