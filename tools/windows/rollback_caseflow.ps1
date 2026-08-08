[CmdletBinding()]
param(
    [string]$TargetPath = $PSScriptRoot,
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$targetRoot = (Resolve-Path -LiteralPath $TargetPath).Path
$rollbackRoot = Join-Path $targetRoot ".caseflow\rollback"
$metadataPath = Join-Path $rollbackRoot "rollback.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "Немає підготовленої копії для відкату."
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json

$stopScript = Join-Path $targetRoot "stop_caseflow.ps1"
if (Test-Path -LiteralPath $stopScript -PathType Leaf) {
    & $stopScript
}

$managedPaths = @(
    "VARTA.exe", ".caseflow\app", ".caseflow\install.json",
    "scripts\caseflow_process.py", "scripts\anomaly_detector.py",
    "start_caseflow.ps1", "stop_caseflow.ps1", "install_caseflow.ps1",
    "install_caseflow_wizard.ps1", "update_caseflow.ps1", "rollback_caseflow.ps1",
    "uninstall_caseflow.ps1", "VARTA_README.md", "legal-case-mind-map.html",
    "Встановити_VARTA.cmd", "Відкрити_VARTA.cmd", "Відкрити_Доказову_Мапу.cmd", "Оновити_VARTA.cmd"
)
$targetPrefix = $targetRoot + [System.IO.Path]::DirectorySeparatorChar
$rollbackPrefix = $rollbackRoot + [System.IO.Path]::DirectorySeparatorChar

foreach ($relative in $managedPaths) {
    $destination = [System.IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $destination.StartsWith($targetPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Небезпечний шлях відкату: $relative"
    }
    if (Test-Path -LiteralPath $destination) {
        $item = Get-Item -LiteralPath $destination -Force
        if ($item.PSIsContainer) { Remove-Item -LiteralPath $destination -Recurse -Force }
        else { Remove-Item -LiteralPath $destination -Force }
    }
}

foreach ($relative in @($metadata.files)) {
    if ($relative -notin $managedPaths) { throw "Невідомий шлях у копії відкату: $relative" }
    $source = [System.IO.Path]::GetFullPath((Join-Path $rollbackRoot $relative))
    $destination = [System.IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $source.StartsWith($rollbackPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Небезпечне джерело відкату: $relative"
    }
    if (-not (Test-Path -LiteralPath $source)) { throw "У копії відкату бракує: $relative" }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
}

$historyPath = Join-Path $targetRoot ".caseflow\update-history.json"
$history = @()
if (Test-Path -LiteralPath $historyPath -PathType Leaf) {
    try { $history = @(Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { $history = @() }
}
$history += [ordered]@{
    timestamp = (Get-Date).ToString("o")
    mode = "rollback"
    from_version = [string]$metadata.to_version
    to_version = [string]$metadata.from_version
}
$history | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $historyPath -Encoding UTF8

Write-Host "VARTA відкочено з $($metadata.to_version) до $($metadata.from_version). Матеріали справи не змінювалися." -ForegroundColor Green
if ($Start) {
    & (Join-Path $targetRoot "start_caseflow.ps1")
}
