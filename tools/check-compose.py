"""Validate the server template without reading a production upload token."""
import os
from pathlib import Path
import subprocess
import tempfile

template = Path(__file__).resolve().parents[1] / 'deploy/compose.server.yaml'
with tempfile.TemporaryDirectory(prefix='shizhi-compose-') as name:
    root = Path(name)
    (root / 'shizhi').mkdir()
    (root / 'shizhi/.env').touch()
    # The server file is a service fragment; the shared stack owns nginx_net.
    network = root / 'networks.yaml'
    network.write_text('networks:\n  nginx_net:\n    external: true\n')
    subprocess.run(['docker', 'compose', '--project-directory', str(root), '-f', str(template), '-f', str(network), 'config', '--quiet'], env={**os.environ, 'SHIZHI_IMAGE': 'shizhi:ci'}, check=True)
print('PASS Compose template with an isolated empty upload env file')
