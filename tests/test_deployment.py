import importlib.util
import hashlib
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest

spec = importlib.util.spec_from_file_location('release', Path(__file__).resolve().parents[1] / 'deploy/remote-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class DeploymentTests(unittest.TestCase):
    def archive_fixture(self, tags=None):
        config = json.dumps({'config': {'Labels': {'org.opencontainers.image.source': 'https://github.com/OmniBBFB/shizhi'}}}).encode()
        identity = hashlib.sha256(config).hexdigest()
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name, blob in [('manifest.json', json.dumps([{'Config': identity + '.json', 'RepoTags': tags, 'Layers': []}]).encode()), (identity + '.json', config)]:
                info = tarfile.TarInfo(name)
                info.size = len(blob)
                archive.addfile(info, io.BytesIO(blob))
        blob = data.getvalue()
        return blob, {'archiveBytes': len(blob), 'archiveSha256': hashlib.sha256(blob).hexdigest(), 'imageId': 'sha256:' + identity}

    def test_receives_exact_verified_untagged_image(self):
        blob, payload = self.archive_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.tar.gz'
            self.assertEqual(release.receive_archive(io.BytesIO(blob), path, payload), payload['imageId'])
            self.assertEqual(path.read_bytes(), blob)

    def test_rejects_corrupted_truncated_or_wrong_identity_image(self):
        blob, payload = self.archive_fixture()
        cases = [(blob[:-1], payload), (blob, {**payload, 'archiveSha256': '0' * 64}), (blob, {**payload, 'imageId': 'sha256:' + '0' * 64}), (blob, {**payload, 'archiveBytes': 513 * 1024 * 1024})]
        for source, metadata in cases:
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                release.receive_archive(io.BytesIO(source), Path(directory) / 'image.tar.gz', metadata)

    def test_rejects_archive_that_could_overwrite_another_image_tag(self):
        blob, payload = self.archive_fixture(['other-project:latest'])
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            release.receive_archive(io.BytesIO(blob), Path(directory) / 'image.tar.gz', payload)

    def test_only_shizhi_digest_is_allowed(self):
        image = release.IMAGE + '@sha256:' + 'a' * 64
        self.assertTrue(release.valid_image(image))
        for invalid in [image.replace('/shizhi@', '/bbns@'), image.replace('/shizhi@', '/board-games@'), release.IMAGE + ':latest', image + '; id', None]:
            self.assertFalse(release.valid_image(invalid))

    def test_only_image_setting_changes(self):
        source = '# shared stack\nBBNS_IMAGE=retained:1\nSHIZHI_IMAGE=old:1\nPRIVATE_SETTING=retained\n'
        self.assertEqual(release.update_image_env(source, 'new:1'), source.replace('SHIZHI_IMAGE=old:1', 'SHIZHI_IMAGE=new:1'))
        for invalid in ['OTHER_IMAGE=old\n', 'SHIZHI_IMAGE=a\nexport SHIZHI_IMAGE=b\n']:
            with self.assertRaises(ValueError):
                release.update_image_env(invalid, 'new')

    def test_atomic_env_replacement_keeps_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('SHIZHI_IMAGE=old\n')
            path.chmod(0o600)
            release.atomic_write(path, 'SHIZHI_IMAGE=new\n')
            self.assertEqual(path.read_text(), 'SHIZHI_IMAGE=new\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_backup_preserves_material_bytes_permissions_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'data', Path(directory) / 'snapshot'
            source.mkdir(mode=0o700)
            material = source / 'note.pdf'
            material.write_bytes(b'%PDF-fixture')
            material.chmod(0o600)
            release.copy_tree_owned(source, target)
            self.assertEqual((target / 'note.pdf').read_bytes(), material.read_bytes())
            for old in [source, material]:
                new = target / old.relative_to(source)
                self.assertEqual(new.stat().st_mode & 0o777, old.stat().st_mode & 0o777)
                self.assertEqual((new.stat().st_uid, new.stat().st_gid), (old.stat().st_uid, old.stat().st_gid))


if __name__ == '__main__':
    unittest.main()
