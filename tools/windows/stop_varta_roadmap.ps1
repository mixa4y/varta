[CmdletBinding()]
param(
    [int]$Port = 8766
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$runtimeDir = Join-Path $repoRoot ".varta\roadmap-controller"
$tokenPath = Join-Path $runtimeDir "session.token"
$healthUrl = "http://127.0.0.1:$Port/api/v1/health"
$stopUrl = "http://127.0.0.1:$Port/api/v1/controller/stop"
$origin = "http://127.0.0.1:$Port"

try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
} catch {
    Write-Host "Roadmap controller на порту $Port не відповідає." -ForegroundColor Yellow
    exit 0
}
$reportedRoot = [System.IO.Path]::GetFullPath([string]$health.root)
if ([string]$health.product -ne "VARTA Roadmap Controller" -or
    -not [string]::Equals($reportedRoot, $repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Відмова зупинки: порт $Port належить іншому застосунку або іншому root."
}
if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
    throw "Не знайдено локальний session token: $tokenPath"
}
$token = (Get-Content -LiteralPath $tokenPath -Raw -Encoding ASCII).Trim()
if (-not $token) { throw "Локальний session token порожній." }
$headers = @{
    "Origin" = $origin
    "X-Varta-Roadmap-Token" = $token
}
Invoke-RestMethod -Method Post -Uri $stopUrl -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 5 | Out-Null

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 200
    try {
        Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1 | Out-Null
    } catch {
        Write-Host "VARTA roadmap controller зупинено." -ForegroundColor Green
        exit 0
    }
}
throw "Controller прийняв запит, але не зупинився протягом 6 секунд."
