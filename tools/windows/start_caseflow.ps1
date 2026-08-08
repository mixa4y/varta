[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$OpenMap
)

$ErrorActionPreference = "Stop"
$caseRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$configPath = Join-Path $caseRoot ".caseflow\config.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "VARTA ще не встановлено. Запустіть install_caseflow.ps1."
}
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Port -le 0) { $Port = [int]$config.port }
$executablePath = Join-Path $caseRoot "VARTA.exe"
$useExecutable = Test-Path -LiteralPath $executablePath -PathType Leaf
$pythonPath = [string]$config.python_path
$serverScript = Join-Path $caseRoot ".caseflow\app\server.py"
if (-not $useExecutable) {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Не знайдено VARTA.exe або Python за збереженим шляхом: $pythonPath"
    }
    if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
        throw "Не знайдено сервер VARTA: $serverScript"
    }
}

$url = if ($OpenMap) { "http://127.0.0.1:$Port/legal-case-map.html" } else { "http://127.0.0.1:$Port/" }
$statusUrl = "http://127.0.0.1:$Port/api/status"
$alreadyRunning = $false
$status = $null
try {
    $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 1
    $reportedRoot = [System.IO.Path]::GetFullPath([string]$status.root)
    if (-not $status.server -or [string]$status.server.product -ne "VARTA" -or -not [string]::Equals($reportedRoot, $caseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Порт $Port уже зайнятий іншим застосунком або іншою справою: $reportedRoot"
    }
    $alreadyRunning = $true
} catch {
    if ($_.Exception.Message -like "Порт * уже зайнятий*") { throw }
}
if (-not $alreadyRunning) {
    $startupLog = Join-Path $caseRoot ".caseflow\logs\startup.log"
    $errorLog = Join-Path $caseRoot ".caseflow\logs\startup-error.log"
    $arguments = if ($useExecutable) {
        @("--root", "`"$caseRoot`"", "--host", "127.0.0.1", "--port", [string]$Port, "--no-open")
    } else {
        @("`"$serverScript`"", "--root", "`"$caseRoot`"", "--host", "127.0.0.1", "--port", [string]$Port)
    }
    # Some managed shells inject both Path and PATH. Windows PowerShell's
    # Start-Process rejects that duplicate environment key, so normalize it.
    $processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $processPath, "Process")
    $runtimePath = if ($useExecutable) { $executablePath } else { $pythonPath }
    $process = Start-Process -FilePath $runtimePath -ArgumentList $arguments -WorkingDirectory $caseRoot -WindowStyle Hidden -RedirectStandardOutput $startupLog -RedirectStandardError $errorLog -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 200
        try {
            $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 1
            $reportedRoot = [System.IO.Path]::GetFullPath([string]$status.root)
            if (-not $status.server -or [string]$status.server.product -ne "VARTA" -or -not [string]::Equals($reportedRoot, $caseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Порт $Port відповідає іншою справою: $reportedRoot"
            }
            $ready = $true
            break
        } catch {}
        if (-not $useExecutable -and $process.HasExited) { break }
    }
    if (-not $ready) {
        $tail = if (Test-Path -LiteralPath $errorLog) { (Get-Content -LiteralPath $errorLog -Tail 12 -ErrorAction SilentlyContinue) -join "`n" } else { "" }
        throw "Сервер VARTA не запустився на порту $Port. Перевірте .caseflow\logs\startup-error.log.`n$tail"
    }
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $serverPid = if ($listener) { [int]$listener.OwningProcess } else { [int]$process.Id }
    Set-Content -LiteralPath (Join-Path $caseRoot ".caseflow\server.pid") -Value $serverPid -Encoding ASCII
}
Write-Host "VARTA: $url" -ForegroundColor Cyan
if (-not $NoBrowser) {
    Start-Process $url
}
