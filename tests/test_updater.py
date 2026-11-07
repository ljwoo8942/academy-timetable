import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import importlib.util
import shlex
import shutil
import subprocess
import struct

from academy_timetable import updater


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name).resolve()
        self.payload = b'tested executable'
        self.name = 'AcademyTimetable.exe'
        self.url = updater.DOWNLOAD_ROOT + 'desktop-test/' + self.name
        self.release = {'tag_name': 'desktop-test', 'draft': False, 'prerelease': False,
                        'assets': [{'name': updater.MANIFEST, 'browser_download_url':
                                    updater.DOWNLOAD_ROOT + 'desktop-test/' + updater.MANIFEST},
                                   {'name': self.name, 'browser_download_url': self.url}]}
        self.manifest = {'schema': 1, 'version': '0.3.0', 'build': 'a' * 40, 'assets': {self.name: {
            'size': len(self.payload), 'sha256': hashlib.sha256(self.payload).hexdigest()}}}

    def tearDown(self):
        self.folder.cleanup()

    def response(self, request, timeout):
        self.assertFalse(request.has_header('Authorization'))
        self.assertNotIn('access_token', request.full_url)
        if request.full_url == updater.API_URL:
            data = json.dumps(self.release).encode()
        elif request.full_url.endswith(updater.MANIFEST):
            data = json.dumps(self.manifest).encode()
        else:
            self.assertEqual(request.full_url, self.url)
            data = self.payload
        return io.BytesIO(data)

    def test_public_update_checks_version_and_download_integrity_without_login(self):
        with patch.object(updater, '_open', side_effect=self.response):
            release = updater.check_update('0.2.0', self.name)
            self.assertEqual(release['version'], '0.3.0')
            result = updater.download_update(release, self.root)
            self.assertEqual(result.read_bytes(), self.payload)
            self.assertIsNone(updater.check_update('0.3.0', self.name))
            self.assertIsNone(updater.check_update('0.4.0', self.name))
            self.assertIsNotNone(updater.check_update('0.3.0', self.name, current_build='b' * 40))
            self.assertIsNotNone(updater.check_update('0.3.0', self.name, current_build='local'))
            self.assertIsNone(updater.check_update('0.3.0', self.name, current_build='a' * 40))

    def test_invalid_source_hash_length_and_cancellation_never_leave_a_payload(self):
        with patch.object(updater, '_open', side_effect=self.response):
            self.release['assets'][1]['browser_download_url'] = 'https://example.com/app.exe'
            with self.assertRaises(ValueError):
                updater.check_update('0.2.0', self.name)
            self.release['assets'][1]['browser_download_url'] = self.url
            release = updater.check_update('0.2.0', self.name)
            for changes in ({'sha256': '0' * 64}, {'size': len(self.payload) + 1}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    updater.download_update({**release, **changes}, self.root)
                self.assertEqual(list(self.root.iterdir()), [])
            with self.assertRaises(updater.UpdateCancelled):
                updater.download_update(release, self.root, cancelled=lambda: True)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_legacy_releases_and_untrusted_redirects_are_handled(self):
        self.release['assets'] = []
        with patch.object(updater, '_open', side_effect=self.response):
            with self.assertRaisesRegex(ValueError, '업데이트 정보'):
                updater.check_update('0.2.0', self.name)
        for url in ('http://github.com/file', 'https://example.com/file', 'https://github.com.evil.test/file'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                updater.SafeRedirect().redirect_request(None, None, 302, '', {}, url)

    def test_platform_selection_preserves_installed_and_portable_locations(self):
        installed = self.root / 'Programs/AcademyTimetable/AcademyTimetable.exe'
        with patch.object(updater.sys, 'platform', 'win32'), \
             patch.dict(os.environ, LOCALAPPDATA=str(self.root)), \
             patch.object(updater.sys, 'frozen', True, create=True):
            with patch.object(updater.sys, 'executable', str(installed)):
                self.assertEqual(updater.install_target(), ('windows-installer', installed, 'AcademyTimetable-Setup.exe'))
            portable = self.root / 'downloads/My App.exe'
            with patch.object(updater.sys, 'executable', str(portable)):
                self.assertEqual(updater.install_target(), ('windows-portable', portable, self.name))

    def test_mac_archive_validation_allows_internal_links_and_rejects_escapes(self):
        for name, link, valid in (('App.app/Contents/file', None, True),
                                  ('App.app/Contents/link', 'file', True),
                                  ('App.app/Contents/link', '../../../outside', False),
                                  ('../outside', None, False), ('/outside', None, False)):
            archive = self.root / 'app.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                info = zipfile.ZipInfo(name)
                if link is not None:
                    info.external_attr = (0o120777 << 16)
                output.writestr(info, link or 'file data')
            with self.subTest(name=name, link=link):
                if valid:
                    updater.validate_mac_archive(archive, 'App.app')
                else:
                    with self.assertRaises(ValueError):
                        updater.validate_mac_archive(archive, 'App.app')

    def test_release_manifest_matches_the_exact_files_and_build(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/create-update-manifest.py'
        spec = importlib.util.spec_from_file_location('update_manifest', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in ('AcademyTimetable-Setup.exe', self.name, 'AcademyTimetable-macOS-arm64.zip'):
            (self.root / name).write_bytes(self.payload)
        module.create_manifest(self.root, '0.3.0', 'a' * 40)
        generated = json.loads((self.root / updater.MANIFEST).read_text())
        self.assertEqual(generated['assets'][self.name], self.manifest['assets'][self.name])
        self.assertEqual(generated['build'], 'a' * 40)
        with self.assertRaises(ValueError):
            module.create_manifest(self.root, '0.3.0', '')

    def test_mac_ditto_zip_accepts_utf8_names_without_the_zip_utf8_flag(self):
        archive = self.root / 'ditto.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('학원 시간표.app/Contents/file', 'data')
        data = bytearray(archive.read_bytes())
        for header, flag_offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
            offset = data.index(header) + flag_offset
            flags = struct.unpack_from('<H', data, offset)[0]
            struct.pack_into('<H', data, offset, flags & ~0x800)
        archive.write_bytes(data)
        updater.validate_mac_archive(archive, '학원 시간표.app')

    def test_helpers_are_detached_and_keep_user_data_out_of_the_replace_plan(self):
        payload = self.root / self.name
        payload.write_bytes(self.payload)
        target = self.root / 'portable/App.exe'
        config = updater.prepare_install(payload, 'windows-portable', target)
        with patch.dict(os.environ, SystemRoot='C:/Windows'), \
             patch.object(updater.subprocess, 'Popen') as start:
            log = updater.launch_update(config)
        args = start.call_args.args[0]
        self.assertEqual(Path(args[-2]).name, 'apply-update.ps1')
        self.assertTrue(start.call_args.kwargs['close_fds'])
        self.assertEqual(start.call_args.kwargs['creationflags'], 0x08000000)
        self.assertEqual(start.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        saved = json.loads((self.root / 'install.json').read_text())
        self.assertEqual(saved['target'], str(target))
        self.assertNotIn('database', saved)
        self.assertTrue(log.exists())

    def test_mac_preparation_failure_removes_the_staged_app_and_keeps_original(self):
        target = self.root / 'Original.app'
        target.mkdir()
        (target / 'original.txt').write_text('keep')
        payload = self.root / 'app.zip'
        payload.write_bytes(b'placeholder')
        with patch.object(updater, 'validate_mac_archive'), \
             patch.object(updater.subprocess, 'run', side_effect=OSError('codesign check failed')):
            with self.assertRaises(OSError):
                updater.prepare_install(payload, 'macos', target)
        self.assertEqual((target / 'original.txt').read_text(), 'keep')
        self.assertFalse(list(self.root.glob('.AcademyTimetable-update-*')))

    @unittest.skipIf(os.name == 'nt' or not shutil.which('bash'), 'Mac replacement script uses Bash')
    def test_mac_helper_swaps_apps_and_restores_the_original_on_launch_failure(self):
        source = Path(updater.__file__).with_name('updater_macos.sh').read_text()
        for exit_code in (0, 1):
            with self.subTest(launch_exit_code=exit_code):
                root = self.root / f'case {exit_code}'
                root.mkdir()
                install_stage, download_stage = root / 'install', root / 'download'
                install_stage.mkdir()
                download_stage.mkdir()
                target, incoming = root / 'Original.app', install_stage / 'new.app'
                for directory, value in ((target, 'old'), (incoming, 'new')):
                    directory.mkdir()
                    (directory / 'version').write_text(value)
                launch, alert = root / 'launch.sh', root / 'alert.sh'
                launch.write_text(f'#!/bin/bash\nexit {exit_code}\n')
                alert.write_text('#!/bin/bash\nexit 0\n')
                launch.chmod(0o755)
                alert.chmod(0o755)
                script = root / 'apply.sh'
                script.write_text(source.replace('/usr/bin/open', shlex.quote(str(launch)))
                                  .replace('/usr/bin/osascript', shlex.quote(str(alert))))
                result = subprocess.run([shutil.which('bash'), str(script), '2147483647', str(target), str(incoming),
                                         str(install_stage / 'previous.app'), str(install_stage), str(download_stage)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode == 0, exit_code == 0, result.stderr)
                self.assertEqual((target / 'version').read_text(), 'new' if exit_code == 0 else 'old')
                if exit_code == 0:
                    self.assertFalse(install_stage.exists())
                    self.assertFalse(download_stage.exists())
                else:
                    self.assertEqual((install_stage / 'failed.app/version').read_text(), 'new')
