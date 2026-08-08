[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param()

$ErrorActionPreference = "Stop"
$caseRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$installPath = Join-Path $caseRoot ".caseflow\install.json"
if (-not (Test-Path -LiteralPath $installPath)) {
    throw "Ця папка не містить підтвердженої інсталяції VARTA."
}

if (-not $PSCmdlet.ShouldProcess($caseRoot, "Видалити лише код VARTA, не видаляючи матеріали справи")) {
    return
}

$stopScript = Join-Path $caseRoot "stop_caseflow.ps1"
if (Test-Path -LiteralPath $stopScript) {
    & $stopScript
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $caseRoot ".caseflow\uninstall_backup_$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($relative in @("config.json", "index.json", "drive_index.json", "install.json", "anomaly_status.json")) {
    $source = Join-Path $caseRoot ".caseflow\$relative"
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $backup $relative) -Force
    }
}

$appPath = (Join-Path $caseRoot ".caseflow\app")
$resolvedApp = if (Test-Path -LiteralPath $appPath) { (Resolve-Path -LiteralPath $appPath).Path } else { $null }
$expectedApp = [System.IO.Path]::GetFullPath($appPath)
if ($resolvedApp -and [string]::Equals($resolvedApp, $expectedApp, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedApp -Recurse -Force
}
foreach ($relative in @(
    "VARTA.exe", "scripts\caseflow_process.py", "scripts\anomaly_detector.py", "VARTA_README.md",
    "Відкрити_VARTA.cmd", "Відкрити_Доказову_Мапу.cmd", "Оновити_VARTA.cmd",
    "start_caseflow.ps1", "stop_caseflow.ps1", "update_caseflow.ps1", "rollback_caseflow.ps1"
)) {
    $target = Join-Path $caseRoot $relative
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
}

Write-Host "Код VARTA видалено. Матеріали справи, Реєстр, конфіг, індекси й резервна копія залишилися." -ForegroundColor Green
Write-Host "Резервна копія службових налаштувань: $backup"
