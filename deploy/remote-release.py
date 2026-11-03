"""Restricted, single-service deployment for the Shizhi repository.

Read JSON from stdin. Never log credentials, full Compose config or material
names. Only the existing SHIZHI_IMAGE setting and Shizhi service can change.
"""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import time

IMAGE = 'ghcr.io/omnibbfb/shizhi'


def valid_image(image):
    return isinstance(image, str) and re.fullmatch(re.escape(IMAGE) + r'@sha256:[a-f0-9]{64}', image) is not None


def receive_archive(stream, path, payload):
    size = payload['archiveBytes']
    if type(size) is not int or not 0 < size <= 512 * 1024 * 1024:
        raise ValueError('Invalid archive size')
    image_id = payload['imageId']
    checksum = payload['archiveSha256']
    if not isinstance(image_id, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
        raise ValueError('Invalid image identity')
    if not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
        raise ValueError('Invalid archive checksum')
    digest = hashlib.sha256()
    with path.open('wb') as target:
        while size:
            chunk = stream.read(min(size, 1024 * 1024))
            if not chunk:
                raise ValueError('Truncated image archive')
            digest.update(chunk)
            target.write(chunk)
            size -= len(chunk)
    if digest.hexdigest() != checksum:
        raise ValueError('Image archive checksum mismatch')
    # Never extract into the host filesystem. Save by image ID, without tags,
    # so loading this archive cannot overwrite another project's image tag.
    with tarfile.open(path, 'r:gz') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        if len(manifest) != 1 or manifest[0].get('RepoTags'):
            raise ValueError('Expected one untagged image')
        config = archive.extractfile(manifest[0]['Config']).read()
        if 'sha256:' + hashlib.sha256(config).hexdigest() != image_id:
            raise ValueError('Image config identity mismatch')
        labels = json.loads(config).get('config', {}).get('Labels', {})
        if labels.get('org.opencontainers.image.source') != 'https://github.com/OmniBBFB/shizhi':
            raise ValueError('Expected the Shizhi image source')
    return image_id


def update_image_env(original, image):
    lines = original.splitlines()
    matches = [i for i, line in enumerate(lines) if re.match(r'^\s*(?:export\s+)?SHIZHI_IMAGE\s*=', line)]
    if len(matches) != 1:
        raise ValueError('Expected exactly one SHIZHI_IMAGE setting')
    lines[matches[0]] = 'SHIZHI_IMAGE=' + image
    return '\n'.join(lines) + '\n'


def atomic_write(path, text):
    mode = path.stat().st_mode & 0o777
    descriptor, name = tempfile.mkstemp(prefix='.shizhi-release-', dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, 'w') as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def copy_tree_owned(source, destination):
    shutil.copytree(source, destination, symlinks=True)
    for path in [source, *source.rglob('*')]:
        metadata = path.lstat()
        os.chown(destination / path.relative_to(source), metadata.st_uid, metadata.st_gid, follow_symlinks=False)


def run(command, *, cwd=None, input=None, timeout=180, capture=True):
    result = subprocess.run(command, cwd=cwd, input=input, capture_output=capture, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(command[:3]))
    return (result.stdout or '').strip()


def wait_for_uploads(container, *, timeout=600):
    until = time.monotonic() + timeout
    # Find open temporary upload files using the runtime already in the image;
    # this does not rely on the host's ps and ignores orphaned closed files.
    probe = """
from pathlib import Path
import os
busy=False
for process in Path('/proc').iterdir():
 if not process.name.isdigit():continue
 try:
  for fd in (process/'fd').iterdir():
   try:
    target=os.readlink(fd)
    if target.startswith('/data/') and Path(target).name.startswith('.upload-'):busy=True
   except OSError:pass
 except OSError:pass
print('busy' if busy else 'idle')
"""
    while run(['docker', 'exec', container, 'python', '-c', probe]) != 'idle':
        if time.monotonic() >= until:
            raise RuntimeError('Upload is busy; existing service was left running')
        time.sleep(1)


def health(container):
    probe = "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=2).read().strip()==b'ok'"
    for attempt in range(30):
        result = subprocess.run(['docker', 'exec', container, 'python', '-c', probe], capture_output=True, timeout=8)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError('Shizhi health check failed')


def deploy(payload, stream):
    image = payload['image']
    if not valid_image(image):
        raise ValueError('Only the Shizhi repository and a pinned digest are permitted')
    root = Path('/root/docker/main')
    directory = root / 'shizhi/deploy'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # BBNS and board-games use the same first lock for this shared Compose stack.
    print('Waiting for the shared deployment lock', flush=True)
    with (root / 'acquire/deploy/release.lock').open('a') as shared, (directory / 'release.lock').open('a') as own:
        fcntl.flock(shared, fcntl.LOCK_EX)
        fcntl.flock(own, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='shizhi-image-') as temporary:
            archive = Path(temporary) / 'image.tar.gz'
            print('Receiving the verified image; the existing service is still running', flush=True)
            runtime_image = receive_archive(stream, archive, payload)
            run(['docker', 'load', '--input', str(archive)], timeout=180)
        if run(['docker', 'image', 'inspect', runtime_image, '--format', '{{.Id}}']) != runtime_image:
            raise ValueError('Loaded image identity mismatch')
        base = ['docker', 'compose', '-f', str(root / 'docker-compose.yml')]
        resolved = json.loads(run(base + ['config', '--format', 'json'], cwd=root))
        previous = resolved['services']['shizhi']['image']
        env_file = root / '.env'
        updated = update_image_env(env_file.read_text(), runtime_image)
        current = run(base + ['ps', '-q', 'shizhi'], cwd=root)
        if not current:
            raise ValueError('Expected the existing Shizhi service')
        wait_for_uploads(current)
        print('Image available; backing up materials before switching Shizhi', flush=True)
        backup = root / 'shizhi/backups' / ('cicd-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(env_file, backup / 'main.env')
        shutil.copy2(root / 'docker-compose.yml', backup / 'docker-compose.yml')
        stopped, changed = False, False
        try:
            stopped = True
            run(base + ['stop', '--timeout', '60', 'shizhi'], cwd=root, timeout=90)
            copy_tree_owned(root / 'shizhi/data', backup / 'data')
            shutil.copy2(root / 'shizhi/.env', backup / 'upload.env')
            (backup / 'upload.env').chmod(0o600)
            audit = "from pathlib import Path; from web.model import Library; import json; c=Library(Path('/data')).catalog(); print(json.dumps({'collections':len(c),'readingUnits':sum(len(v['units']) for v in c),'pdfs':sum(len(u['pdfs']) for v in c for u in v['units'])}))"
            catalog = json.loads(run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--mount', 'type=bind,src=' + str(backup / 'data') + ',dst=/data,readonly', '--entrypoint', 'python', runtime_image, '-c', audit]))
            atomic_write(env_file, updated)
            changed = True
            run(base + ['config', '--quiet'], cwd=root)
            selected = json.loads(run(base + ['config', '--format', 'json'], cwd=root))
            if selected['services']['shizhi']['image'] != runtime_image:
                raise RuntimeError('Compose is not using SHIZHI_IMAGE')
            for name, service in resolved['services'].items():
                if name != 'shizhi' and selected['services'][name] != service:
                    raise RuntimeError('Unrelated Compose service would change')
            run(base + ['up', '-d', '--no-deps', 'shizhi'], cwd=root)
            container = run(base + ['ps', '-q', 'shizhi'], cwd=root)
            health(container)
            print('Shizhi is healthy', flush=True)
            result = {'ok': True, 'image': image, 'runtimeImage': runtime_image, 'archiveSha256': payload['archiveSha256'], 'previousImage': previous, 'backup': str(backup), 'container': container, **catalog}
            (directory / 'release.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result))
        except Exception:
            if changed:
                atomic_write(env_file, update_image_env(env_file.read_text(), previous))
            if stopped:
                run(base + ['up', '-d', '--no-deps', 'shizhi'], cwd=root)
            # Never restore backup data over newer uploads during image rollback.
            raise


if __name__ == '__main__':
    if os.environ.get('SSH_ORIGINAL_COMMAND') != 'deploy':
        raise SystemExit('Only the deploy command is permitted')
    header = sys.stdin.buffer.readline(32769)
    if len(header) > 32768 or not header.endswith(b'\n'):
        raise SystemExit('Invalid deployment header')
    deploy(json.loads(header), sys.stdin.buffer)
