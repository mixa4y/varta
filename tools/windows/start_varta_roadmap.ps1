[CmdletBinding()]
param(
    [int]$Port = 8766,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$serverScript = Join-Path $repoRoot "tools\roadmap_controller\server.py"
$runtimeDir = Join-Path $repoRoot ".varta\roadmap-controller"
$startupLog = Join-Path $runtimeDir "server-stdout.log"
$errorLog = Join-Path $runtimeDir "server-stderr.log"
$url = "http://127.0.0.1:$Port/"
$healthUrl = "http://127.0.0.1:$Port/api/v1/health"

if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
    throw "Не знайдено roadmap controller: $serverScript"
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port має бути в межах 1..65535."
}

$alreadyRunning = $false
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
    $reportedRoot = [System.IO.Path]::GetFullPath([string]$health.root)
    if ([string]$health.product -ne "VARTA Roadmap Controller" -or
        -not [string]::Equals($reportedRoot, $repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Порт $Port зайнятий іншим застосунком."
    }
    $alreadyRunning = $true
} catch {
    if ($_.Exception.Message -like "Порт * зайнятий*") { throw }
}

if (-not $alreadyRunning) {
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $runtimePath = $venvPython
        $arguments = @(
            "`"$serverScript`"",
            "--root", "`"$repoRoot`"",
            "--port", [string]$Port
        )
    } else {
        $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -eq $pyCommand) {
            throw "Не знайдено Python 3.12 (.venv або py.exe)."
        }
        $runtimePath = $pyCommand.Source
        $arguments = @(
            "-3.12",
            "`"$serverScript`"",
            "--root", "`"$repoRoot`"",
            "--port", [string]$Port
        )
    }

    # Windows PowerShell rejects duplicate Path/PATH keys in Start-Process.
    $processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $processPath, "Process")
    $process = Start-Process `
        -FilePath $runtimePath `
        -ArgumentList $arguments `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $startupLog `
        -RedirectStandardError $errorLog `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 240; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
            $reportedRoot = [System.IO.Path]::GetFullPath([string]$health.root)
            if ([string]$health.product -ne "VARTA Roadmap Controller" -or
                -not [string]::Equals($reportedRoot, $repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Порт $Port відповідає іншим застосунком."
            }
            $ready = $true
            break
        } catch {}
    }
    if (-not $ready) {
        $tail = if (Test-Path -LiteralPath $errorLog) {
            (Get-Content -LiteralPath $errorLog -Tail 16 -ErrorAction SilentlyContinue) -join "`n"
        } else { "" }
        throw "Roadmap controller не запустився на порту $Port.`n$tail"
    }
}

Write-Host "VARTA roadmap: $url" -ForegroundColor Cyan
if ($health.codexReady) {
    Write-Host "Codex App Server: ready" -ForegroundColor Green
} else {
    Write-Warning "Controller працює, але Codex App Server не готовий: $($health.codexError)"
}
if (-not $NoBrowser) {
    Start-Process $url
}
