$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
$setup = Join-Path $project 'dist\AcademyTimetable-Setup.exe'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\AcademyTimetable'
$executable = Join-Path $installDir 'AcademyTimetable.exe'
$db = & $python -c 'from PySide6.QtCore import QCoreApplication, QStandardPaths; app = QCoreApplication([]); app.setOrganizationName("AcademyTimetable"); app.setApplicationName("AcademyTimetable"); print(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) + "/academy-timetable.sqlite3")'
if ($LASTEXITCODE -ne 0 -or !$db -or (Test-Path -LiteralPath $db) -or (Test-Path -LiteralPath $installDir)) {
    throw 'This check requires an unused CI user profile.'
}
$rulePrefix = 'AcademyTimetable-CI-' + [Guid]::NewGuid().ToString('N')
$working = Join-Path $env:RUNNER_TEMP $rulePrefix
$app = $null
New-Item -ItemType Directory -Path $working | Out-Null
try {
    foreach ($file in @($setup, $executable)) {
        New-NetFirewallRule -Name ($rulePrefix + [IO.Path]::GetFileName($file)) -DisplayName $rulePrefix `
            -Direction Outbound -Action Block -Program $file -Profile Any | Out-Null
    }
    $install = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -Wait -PassThru
    if ($install.ExitCode -ne 0 -or !(Test-Path -LiteralPath $executable)) { throw 'Installer did not install the app.' }
    $shortcuts = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) '학원 시간표.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) '학원 시간표\학원 시간표.lnk')
    )
    foreach ($shortcut in $shortcuts) {
        if (!(Test-Path -LiteralPath $shortcut)) {
            throw "Missing shortcut: $shortcut"
        }
    }
    $previousPath = $env:Path
    $previousPythonHome = $env:PYTHONHOME
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:Path = "$env:SystemRoot\System32"
        $env:PYTHONHOME = ''
        $env:PYTHONPATH = ''
        $app = Start-Process -FilePath $shortcuts[0] -WorkingDirectory $working -PassThru
        if (!$app -or $app.Path -ne $executable) { throw 'Desktop shortcut did not start the installed executable.' }
    } finally {
        $env:Path = $previousPath
        $env:PYTHONHOME = $previousPythonHome
        $env:PYTHONPATH = $previousPythonPath
    }
    for ($attempt = 0; $attempt -lt 60 -and !(Test-Path -LiteralPath $db); $attempt++) {
        if ($app.HasExited) { throw "App exited with code $($app.ExitCode)." }
        Start-Sleep -Seconds 1
    }
    if (!(Test-Path -LiteralPath $db)) { throw 'App did not initialize its database.' }
    Start-Sleep -Seconds 2
    if ($app.HasExited) { throw "App exited with code $($app.ExitCode)." }
    $version = & $python -c 'from importlib.metadata import version; print(version("academy-timetable"))'
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the expected app version.' }
    $window = $null
    for ($attempt = 0; $attempt -lt 30 -and !$window; $attempt++) {
        $window = Get-Process -Name AcademyTimetable -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $executable -and $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq "학원 시간표 관리 v$version" }
        if (!$window) { Start-Sleep -Seconds 1 }
    }
    if (!$window) { throw 'Installed app did not create its native Windows window with the expected version.' }
    $log = Join-Path (Split-Path -Parent $db) 'academy-timetable.log'
    if (!(Test-Path -LiteralPath $log) -or !(Select-String -LiteralPath $log -SimpleMatch "version=$version" -Quiet)) {
        throw 'Installed app did not record its startup version in the log.'
    }
    & $python -c 'import sqlite3, sys; from academy_timetable.db import SCHEMA_VERSION; db = sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,); db.execute("INSERT INTO terms(name) VALUES (?)", ("Installer preservation check",)); db.commit(); db.close()' $db
    if ($LASTEXITCODE -ne 0) { throw 'Installed app database check failed.' }
    $databaseHash = (Get-FileHash -LiteralPath $db).Hash
    $updateStage = Join-Path $working 'update'
    New-Item -ItemType Directory -Path $updateStage | Out-Null
    $settings = @{ mode = 'windows-installer'; payload = $setup; target = $executable;
        pid = $window.Id; parent_pid = $app.Id; executable = $executable; stage = $updateStage }
    $settingsPath = Join-Path $working 'update-test.json'
    $settings | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
    & $python -c 'import json,sys; from academy_timetable.updater import launch_update; launch_update(json.load(open(sys.argv[1], encoding="utf-8-sig")))' $settingsPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the update helper.' }
    $window.CloseMainWindow() | Out-Null
    $updateLog = $updateStage + '.log'
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if ((Test-Path -LiteralPath $updateLog) -and (Select-String -LiteralPath $updateLog -SimpleMatch 'Update installed and app restarted.' -Quiet)) { break }
        Start-Sleep -Seconds 1
    }
    if (!(Test-Path -LiteralPath $updateLog) -or !(Select-String -LiteralPath $updateLog -SimpleMatch 'Update installed and app restarted.' -Quiet)) {
        if (Test-Path -LiteralPath $updateLog) { Get-Content -LiteralPath $updateLog }
        throw 'The update helper did not finish.'
    }
    $app = $null
    for ($attempt = 0; $attempt -lt 30 -and !$app; $attempt++) {
        $app = Get-Process -Name AcademyTimetable -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $executable -and $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq "학원 시간표 관리 v$version" }
        if (!$app) { Start-Sleep -Seconds 1 }
    }
    if (!$app) { throw 'The update did not reopen the native app window.' }
    if ((Get-FileHash -LiteralPath $db).Hash -ne $databaseHash) { throw 'The update changed timetable data.' }
    taskkill /PID $app.Id /T /F | Out-Null
    Get-Process -Name AcademyTimetable -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $executable } | Wait-Process -Timeout 30
    $app = $null
    $databaseHash = (Get-FileHash -LiteralPath $db).Hash
    $install = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -Wait -PassThru
    if ($install.ExitCode -ne 0 -or !(Test-Path -LiteralPath $executable)) { throw 'Reinstallation failed.' }
    if ((Get-FileHash -LiteralPath $db).Hash -ne $databaseHash) { throw 'Reinstallation changed user data.' }
    $uninstall = Start-Process -FilePath (Join-Path $installDir 'unins000.exe') `
        -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -Wait -PassThru
    if ($uninstall.ExitCode -ne 0 -or (Test-Path -LiteralPath $executable)) { throw 'Uninstallation failed.' }
    foreach ($shortcut in $shortcuts) {
        if (Test-Path -LiteralPath $shortcut) { throw 'Uninstallation left an app shortcut.' }
    }
    if ((Get-FileHash -LiteralPath $db).Hash -ne $databaseHash) { throw 'Uninstallation changed user data.' }
    Write-Output 'Native Windows window and version, offline startup without system Python on PATH, update helper and restart, shortcuts, reinstallation and data-preserving uninstall: OK'
} finally {
    if ($app -and !$app.HasExited) { taskkill /PID $app.Id /T /F | Out-Null }
    Get-NetFirewallRule -DisplayName $rulePrefix -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Remove-Item -LiteralPath $working -Recurse -Force
}
