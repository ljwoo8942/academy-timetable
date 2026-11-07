"""테스트가 끝난 공개 배포 파일의 버전과 SHA-256 목록을 생성한다."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib


def create_manifest(directory, version, build):
    if not re.fullmatch('[0-9a-f]{40}', build):
        raise ValueError('GITHUB_SHA가 필요합니다.')
    files = ('AcademyTimetable-Setup.exe', 'AcademyTimetable.exe', 'AcademyTimetable-macOS-arm64.zip')
    assets = {}
    for name in files:
        path = directory / name
        size = path.stat().st_size
        if not 0 < size <= 512 * 1024 * 1024:
            raise ValueError(f'잘못된 배포 파일 크기: {name}')
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        assets[name] = {'size': size, 'sha256': digest}
    manifest = {'schema': 1, 'version': version, 'build': build, 'assets': assets}
    (directory / 'AcademyTimetable-update.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    version = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())['project']['version']
    create_manifest(Path(sys.argv[1]), version, os.environ.get('GITHUB_SHA', ''))
