"""Fingerprint packaged Python source only; never read configuration or data."""
import hashlib
from pathlib import Path


def source_build_id(directory):
    digest = hashlib.sha256()
    for path in sorted(Path(directory).glob('*.py'), key=lambda p: p.name):
        digest.update(path.name.encode('utf-8') + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()[:20]


# Frozen on startup: changing files without restarting must not claim a new build.
BUILD_ID = source_build_id(Path(__file__).parent)
