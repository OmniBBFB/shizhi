#!/usr/bin/env python3
"""Export only files the reader uses; never package videos or build caches."""
import argparse
import tarfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web.model import BV, PART, PUBLIC


def reading_files(source):
    for video in sorted(source.iterdir()):
        if video.is_symlink() or not video.is_dir() or not BV.fullmatch(video.name):
            continue
        folders = [video] + [p for p in sorted(video.iterdir())
                             if PART.fullmatch(p.name) and not p.is_symlink() and p.is_dir()]
        for folder in folders:
            for path in sorted(folder.iterdir()):
                if (not path.is_symlink() and path.is_file() and
                        (path.suffix.lower() in PUBLIC or path.name == 'metadata.json')):
                    yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    files = list(reading_files(source))
    if not files:
        parser.error('没有找到可导出的 BV 阅读材料')
    output = args.output.resolve()
    if output.is_relative_to(source) and output.parts[len(source.parts):][0].startswith('BV'):
        parser.error('导出包不能写入 BV 材料目录')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz', compresslevel=3) as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(source), recursive=False)
    print(f'{len(files)} files, {sum(p.stat().st_size for p in files):,} bytes -> {output}')


if __name__ == '__main__':
    main()
