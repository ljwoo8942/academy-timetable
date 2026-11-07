#!/bin/bash
set -euo pipefail
app_pid=$1
target=$2
incoming=$3
previous=$4
install_stage=$5
download_stage=$6

failed() {
    if [[ -d "$previous" ]]; then
        if [[ -d "$target" ]]; then /bin/mv "$target" "$install_stage/failed.app"; fi
        /bin/mv "$previous" "$target"
    fi
    echo 'Update failed. Previous app and timetable backup were preserved.'
    /usr/bin/osascript -e 'display alert "학원 시간표 업데이트 실패" message "시간표 백업은 보존되었습니다. 다른 앱 창을 닫은 뒤 다시 시도하세요."' || true
}
trap failed ERR

for ((attempt=0; attempt<900; attempt++)); do
    if ! kill -0 "$app_pid" 2>/dev/null; then break; fi
    /bin/sleep 0.2
done
if kill -0 "$app_pid" 2>/dev/null; then
    echo 'App did not exit. No update was applied.'
    exit 1
fi
/bin/mv "$target" "$previous"
/bin/mv "$incoming" "$target"
/usr/bin/open -n "$target"
trap - ERR
/bin/rm -rf "$install_stage" "$download_stage" || true
echo 'Update installed and app restarted.'
