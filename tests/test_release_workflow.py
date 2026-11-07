import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "Release script runs on a Unix runner")
class ReleaseWorkflowTests(unittest.TestCase):
    def test_published_downloads_are_preserved_and_drafts_can_resume(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/build-desktop.yml").read_text()
        publish = workflow.split("      - name: Publish tested apps to GitHub Releases", 1)[1]
        script = textwrap.dedent(publish.split("        run: |\n", 1)[1])
        for case, failed, expected in (
            ("new", False, (True, True, True)),
            ("draft", False, (False, True, True)),
            ("published", False, (False, False, False)),
            ("stale", False, (False, False, False)),
            ("api_error", True, (False, False, False)),
            ("upload_error", True, (True, True, False)),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                gh = root / "gh"
                gh.write_text('''#!/bin/bash
printf '%s %s\\n' "$1" "$2" >> "$GH_LOG"
case "$1 $2" in
  'api '*)
    [ "$GH_CASE" != api_error ] || exit 1
    if [ "$GH_CASE" = stale ]; then echo older; else echo "$GITHUB_SHA"; fi ;;
  'release view')
    case "$GH_CASE" in
      draft) echo true ;;
      published) echo false ;;
      *) exit 1 ;;
    esac ;;
  'release upload') [ "$GH_CASE" != upload_error ] ;;
  'release create'|'release edit') exit 0 ;;
  *) exit 2 ;;
esac
''')
                gh.chmod(0o755)
                log = root / "calls.log"
                env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                           GH_LOG=str(log), GH_CASE=case, GH_REPO="example/timetable", GITHUB_SHA="a" * 40)
                result = subprocess.run([shutil.which("bash"), "-e", "-o", "pipefail", "-c", script],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode != 0, failed, result.stderr)
                calls = log.read_text().splitlines()
                self.assertEqual(tuple("release " + action in calls for action in ("create", "upload", "edit")), expected)
