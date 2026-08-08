[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$OutputDirectory = "",
    [switch]$SkipExecutable,
    [switch]$SkipMap
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$versionPath = Join-Path $sourceRoot "caseflow\version.json"
if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) { throw "Не знайдено caseflow/version.json." }
$versionManifest = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json
$caseflowVersion = [string]$versionManifest.version
try { [void][version]$caseflowVersion } catch { throw "Некоректна версія VARTA: $caseflowVersion" }

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $sourceRoot "dist" }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $resolved = & py.exe -3 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $resolved) { throw "Не знайдено Python 3. Передайте -PythonPath." }
    $PythonPath = $resolved.Trim()
}

if (-not $SkipMap) {
    $mapTemplate = Join-Path $sourceRoot "caseflow\static\legal-case-map.html"
    if (-not (Test-Path -LiteralPath $mapTemplate -PathType Leaf)) {
        throw "Не знайдено універсальну в’юху доказової мапи: $mapTemplate"
    }
}

if (-not $SkipExecutable) {
    & (Join-Path $PSScriptRoot "build_caseflow_exe.ps1") -PythonPath $PythonPath -OutputDirectory $outputRoot
}
$exePath = Join-Path $outputRoot "VARTA.exe"
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw "Немає зібраного EXE: $exePath" }

$stagingRoot = Join-Path $sourceRoot "tmp\release_package"
$expectedStaging = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot "tmp\release_package"))
if (Test-Path -LiteralPath $stagingRoot) {
    $resolvedStaging = (Resolve-Path -LiteralPath $stagingRoot).Path
    if (-not [string]::Equals($expectedStaging, $resolvedStaging, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Некоректна staging-папка: $resolvedStaging"
    }
    Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $stagingRoot "dist") -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $sourceRoot "caseflow") -Destination (Join-Path $stagingRoot "caseflow") -Recurse -Force
Copy-Item -LiteralPath $exePath -Destination (Join-Path $stagingRoot "dist\VARTA.exe") -Force

$deployFiles = @(
    "README.md",
    "install_caseflow.ps1", "install_caseflow_wizard.ps1", "update_caseflow.ps1", "rollback_caseflow.ps1",
    "start_caseflow.ps1", "stop_caseflow.ps1", "uninstall_caseflow.ps1"
)
foreach ($relative in $deployFiles) {
    $source = Join-Path $sourceRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        $source = Join-Path $PSScriptRoot $relative
    }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Для пакета бракує: $relative" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $stagingRoot $relative) -Force
}
$mapSource = Join-Path $sourceRoot "caseflow\static\legal-case-map.html"
if (Test-Path -LiteralPath $mapSource -PathType Leaf) {
    Copy-Item -LiteralPath $mapSource -Destination (Join-Path $stagingRoot "legal-case-mind-map.html") -Force
}

$packageFiles = Get-ChildItem -LiteralPath $stagingRoot -Recurse -File | Sort-Object FullName
$manifestFiles = foreach ($file in $packageFiles) {
    $relative = $file.FullName.Substring($stagingRoot.Length + 1).Replace([System.IO.Path]::DirectorySeparatorChar, '/')
    [ordered]@{
        path = $relative
        bytes = [int64]$file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
}
$releaseManifest = [ordered]@{
    schema_version = 1
    product = "VARTA"
    version = $caseflowVersion
    channel = [string]$versionManifest.channel
    data_schema = $versionManifest.data_schema
    created_at = (Get-Date).ToString("o")
    update_policy = "full-package-preserve-case-data"
    preserved_paths = @($versionManifest.preserved_paths)
    files = @($manifestFiles)
}
$releaseManifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $stagingRoot "release-manifest.json") -Encoding UTF8

$archivePath = Join-Path $outputRoot "VARTA-Setup-v$caseflowVersion.zip"
if (Test-Path -LiteralPath $archivePath -PathType Leaf) { Remove-Item -LiteralPath $archivePath -Force }
Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $archivePath -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
$archiveBytes = (Get-Item -LiteralPath $archivePath).Length

Remove-Item -LiteralPath $stagingRoot -Recurse -Force
Write-Host "Інсталяційний пакет VARTA $caseflowVersion створено: $archivePath" -ForegroundColor Green
Write-Host "Розмір: $archiveBytes байт; SHA-256: $archiveHash"
