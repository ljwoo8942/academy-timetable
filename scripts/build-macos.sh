#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
python="$root/.venv/bin/python"
dist="$root/dist"
app="$dist/학원 시간표.app"

if [[ $(uname -s) != Darwin ]]; then
    echo "macOS에서 실행하세요." >&2
    exit 1
fi
if ! "$python" -c 'import PyInstaller' 2>/dev/null; then
    echo "먼저 개발 환경과 PyInstaller를 설치하세요. README의 macOS 앱 빌드 항목을 참고하세요." >&2
    exit 1
fi

mkdir -p "$dist"
stage=$(mktemp -d "$dist/.macos-build.XXXXXX")
cleanup() {
    if [[ -d "$stage/previous.app" && ! -e "$app" ]]; then
        mv "$stage/previous.app" "$app" || return
    fi
    rm -rf "$stage"
}
trap cleanup EXIT

printf '%s\n' 'from academy_timetable.__main__ import main' 'raise SystemExit(main())' > "$stage/launch.py"
cd "$stage"
PYINSTALLER_CONFIG_DIR="$stage/cache" "$python" -m PyInstaller \
    --windowed --onedir --name AcademyTimetable --paths "$root/src" \
    --copy-metadata academy-timetable \
    --osx-bundle-identifier com.ljwoo8942.academy-timetable launch.py

staged_app="$stage/dist/AcademyTimetable.app"
codesign --verify --deep --strict "$staged_app"
if [[ -e "$app" ]]; then
    mv "$app" "$stage/previous.app"
fi
mv "$staged_app" "$app"
printf '실행 파일 %s\n' "$app"
