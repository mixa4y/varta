[CmdletBinding()]
param(
    [string]$TargetPath = $PSScriptRoot,
    [string]$PackagePath = "",
    [string]$Repository = "mixa4y/varta",
    [switch]$CheckOnly,
    [switch]$Start,
    [switch]$AllowDowngrade
)

$ErrorActionPreference = "Stop"
$targetRoot = (Resolve-Path -LiteralPath $TargetPath).Path
$installStatePath = Join-Path $targetRoot ".caseflow\install.json"
$currentVersion = "0.0.0"
if (Test-Path -LiteralPath $installStatePath -PathType Leaf) {
    try {
        $installState = Get-Content -LiteralPath $installStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($installState.version) { $currentVersion = [string]$installState.version }
    } catch {}
}

$temporaryRoot = $null
$packageRoot = $null
try {
    if ([string]::IsNullOrWhiteSpace($PackagePath)) {
        $headers = @{ "User-Agent" = "VARTA-Updater"; "Accept" = "application/vnd.github+json" }
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/latest" -Headers $headers -TimeoutSec 30
        $asset = @($release.assets) | Where-Object { $_.name -match '^VARTA-Setup-v.+\.zip$' } | Select-Object -First 1
        if (-not $asset) { throw "Останній реліз не містить VARTA-Setup-v*.zip." }
        $availableVersion = ([string]$release.tag_name).TrimStart('v')
        $isNewer = ([version]$availableVersion -gt [version]$currentVersion)
        if ($CheckOnly) {
            [ordered]@{
                product = "VARTA"
                current_version = $currentVersion
                available_version = $availableVersion
                update_available = $isNewer
                release = [string]$release.html_url
                package = [string]$asset.browser_download_url
            } | ConvertTo-Json -Depth 4
            return
        }
        if (-not $isNewer -and -not $AllowDowngrade) {
            Write-Host "Встановлено актуальну версію VARTA $currentVersion." -ForegroundColor Green
            return
        }
        $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("caseflow-update-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
        $PackagePath = Join-Path $temporaryRoot $asset.name
        Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -Headers $headers -OutFile $PackagePath -TimeoutSec 300
    }

    $resolvedPackage = (Resolve-Path -LiteralPath $PackagePath).Path
    if (Test-Path -LiteralPath $resolvedPackage -PathType Container) {
        $packageRoot = $resolvedPackage
    } elseif ([System.IO.Path]::GetExtension($resolvedPackage) -ieq ".zip") {
        if (-not $temporaryRoot) {
            $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("caseflow-update-" + [guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
        }
        $packageRoot = Join-Path $temporaryRoot "package"
        New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($resolvedPackage)
        try {
            $packagePrefix = [System.IO.Path]::GetFullPath($packageRoot) + [System.IO.Path]::DirectorySeparatorChar
            foreach ($entry in $archive.Entries) {
                $entryPath = $entry.FullName.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
                $destination = [System.IO.Path]::GetFullPath((Join-Path $packageRoot $entryPath))
                if (-not $destination.StartsWith($packagePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Небезпечний шлях у ZIP-пакеті: $($entry.FullName)"
                }
                if ([string]::IsNullOrEmpty($entry.Name)) {
                    New-Item -ItemType Directory -Path $destination -Force | Out-Null
                } else {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
                    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $true)
                }
            }
        } finally {
            $archive.Dispose()
        }
    } else {
        throw "Підтримується папка пакета або ZIP-файл."
    }

    $installer = Join-Path $packageRoot "install_caseflow.ps1"
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        $installer = Get-ChildItem -LiteralPath $packageRoot -Filter "install_caseflow.ps1" -File -Recurse | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $installer) { throw "У пакеті немає install_caseflow.ps1." }
    $arguments = @{ TargetPath = $targetRoot }
    if ($Start) { $arguments["Start"] = $true }
    if ($AllowDowngrade) { $arguments["AllowDowngrade"] = $true }
    & $installer @arguments
} finally {
    if ($temporaryRoot -and (Test-Path -LiteralPath $temporaryRoot)) {
        $tempPrefix = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $resolvedTemp = [System.IO.Path]::GetFullPath($temporaryRoot)
        if ($resolvedTemp.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedTemp) -like "caseflow-update-*") {
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
        }
    }
}
