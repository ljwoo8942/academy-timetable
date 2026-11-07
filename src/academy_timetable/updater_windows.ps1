param([string]$Config)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$backup = $null
$replacement = $null
try {
    $waiting = @(Get-Process -Id $settings.pid -ErrorAction SilentlyContinue)
    $parent = Get-Process -Id $settings.parent_pid -ErrorAction SilentlyContinue
    if ($parent -and $parent.Path -eq $settings.executable) { $waiting += $parent }
    foreach ($process in $waiting) {
        if (!$process.WaitForExit(180000)) { throw 'The app did not exit. No update was applied.' }
    }
    if ($settings.mode -eq 'windows-installer') {
        $install = Start-Process -FilePath $settings.payload -ArgumentList `
            '/SILENT /SP- /NORESTART /NOCLOSEAPPLICATIONS /NORESTARTAPPLICATIONS' -Wait -PassThru
        if ($install.ExitCode -ne 0) { throw "Installation stopped: $($install.ExitCode)" }
    } elseif ($settings.mode -eq 'windows-portable') {
        $backup = $settings.target + '.' + [Guid]::NewGuid().ToString('N') + '.previous'
        $replacement = $settings.target + '.' + [Guid]::NewGuid().ToString('N') + '.new'
        Copy-Item -LiteralPath $settings.payload -Destination $replacement
        [IO.File]::Replace($replacement, $settings.target, $backup)
    } else {
        throw 'Unsupported update mode.'
    }
    Start-Process -FilePath $settings.target -WorkingDirectory (Split-Path -Parent $settings.target) | Out-Null
    if ($backup) { Remove-Item -LiteralPath $backup -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $settings.stage -Recurse -Force -ErrorAction SilentlyContinue
    Write-Output 'Update installed and app restarted.'
} catch {
    $detail = $_.Exception.Message
    if ($backup -and (Test-Path -LiteralPath $backup)) {
        [IO.File]::Replace($backup, $settings.target, $null)
    }
    if ($replacement -and (Test-Path -LiteralPath $replacement)) {
        Remove-Item -LiteralPath $replacement -ErrorAction SilentlyContinue
    }
    Write-Output "Update failed: $detail"
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("업데이트를 완료하지 못했습니다. 시간표 백업은 보존되었습니다. 다른 앱 창을 닫은 뒤 다시 시도하세요.`n$detail", '학원 시간표') | Out-Null
    exit 1
}
