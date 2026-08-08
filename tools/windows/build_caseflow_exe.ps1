[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$versionManifestPath = Join-Path $sourceRoot "caseflow\version.json"
if (-not (Test-Path -LiteralPath $versionManifestPath -PathType Leaf)) {
    throw "Не знайдено caseflow/version.json."
}
$versionManifest = Get-Content -LiteralPath $versionManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$caseflowVersion = [string]$versionManifest.version
try { [void][version]$caseflowVersion } catch { throw "Некоректна версія VARTA: $caseflowVersion" }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $sourceRoot "dist"
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $resolved = & py.exe -3 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $resolved) {
        throw "Не знайдено Python 3. Передайте -PythonPath."
    }
    $PythonPath = $resolved.Trim()
}

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python не знайдено: $PythonPath"
}

& $PythonPath -c "import openpyxl, pypdf, PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Для збірки потрібні openpyxl, pypdf і PyInstaller."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$workRoot = Join-Path $sourceRoot "tmp\pyinstaller"
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--noupx",
    "--name", "VARTA",
    "--distpath", $outputRoot,
    "--workpath", $workRoot,
    "--specpath", $workRoot,
    "--paths", (Join-Path $sourceRoot "caseflow"),
    "--add-data", "$(Join-Path $sourceRoot 'caseflow\static');static",
    "--add-data", "$(Join-Path $sourceRoot 'caseflow\version.json');.",
    (Join-Path $sourceRoot "caseflow\server.py")
)

& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller завершився з кодом $LASTEXITCODE."
}

$exePath = Join-Path $outputRoot "VARTA.exe"
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "EXE не створено: $exePath"
}

$hash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
Write-Host "VARTA $caseflowVersion EXE створено: $exePath" -ForegroundColor Green
Write-Host "SHA-256: $hash"
