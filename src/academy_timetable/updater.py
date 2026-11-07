"""로그인 없이 공개 배포를 확인하고 검증된 파일로 앱을 교체한다."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

API_URL = 'https://api.github.com/repos/ljwoo8942/academy-timetable/releases/latest'
DOWNLOAD_ROOT = 'https://github.com/ljwoo8942/academy-timetable/releases/download/'
MANIFEST = 'AcademyTimetable-update.json'
MAX_DOWNLOAD = 512 * 1024 * 1024


class UpdateCancelled(Exception):
    pass


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != 'https' or url.hostname not in (
            'github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'
        ) or url.username or url.password:
            raise ValueError('공식 GitHub 다운로드 주소가 아닙니다.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_open = build_opener(SafeRedirect()).open


def _request(url):
    return Request(url, headers={'User-Agent': 'AcademyTimetable-Updater', 'Accept': 'application/vnd.github+json'})


def _json(url):
    with _open(_request(url), timeout=15) as response:
        data = response.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise ValueError('업데이트 정보가 너무 큽니다.')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('업데이트 정보 형식이 올바르지 않습니다.')
    return value


def version_tuple(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('앱 버전 정보를 확인할 수 없습니다.')
    return tuple(map(int, value.split('.')))


def check_update(current_version, asset_name, *, current_build=''):
    current = version_tuple(current_version)
    release = _json(API_URL)
    if release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('정식 공개 배포가 아닙니다.')
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag or len(tag) > 200:
        raise ValueError('공개 배포 정보를 확인할 수 없습니다.')
    assets = {asset['name']: asset for asset in release.get('assets', [])}
    if MANIFEST not in assets:
        raise ValueError('현재 공개 배포에는 자동 업데이트 정보가 없습니다. 새 배포가 완료된 뒤 다시 확인하세요.')

    def asset_url(name):
        expected = DOWNLOAD_ROOT + quote(tag, safe='') + '/' + name
        if assets.get(name, {}).get('browser_download_url') != expected:
            raise ValueError('공식 배포 파일의 업데이트 정보가 없거나 올바르지 않습니다.')
        return expected

    manifest = _json(asset_url(MANIFEST))
    if manifest.get('schema') != 1:
        raise ValueError('지원하지 않는 업데이트 정보입니다.')
    latest = version_tuple(manifest.get('version'))
    build = manifest.get('build')
    if not isinstance(build, str) or not re.fullmatch('[0-9a-f]{40}', build):
        raise ValueError('배포 빌드 정보가 올바르지 않습니다.')
    if latest < current or (latest == current and (not current_build or current_build == build)):
        return None
    url = asset_url(asset_name)
    metadata = manifest.get('assets', {}).get(asset_name, {})
    size, digest = metadata.get('size'), metadata.get('sha256')
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('배포 파일의 크기 또는 검증값이 올바르지 않습니다.')
    asset = assets[asset_name]
    if asset.get('size', size) != size or asset.get('digest', 'sha256:' + digest) not in (None, 'sha256:' + digest):
        raise ValueError('배포 파일과 업데이트 정보가 일치하지 않습니다.')
    return {'version': manifest['version'], 'build': build, 'name': asset_name, 'url': url, 'size': size, 'sha256': digest}


def download_update(release, folder, *, cancelled=lambda: False, progress=lambda value: None):
    folder = Path(folder)
    partial = folder / (release['name'] + '.part')
    destination = folder / release['name']
    total, digest, deadline = 0, hashlib.sha256(), time.monotonic() + 600
    try:
        with _open(_request(release['url']), timeout=15) as response, partial.open('xb') as output:
            while True:
                if cancelled():
                    raise UpdateCancelled()
                if time.monotonic() > deadline:
                    raise TimeoutError('다운로드 시간이 초과되었습니다. 다시 시도하세요.')
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > release['size']:
                    raise ValueError('배포 파일의 크기가 일치하지 않습니다.')
                output.write(chunk)
                digest.update(chunk)
                progress(total * 100 // release['size'])
        if total != release['size'] or digest.hexdigest() != release['sha256']:
            raise ValueError('다운로드 검증에 실패했습니다. 앱은 변경되지 않았습니다.')
        partial.replace(destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def install_target():
    if not getattr(sys, 'frozen', False):
        raise ValueError('소스 실행 중에는 앱을 교체하지 않습니다. 배포 실행 파일에서 업데이트하세요.')
    executable = Path(sys.executable).resolve()
    if sys.platform == 'win32':
        installed = Path(os.environ['LOCALAPPDATA']) / 'Programs/AcademyTimetable/AcademyTimetable.exe'
        mode = 'windows-installer' if executable == installed.resolve() else 'windows-portable'
        return mode, executable, 'AcademyTimetable-Setup.exe' if mode == 'windows-installer' else 'AcademyTimetable.exe'
    if sys.platform == 'darwin' and platform.machine() == 'arm64':
        bundle = executable.parent.parent.parent
        if bundle.suffix == '.app' and executable.parent.name == 'MacOS':
            if not os.access(bundle.parent, os.W_OK):
                raise ValueError('앱 폴더에 쓰기 권한이 없습니다. Finder에서 앱을 사용자 응용 프로그램 폴더로 옮긴 뒤 다시 실행하세요.')
            return 'macos', bundle, 'AcademyTimetable-macOS-arm64.zip'
    raise ValueError('자동 업데이트는 Windows x64와 Apple Silicon Mac 배포 앱에서 지원합니다.')


def validate_mac_archive(archive, app_name):
    total = 0
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist()) > 20000:
            raise ValueError('앱 압축 파일에 항목이 너무 많습니다.')
        for info in source.infolist():
            # ditto는 UTF-8 이름을 ZIP의 UTF-8 플래그 없이 기록하기도 한다.
            name = info.filename if info.flag_bits & 0x800 else info.filename.encode('cp437').decode('utf-8')
            path = PurePosixPath(unicodedata.normalize('NFC', name))
            total += info.file_size
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in (app_name, '__MACOSX') or total > 2 * 1024**3:
                raise ValueError('안전하지 않은 앱 압축 파일입니다.')
            if stat.S_ISLNK(info.external_attr >> 16):
                if info.file_size > 4096:
                    raise ValueError('잘못된 앱 링크입니다.')
                target = unicodedata.normalize('NFC', source.read(info).decode('utf-8'))
                resolved = posixpath.normpath(str(path.parent / target))
                if PurePosixPath(target).is_absolute() or not resolved.startswith(app_name + '/'):
                    raise ValueError('앱 폴더 밖을 가리키는 링크입니다.')


def prepare_install(payload, mode, target):
    stage = payload.parent
    config = {'mode': mode, 'payload': str(payload), 'target': str(target), 'pid': os.getpid(),
              'parent_pid': os.getppid(), 'executable': sys.executable, 'stage': str(stage)}
    if mode == 'macos':
        validate_mac_archive(payload, '학원 시간표.app')
        install_stage = Path(tempfile.mkdtemp(prefix='.AcademyTimetable-update-', dir=target.parent))
        try:
            subprocess.run(['/usr/bin/ditto', '-x', '-k', str(payload), str(install_stage)], check=True, timeout=120)
            incoming = install_stage / '학원 시간표.app'
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(incoming)], check=True, timeout=60)
            config.update(incoming=str(incoming), previous=str(install_stage / 'previous.app'), install_stage=str(install_stage))
        except Exception:
            shutil.rmtree(install_stage)
            raise
    return config


def cleanup_update(config):
    if config.get('install_stage'):
        shutil.rmtree(config['install_stage'], ignore_errors=True)
    shutil.rmtree(config['stage'], ignore_errors=True)


def launch_update(config):
    stage = Path(config['stage'])
    suffix = 'ps1' if config['mode'].startswith('windows-') else 'sh'
    script = stage / ('apply-update.' + suffix)
    source = Path(__file__).with_name('updater_windows.ps1' if suffix == 'ps1' else 'updater_macos.sh')
    script.write_text(source.read_text(encoding='utf-8'), encoding='utf-8-sig' if suffix == 'ps1' else 'utf-8')
    if suffix == 'ps1':
        settings = stage / 'install.json'
        settings.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        args = [powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), str(settings)]
        options = {'creationflags': 0x08000000 | 0x00000008}
    else:
        args = ['/bin/bash', str(script), str(config['pid']), config['target'], config['incoming'],
                config['previous'], config['install_stage'], config['stage']]
        options = {'start_new_session': True}
    env = dict(os.environ)
    env.pop('DYLD_LIBRARY_PATH', None)
    # 재시작한 앱이 이전 PyInstaller 임시 폴더를 재사용하지 않게 한다.
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    log_path = stage.with_suffix('.log')
    dll_directory = None
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        import ctypes
        dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        dll_directory.argtypes = [ctypes.c_wchar_p]
        dll_directory(None)
    try:
        with log_path.open('wb') as log:
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             env=env, close_fds=True, **options)
    finally:
        if dll_directory is not None:
            dll_directory(sys._MEIPASS)
    return log_path
