$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
$dist = Join-Path $project 'dist'
$stage = Join-Path $dist ('.windows-build-' + [Guid]::NewGuid().ToString('N'))
$compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (!(Test-Path -LiteralPath $compiler)) {
    throw 'Install Inno Setup 6.5 or later before building the Windows installer.'
}

New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    $entry = Join-Path $stage 'launch.py'
    @('from academy_timetable.__main__ import main', 'raise SystemExit(main())') |
        Set-Content -LiteralPath $entry -Encoding Ascii

    $options = @(
        '--windowed', '--onefile', '--name', 'AcademyTimetable',
        '--paths', (Join-Path $project 'src'),
        '--specpath', $stage, '--workpath', (Join-Path $stage 'work'),
        '--distpath', $stage, $entry
    )
    & $python -m PyInstaller @options
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

    $executable = Join-Path $dist 'AcademyTimetable.exe'
    Move-Item -LiteralPath (Join-Path $stage 'AcademyTimetable.exe') -Destination $executable -Force
    Write-Output $executable

    $version = & $python -c 'from importlib.metadata import version; print(version("academy-timetable"))'
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the app version.' }
    & $compiler "/DAppVersion=$version" "/O$stage" (Join-Path $PSScriptRoot 'windows-installer.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed.' }
    $installer = Join-Path $dist 'AcademyTimetable-Setup.exe'
    Move-Item -LiteralPath (Join-Path $stage 'AcademyTimetable-Setup.exe') -Destination $installer -Force
    Write-Output $installer
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
