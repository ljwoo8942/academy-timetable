$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
$dist = Join-Path $project 'dist'
$stage = Join-Path $dist ('.windows-build-' + [Guid]::NewGuid().ToString('N'))

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
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
