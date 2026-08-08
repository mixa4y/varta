[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
$caseRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$pidPath = Join-Path $caseRoot ".caseflow\server.pid"
if (-not (Test-Path -LiteralPath $pidPath)) {
    $configProbe = Join-Path $caseRoot ".caseflow\config.json"
    $discoveredPid = $null
    if (Test-Path -LiteralPath $configProbe -PathType Leaf) {
        try {
            $probeConfig = Get-Content -LiteralPath $configProbe -Raw -Encoding UTF8 | ConvertFrom-Json
            $probePort = [int]$probeConfig.port
            $probeStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$probePort/api/status" -TimeoutSec 1
            $probeRoot = [System.IO.Path]::GetFullPath([string]$probeStatus.root)
            if ([string]::Equals($probeRoot, $caseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                $listener = Get-NetTCPConnection -LocalPort $probePort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($listener) { $discoveredPid = [int]$listener.OwningProcess }
            }
        } catch {}
    }
    if (-not $discoveredPid) {
        Write-Host "VARTA у цій справі вже зупинено."
        exit 0
    }
    Set-Content -LiteralPath $pidPath -Value $discoveredPid -Encoding ASCII
}
$serverPid = [int](Get-Content -LiteralPath $pidPath -Raw)
$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidPath -Force
    Write-Host "VARTA уже зупинено."
    exit 0
}
$config = Get-Content -LiteralPath (Join-Path $caseRoot ".caseflow\config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$status = $null
try { $status = Invoke-RestMethod -Uri "http://127.0.0.1:$([int]$config.port)/api/status" -TimeoutSec 1 } catch {}
if ($status) {
    $reportedRoot = [System.IO.Path]::GetFullPath([string]$status.root)
    if (-not [string]::Equals($reportedRoot, $caseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Порт відповідає іншою справою ($reportedRoot); зупинку скасовано."
    }
    if ($status.activeJob -and -not $Force) {
        throw "Зараз виконується $($status.activeJob.kind). Дочекайтеся завершення або свідомо використайте -Force."
    }
}
$commandLine = $null
try { $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid" -ErrorAction Stop).CommandLine } catch {}
$verified = (
    $commandLine -and
    ($commandLine -like "*server.py*" -or $commandLine -like "*VARTA.exe*") -and
    $commandLine -like "*$caseRoot*"
) -or ($status -and ($process.ProcessName -like "python*" -or $process.ProcessName -eq "VARTA"))
if (-not $verified -and -not $Force) {
    throw "PID $serverPid не вдалося надійно підтвердити як VARTA; зупинку скасовано. Використайте -Force лише після ручної перевірки."
}
Stop-Process -Id $serverPid
Remove-Item -LiteralPath $pidPath -Force
Write-Host "VARTA зупинено." -ForegroundColor Green
