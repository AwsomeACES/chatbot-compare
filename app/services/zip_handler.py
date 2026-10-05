import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from ..config import MAX_UPLOAD

EXCLUDED = {'.git','.venv','venv','node_modules','__pycache__','dist','build'}

def excluded(path):
    return any(p.lower() in EXCLUDED or p.lower().startswith('.env') or p.lower() in {'secrets.json','credentials.json','id_rsa','id_ed25519'} or p.lower().endswith(('.pem','.key','.pfx')) for p in path.parts)

def extract_zip(archive: Path, destination: Path):
    if archive.stat().st_size > MAX_UPLOAD:
        raise ValueError('Archive exceeds configured size limit')
    try:
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            if len(entries) > 3000:
                raise ValueError('Archive contains more than 3000 entries')
            total = 0
            names = set()
            for item in entries:
                name = item.filename.replace('\\', '/')
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or ':' in name or '\x00' in name:
                    raise ValueError('Unsafe archive path')
                for part in path.parts:
                    if part.endswith((' ', '.')) or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I):
                        raise ValueError('Unsafe Windows archive name')
                if name.casefold() in names:
                    raise ValueError('Duplicate archive path')
                names.add(name.casefold())
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError('Symlinks and encrypted archives are unsupported')
                total += item.file_size
                if total > 150 * 1024 * 1024 or item.file_size / max(item.compress_size, 1) > 150:
                    raise ValueError('Suspicious archive expansion')
                target = (destination / Path(*path.parts)).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError('Archive escapes extraction directory')
            destination.mkdir(parents=True, exist_ok=False)
            skipped = 0
            for item in entries:
                path = PurePosixPath(item.filename.replace('\\','/'))
                if excluded(path) or item.file_size > 2 * 1024 * 1024:
                    skipped += 1
                    continue
                target = destination / Path(*path.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, target.open('wb') as dst:
                        shutil.copyfileobj(src, dst, 65536)
            return {'archive_entries': len(entries), 'skipped_entries': skipped, 'expanded_bytes': total}
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError('Invalid or unreadable ZIP archive') from exc
