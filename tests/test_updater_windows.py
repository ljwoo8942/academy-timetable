import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from academy_timetable.updater import launch_update, prepare_install


@unittest.skipUnless(os.name == 'nt', 'Native Windows update helper')
class WindowsUpdateTests(unittest.TestCase):
    def test_running_portable_app_is_replaced_after_exit_and_restarted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            portable = root / 'portable app'
            portable.mkdir()
            stage = root / 'download'
            stage.mkdir()
            target, payload = portable / 'App.exe', stage / 'new.exe'
            powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            old_code = 'public class OldApp { public static void Main() { while (!System.IO.File.Exists(System.IO.Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "stop"))) System.Threading.Thread.Sleep(20); } }'
            new_code = 'public class NewApp { public static void Main() { System.IO.File.WriteAllText(System.IO.Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "updated"), "new"); } }'
            commands = '\n'.join(f"Add-Type -TypeDefinition '{code}' -OutputAssembly '{str(path).replace(chr(39), chr(39) * 2)}' -OutputType WindowsApplication"
                                 for code, path in ((old_code, target), (new_code, payload)))
            subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', "$ErrorActionPreference='Stop';" + commands],
                           check=True, capture_output=True, timeout=60)
            expected = payload.read_bytes()
            old = subprocess.Popen([str(target)])
            helpers = []
            real_popen = subprocess.Popen

            def start_helper(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                helpers.append(process)
                return process

            try:
                self.assertIsNone(old.poll())
                config = prepare_install(payload, 'windows-portable', target)
                config.update(pid=old.pid, parent_pid=0, executable=str(target))
                with patch('academy_timetable.updater.subprocess.Popen', side_effect=start_helper):
                    log = launch_update(config)
                (portable / 'stop').touch()
                old.wait(timeout=20)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if (portable / 'updated').exists() and log.exists() and 'Update installed and app restarted.' in log.read_text():
                        break
                    time.sleep(0.05)
                self.assertEqual((portable / 'updated').read_text(), 'new')
                self.assertEqual(target.read_bytes(), expected)
                helpers[0].wait(timeout=10)
                self.assertEqual(helpers[0].returncode, 0, log.read_text())
                self.assertFalse(list(portable.glob('*.previous')))
            finally:
                for process in [old, *helpers]:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
