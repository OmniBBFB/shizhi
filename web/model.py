"""Model: the BV directories are the only content store; nothing is persisted."""
import json
import re
from pathlib import Path
from urllib.parse import quote

BV = re.compile(r'BV[0-9A-Za-z]{10}')
PART = re.compile(r'P\d+')
PUBLIC = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.md', '.txt', '.tex', '.zip', '.srt', '.vtt', '.jsonl'}


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def safe_file(self, relative):
        path = Path(relative)
        if path.is_absolute() or not path.parts or not BV.fullmatch(path.parts[0]):
            raise FileNotFoundError(relative)
        target = self.root / path
        if any(p.is_symlink() for p in [target, *target.parents] if p != self.root and self.root in p.parents):
            raise FileNotFoundError(relative)
        resolved = target.resolve()
        if not resolved.is_relative_to(self.root / path.parts[0]) or not resolved.is_file() or resolved.suffix.lower() not in PUBLIC:
            raise FileNotFoundError(relative)
        return resolved

    def files(self, folder):
        return sorted((p for p in folder.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in PUBLIC), key=lambda p: p.name)

    def link(self, path):
        return '/files/' + quote(path.relative_to(self.root).as_posix(), safe='/')

    @staticmethod
    def metadata(folder):
        try:
            path = folder / 'metadata.json'
            if path.is_symlink():
                return {}, '元数据为符号链接，未读取'
            data = json.loads(path.read_text(encoding='utf-8'))
            data = data.get('data', data)
            if not isinstance(data, dict):
                raise ValueError('metadata must be an object')
            data['pages'] = data.get('pages') if isinstance(data.get('pages'), list) else []
            data['owner'] = data.get('owner') if isinstance(data.get('owner'), dict) else {}
            return data, ''
        except (OSError, ValueError, AttributeError):
            return {}, '元数据缺失或无法读取，使用目录名称'

    def unit(self, folder, title):
        files = self.files(folder)
        def group(extension):
            return [{'name': p.name, 'url': self.link(p)} for p in files if p.suffix.lower() in extension]
        return {'id': folder.name, 'title': title, 'pdfs': group({'.pdf'}), 'documents': group({'.md', '.txt'}),
                'downloads': group({'.pdf', '.zip', '.tex', '.md', '.srt', '.vtt', '.jsonl'}),
                'transcript': next((self.link(p) for p in files if p.name == 'transcript.jsonl'), None)}

    def catalog(self):
        videos = []
        for folder in sorted(self.root.iterdir()):
            if not BV.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
                continue
            data, warning = self.metadata(folder)
            pages = {f"P{int(p['page']):02d}": p for p in data.get('pages', []) if isinstance(p, dict) and str(p.get('page', '')).isdigit()}
            units = []
            base = self.unit(folder, '视频讲义')
            if base['pdfs'] or base['documents'] or base['transcript']:
                base['id'] = 'main'
                units.append(base)
            for part in sorted(folder.iterdir()):
                if PART.fullmatch(part.name) and part.is_dir() and not part.is_symlink():
                    meta, _ = self.metadata(part)
                    page = pages.get(part.name, {})
                    title = page.get('part') or meta.get('title') or part.name
                    units.append(self.unit(part, str(title)))
            covers = [p for p in self.files(folder) if p.stem == 'cover' and p.suffix in {'.jpg', '.png', '.webp'}]
            videos.append({'id': folder.name, 'title': str(data.get('title') or folder.name),
                           'author': str((data.get('owner') or {}).get('name') or ''),
                           'cover': self.link(covers[0]) if covers else None, 'warning': warning,
                           'units': units, 'pdf_count': sum(len(u['pdfs']) for u in units),
                           'part_count': sum(u['id'] != 'main' for u in units)})
        return videos

    def document(self, relative):
        path = self.safe_file(relative)
        if path.suffix not in {'.md', '.txt', '.jsonl'}:
            raise FileNotFoundError(relative)
        if path.stat().st_size > 8_000_000:
            return '文件较大，请从材料列表下载阅读。'
        return path.read_text(encoding='utf-8', errors='replace')
