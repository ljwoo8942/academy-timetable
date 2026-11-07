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
    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcut in $shortcuts) {
        if (!(Test-Path -LiteralPath $shortcut)) {
            Get-ChildItem ([Environment]::GetFolderPath('Desktop')), ([Environment]::GetFolderPath('Programs')) -Filter '*.lnk' -Recurse |
                Select-Object -ExpandProperty FullName | Write-Output
            throw "Missing shortcut: $shortcut"
        }
        $target = $shell.CreateShortcut($shortcut).TargetPath
        if ($target -ne $executable) {
            throw "Shortcut target is $target; expected $executable"
        }
    }
    $previousPath = $env:Path
    $previousPythonHome = $env:PYTHONHOME
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:Path = "$env:SystemRoot\System32"
        $env:PYTHONHOME = ''
        $env:PYTHONPATH = ''
        $app = Start-Process -FilePath $executable -WorkingDirectory $working -PassThru
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
    & $python -c 'import sqlite3, sys; from academy_timetable.db import SCHEMA_VERSION; db = sqlite3.connect(sys.argv[1]); assert db.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,); db.execute("INSERT INTO terms(name) VALUES (?)", ("Installer preservation check",)); db.commit(); db.close()' $db
    if ($LASTEXITCODE -ne 0) { throw 'Installed app database check failed.' }
    taskkill /PID $app.Id /T /F | Out-Null
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
    Write-Output 'Installed startup with network blocked and system Python absent from PATH, shortcuts, reinstallation and data-preserving uninstall: OK'
} finally {
    if ($app -and !$app.HasExited) { taskkill /PID $app.Id /T /F | Out-Null }
    Get-NetFirewallRule -DisplayName $rulePrefix -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Remove-Item -LiteralPath $working -Recurse -Force
}
