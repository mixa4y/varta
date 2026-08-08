[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$TargetPath = $PSScriptRoot,
    [string]$CaseNumber = "",
    [int]$Port = 8768,
    [string]$SevenZipPath = "",
    [switch]$AllowDowngrade,
    [switch]$NoRollback,
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$repositoryCandidate = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceRoot = if (Test-Path -LiteralPath (Join-Path $repositoryCandidate "caseflow\server.py") -PathType Leaf) {
    $repositoryCandidate
} else {
    (Resolve-Path -LiteralPath $PSScriptRoot).Path
}
$toolRoot = if (Test-Path -LiteralPath (Join-Path $sourceRoot "start_caseflow.ps1") -PathType Leaf) {
    $sourceRoot
} else {
    Join-Path $sourceRoot "tools\windows"
}
if (-not (Test-Path -LiteralPath $TargetPath)) {
    New-Item -ItemType Directory -Path $TargetPath -Force | Out-Null
}
$targetRoot = (Resolve-Path -LiteralPath $TargetPath).Path

$sourceApp = Join-Path $sourceRoot "caseflow"
if (-not (Test-Path -LiteralPath (Join-Path $sourceApp "server.py") -PathType Leaf)) {
    $installedApp = Join-Path $sourceRoot ".caseflow\app"
    if (Test-Path -LiteralPath (Join-Path $installedApp "server.py") -PathType Leaf) {
        $sourceApp = $installedApp
    } else {
        throw "Не знайдено пакет VARTA: $sourceApp"
    }
}
$versionManifestPath = Join-Path $sourceApp "version.json"
if (-not (Test-Path -LiteralPath $versionManifestPath -PathType Leaf)) {
    throw "Пакет не містить caseflow/version.json. Збірку скасовано."
}
$versionManifest = Get-Content -LiteralPath $versionManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$versionManifest.product -ne "VARTA" -or [string]::IsNullOrWhiteSpace([string]$versionManifest.version)) {
    throw "Некоректний маніфест версії VARTA."
}
$caseflowVersion = [string]$versionManifest.version
try { $packageVersion = [version]$caseflowVersion } catch { throw "Некоректна версія пакета: $caseflowVersion" }

$configPath = Join-Path $targetRoot ".caseflow\config.json"
$installPath = Join-Path $targetRoot ".caseflow\install.json"
$existingConfig = $null
$existingInstall = $null
if (Test-Path -LiteralPath $configPath -PathType Leaf) {
    try { $existingConfig = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
}
if (Test-Path -LiteralPath $installPath -PathType Leaf) {
    try { $existingInstall = Get-Content -LiteralPath $installPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
}
$previousVersion = if ($existingInstall -and $existingInstall.version) { [string]$existingInstall.version } else { $null }
$installMode = "install"
if ($previousVersion) {
    try { $installedVersion = [version]$previousVersion } catch { $installedVersion = [version]"0.0.0" }
    if ($installedVersion -gt $packageVersion -and -not $AllowDowngrade) {
        throw "Встановлена новіша версія $previousVersion. Пониження до $caseflowVersion заблоковано; використайте -AllowDowngrade свідомо."
    }
    $installMode = if ($installedVersion -eq $packageVersion) { "repair" } elseif ($installedVersion -lt $packageVersion) { "update" } else { "downgrade" }
}

if ([string]::IsNullOrWhiteSpace($CaseNumber)) {
    $CaseNumber = if ($existingConfig -and $existingConfig.case_number) { [string]$existingConfig.case_number } else { Split-Path -Leaf $targetRoot }
}
if (-not $PSBoundParameters.ContainsKey("Port") -and $existingConfig -and $existingConfig.port) {
    $Port = [int]$existingConfig.port
}

function Copy-VARTAFile {
    param([string]$Source, [string]$Destination)
    $sourceFull = [System.IO.Path]::GetFullPath($Source)
    $destinationFull = [System.IO.Path]::GetFullPath($Destination)
    if ([string]::Equals($sourceFull, $destinationFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    Copy-Item -LiteralPath $sourceFull -Destination $destinationFull -Force
}

function Test-ReleasePackage {
    $releasePath = Join-Path $sourceRoot "release-manifest.json"
    if (-not (Test-Path -LiteralPath $releasePath -PathType Leaf)) { return }
    $release = Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$release.product -ne "VARTA" -or [string]$release.version -ne $caseflowVersion) {
        throw "Маніфест релізу не відповідає пакету VARTA $caseflowVersion."
    }
    $sourcePrefix = $sourceRoot + [System.IO.Path]::DirectorySeparatorChar
    foreach ($file in @($release.files)) {
        $relative = ([string]$file.path).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot $relative))
        if (-not $candidate.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Небезпечний шлях у маніфесті: $relative"
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "У пакеті немає файла: $relative"
        }
        $actualHash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
        if ($actualHash -ne [string]$file.sha256) {
            throw "Пакет пошкоджено або змінено: $relative"
        }
    }
}

function Stop-VARTARuntime {
    if (-not $existingInstall -and -not $existingConfig) { return }
    $runtimePort = if ($existingConfig -and $existingConfig.port) { [int]$existingConfig.port } else { $Port }
    $status = $null
    $runtimeConfirmed = $false
    try { $status = Invoke-RestMethod -Uri "http://127.0.0.1:$runtimePort/api/status" -TimeoutSec 1 } catch {}
    if ($status) {
        $reportedRoot = [System.IO.Path]::GetFullPath([string]$status.root)
        if (-not [string]::Equals($reportedRoot, $targetRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Порт $runtimePort належить іншій справі ($reportedRoot); оновлення скасовано."
        }
        if ($status.activeJob) {
            throw "Зараз виконується $($status.activeJob.kind). Дочекайтеся завершення перед оновленням."
        }
        $runtimeConfirmed = $true
        $listener = Get-NetTCPConnection -LocalPort $runtimePort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) {
            $runtimeProcess = Get-Process -Id ([int]$listener.OwningProcess) -ErrorAction SilentlyContinue
            if (-not $runtimeProcess -or ($runtimeProcess.ProcessName -ne "VARTA" -and $runtimeProcess.ProcessName -notlike "python*")) {
                throw "Не вдалося безпечно підтвердити процес VARTA на порту $runtimePort."
            }
            Stop-Process -Id $runtimeProcess.Id
            try { Wait-Process -Id $runtimeProcess.Id -Timeout 10 -ErrorAction SilentlyContinue } catch {}
        }
    }
    if ($runtimeConfirmed) {
        $installedExePath = [System.IO.Path]::GetFullPath((Join-Path $targetRoot "VARTA.exe"))
        $frozenProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ExecutablePath -and [string]::Equals([System.IO.Path]::GetFullPath([string]$_.ExecutablePath), $installedExePath, [System.StringComparison]::OrdinalIgnoreCase)
        }
        foreach ($frozenProcess in @($frozenProcesses)) {
            $remaining = Get-Process -Id ([int]$frozenProcess.ProcessId) -ErrorAction SilentlyContinue
            if ($remaining) { Stop-Process -Id $remaining.Id -Force }
        }
    }
    $pidPath = Join-Path $targetRoot ".caseflow\server.pid"
    if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
        $savedPid = 0
        if ([int]::TryParse((Get-Content -LiteralPath $pidPath -Raw), [ref]$savedPid)) {
            $savedProcess = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($savedProcess) {
                $commandLine = $null
                try { $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction Stop).CommandLine } catch {}
                if ($commandLine -and $commandLine -like "*$targetRoot*" -and ($commandLine -like "*VARTA.exe*" -or $commandLine -like "*server.py*")) {
                    Stop-Process -Id $savedPid
                }
            }
        }
        Remove-Item -LiteralPath $pidPath -Force
    }
}

function New-RollbackSnapshot {
    if (-not $previousVersion -or $NoRollback) { return $null }
    $rollbackRoot = Join-Path $targetRoot ".caseflow\rollback"
    if ($installMode -eq "repair" -and (Test-Path -LiteralPath (Join-Path $rollbackRoot "rollback.json") -PathType Leaf)) {
        return $rollbackRoot
    }
    if (Test-Path -LiteralPath $rollbackRoot) {
        $expectedRollback = [System.IO.Path]::GetFullPath((Join-Path $targetRoot ".caseflow\rollback"))
        $resolvedRollback = (Resolve-Path -LiteralPath $rollbackRoot).Path
        if (-not [string]::Equals($expectedRollback, $resolvedRollback, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Некоректна папка відкату: $resolvedRollback"
        }
        Remove-Item -LiteralPath $resolvedRollback -Recurse -Force
    }
    New-Item -ItemType Directory -Path $rollbackRoot -Force | Out-Null
    $backupPaths = @(
        "VARTA.exe", ".caseflow\app", ".caseflow\install.json",
        "scripts\caseflow_process.py", "scripts\anomaly_detector.py",
        "start_caseflow.ps1", "stop_caseflow.ps1", "install_caseflow.ps1",
        "install_caseflow_wizard.ps1", "update_caseflow.ps1", "rollback_caseflow.ps1",
        "uninstall_caseflow.ps1", "VARTA_README.md", "legal-case-mind-map.html",
        "Встановити_VARTA.cmd", "Відкрити_VARTA.cmd", "Відкрити_Доказову_Мапу.cmd", "Оновити_VARTA.cmd"
    )
    $backedUp = @()
    foreach ($relative in $backupPaths) {
        $source = Join-Path $targetRoot $relative
        if (-not (Test-Path -LiteralPath $source)) { continue }
        $destination = Join-Path $rollbackRoot $relative
        $destinationParent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
        $backedUp += $relative
    }
    $metadata = [ordered]@{
        created_at = (Get-Date).ToString("o")
        from_version = $previousVersion
        to_version = $caseflowVersion
        files = $backedUp
        managed_paths = $backupPaths
    }
    $metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $rollbackRoot "rollback.json") -Encoding UTF8
    return $rollbackRoot
}

Test-ReleasePackage
Stop-VARTARuntime
$rollbackSnapshot = New-RollbackSnapshot

$folders = @(
    "00_INBOX",
    "01_ОПРАЦЬОВАНО",
    "02_РОЗПАКОВАНО",
    "03_РЕЄСТР",
    "03_РЕЄСТР\exports",
    "03_РЕЄСТР\manifests",
    "99_ПОТРЕБУЄ_ПЕРЕВІРКИ",
    "scripts",
    "tmp\caseflow_runs",
    "tmp\caseflow_anomalies\runs",
    "tmp\processing_queue",
    "tmp\summary_agent",
    ".caseflow\app\static",
    ".caseflow\logs",
    ".caseflow\secrets"
)
foreach ($relative in $folders) {
    New-Item -ItemType Directory -Path (Join-Path $targetRoot $relative) -Force | Out-Null
}

Copy-VARTAFile (Join-Path $sourceApp "server.py") (Join-Path $targetRoot ".caseflow\app\server.py")
Copy-VARTAFile (Join-Path $sourceApp "caseflow_process.py") (Join-Path $targetRoot ".caseflow\app\caseflow_process.py")
Copy-VARTAFile (Join-Path $sourceApp "anomaly_detector.py") (Join-Path $targetRoot ".caseflow\app\anomaly_detector.py")
Copy-VARTAFile (Join-Path $sourceApp "version.json") (Join-Path $targetRoot ".caseflow\app\version.json")
$sourceStatic = [System.IO.Path]::GetFullPath((Join-Path $sourceApp "static"))
$targetStatic = [System.IO.Path]::GetFullPath((Join-Path $targetRoot ".caseflow\app\static"))
if (-not [string]::Equals($sourceStatic, $targetStatic, [System.StringComparison]::OrdinalIgnoreCase)) {
    Copy-Item -Path (Join-Path $sourceStatic "*") -Destination $targetStatic -Recurse -Force
}
Copy-VARTAFile (Join-Path $sourceApp "caseflow_process.py") (Join-Path $targetRoot "scripts\caseflow_process.py")
Copy-VARTAFile (Join-Path $sourceApp "anomaly_detector.py") (Join-Path $targetRoot "scripts\anomaly_detector.py")

$sourceExecutable = Join-Path $sourceRoot "dist\VARTA.exe"
$installedExecutable = Join-Path $targetRoot "VARTA.exe"
$useExecutable = Test-Path -LiteralPath $sourceExecutable -PathType Leaf
if ($useExecutable) {
    Copy-VARTAFile $sourceExecutable $installedExecutable
}

$pythonCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($env:VARTA_PYTHON)) {
    $pythonCandidates += $env:VARTA_PYTHON
}
if (-not [string]::IsNullOrWhiteSpace($env:CASEFLOW_PYTHON)) {
    $pythonCandidates += $env:CASEFLOW_PYTHON
}
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $bundledPython) {
    $pythonCandidates += $bundledPython
}
$pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonCandidates += $pythonCommand.Source
}
$pyCommand = Get-Command "py.exe" -ErrorAction SilentlyContinue
if ($pyCommand) {
    try {
        $resolved = & $pyCommand.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $pythonCandidates += $resolved.Trim()
        }
    } catch {}
}
$pythonPath = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $pythonPath -and -not $useExecutable) {
    throw "Не знайдено Python 3. Встановіть Python або задайте VARTA_PYTHON."
}

$sevenZipCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($SevenZipPath)) { $sevenZipCandidates += $SevenZipPath }
if (-not [string]::IsNullOrWhiteSpace($env:VARTA_7Z)) { $sevenZipCandidates += $env:VARTA_7Z }
if (-not [string]::IsNullOrWhiteSpace($env:CASEFLOW_7Z)) { $sevenZipCandidates += $env:CASEFLOW_7Z }
$sevenZipCandidates += @(
    (Join-Path $env:ProgramFiles "7-Zip\7z.exe"),
    "C:\Program Files\3uToolsV3\files\patchtools\7z-64\7z.exe",
    "C:\Program Files\3uToolsV3\files\patchtools\7z-32\7z.exe",
    "C:\Program Files\Lenovo\Lenovo Bootable Generator\7z.exe"
)
$sevenZipCommand = Get-Command "7z.exe" -ErrorAction SilentlyContinue
if ($sevenZipCommand) { $sevenZipCandidates += $sevenZipCommand.Source }
$resolvedSevenZip = $sevenZipCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $resolvedSevenZip) {
    throw "Не знайдено 7-Zip, необхідний для основного формату RAR. Встановіть 7-Zip або передайте -SevenZipPath."
}
$resolvedSevenZip = (Resolve-Path -LiteralPath $resolvedSevenZip).Path

$dependencyInfo = [pscustomobject]@{ python = $null; openpyxl = $null; pypdf = $null }
if ($pythonPath) {
    $dependencyCheck = & $pythonPath -c "import json,sys,openpyxl,pypdf; print(json.dumps({'python':sys.version.split()[0],'openpyxl':openpyxl.__version__,'pypdf':pypdf.__version__}))" 2>$null
    if ($LASTEXITCODE -ne 0 -and -not $useExecutable) {
        throw "У вибраному Python немає openpyxl або pypdf. Встановіть залежності або задайте VARTA_PYTHON на сумісне середовище."
    }
    if ($LASTEXITCODE -eq 0) {
        $dependencyInfo = $dependencyCheck | ConvertFrom-Json
        $versionParts = ([string]$dependencyInfo.python).Split('.')
        $pythonMajor = [int]$versionParts[0]
        $pythonMinor = [int]$versionParts[1]
        if (($pythonMajor -ne 3 -or $pythonMinor -lt 10 -or $pythonMinor -gt 13) -and -not $useExecutable) {
            throw "Потрібен Python 3.10–3.13; знайдено $($dependencyInfo.python)."
        }
    }
}

$config = [ordered]@{}
if ($existingConfig) {
    foreach ($property in $existingConfig.PSObject.Properties) { $config[$property.Name] = $property.Value }
}
$google = [ordered]@{}
if ($existingConfig -and $existingConfig.google) {
    foreach ($property in $existingConfig.google.PSObject.Properties) { $google[$property.Name] = $property.Value }
}
if (-not $google.Contains("client_id")) { $google["client_id"] = "" }
$ui = [ordered]@{}
if ($existingConfig -and $existingConfig.ui) {
    foreach ($property in $existingConfig.ui.PSObject.Properties) { $ui[$property.Name] = $property.Value }
}
if (-not $ui.Contains("panel_opacity")) { $ui["panel_opacity"] = 82 }
$config["case_number"] = $CaseNumber
$config["python_path"] = if ($pythonPath) { $pythonPath } elseif ($existingConfig -and $existingConfig.python_path) { [string]$existingConfig.python_path } else { "" }
$config["seven_zip_path"] = $resolvedSevenZip
$config["port"] = $Port
$config["google"] = $google
$config["ui"] = $ui
$config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding UTF8

$existingWorkbook = Get-ChildItem -LiteralPath (Join-Path $targetRoot "03_РЕЄСТР") -Filter "*.xlsx" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $existingWorkbook) {
    $template = Get-ChildItem -LiteralPath (Join-Path $sourceRoot "03_РЕЄСТР") -Filter "*.xlsx" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $template) {
        $template = Get-ChildItem -LiteralPath (Join-Path $sourceRoot "outputs\registry-legend-timeline-20260722") -Filter "*.xlsx" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($template) {
        $safeCase = ($CaseNumber -replace '[<>:"/\\|?*]', '_')
        Copy-Item -LiteralPath $template.FullName -Destination (Join-Path $targetRoot "03_РЕЄСТР\Реєстр_$safeCase.xlsx") -Force
    }
}

$registerCandidates = @()
$registerCandidates += Get-ChildItem -LiteralPath (Join-Path $targetRoot "03_РЕЄСТР\exports") -Filter "*.xlsx" -File -ErrorAction SilentlyContinue
$registerCandidates += Get-ChildItem -LiteralPath (Join-Path $targetRoot "03_РЕЄСТР") -Filter "*.xlsx" -File -ErrorAction SilentlyContinue
$latestRegister = $registerCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$registerPointer = Join-Path $targetRoot "03_РЕЄСТР\ОСТАННІЙ_РЕЄСТР.txt"
if ($latestRegister -and -not (Test-Path -LiteralPath $registerPointer -PathType Leaf)) {
    Set-Content -LiteralPath $registerPointer -Value $latestRegister.FullName -Encoding UTF8
}

$startScriptSource = Join-Path $toolRoot "start_caseflow.ps1"
$stopScriptSource = Join-Path $toolRoot "stop_caseflow.ps1"
Copy-VARTAFile $startScriptSource (Join-Path $targetRoot "start_caseflow.ps1")
Copy-VARTAFile $stopScriptSource (Join-Path $targetRoot "stop_caseflow.ps1")
foreach ($name in @("install_caseflow.ps1", "install_caseflow_wizard.ps1", "update_caseflow.ps1", "rollback_caseflow.ps1", "uninstall_caseflow.ps1")) {
    $source = Join-Path $toolRoot $name
    if (Test-Path -LiteralPath $source) {
        Copy-VARTAFile $source (Join-Path $targetRoot $name)
    }
}
$readmeSource = Join-Path $sourceRoot "README.md"
if (Test-Path -LiteralPath $readmeSource -PathType Leaf) {
    Copy-VARTAFile $readmeSource (Join-Path $targetRoot "VARTA_README.md")
}

$mapSource = Join-Path $sourceRoot "legal-case-mind-map.html"
if (-not (Test-Path -LiteralPath $mapSource -PathType Leaf)) {
    $mapSource = Join-Path $sourceRoot "caseflow\static\legal-case-map.html"
}
if (Test-Path -LiteralPath $mapSource) {
    Copy-VARTAFile $mapSource (Join-Path $targetRoot "legal-case-mind-map.html")
    Copy-VARTAFile $mapSource (Join-Path $targetRoot ".caseflow\app\static\legal-case-map.html")
}

$cmdContent = if ($useExecutable) {
    "@echo off`r`n`"%~dp0VARTA.exe`" --root `"%~dp0`" --port $Port`r`n"
} else {
    "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0start_caseflow.ps1`"`r`n"
}
Set-Content -LiteralPath (Join-Path $targetRoot "Відкрити_VARTA.cmd") -Value $cmdContent -Encoding ASCII
$mapCmdContent = if ($useExecutable) {
    "@echo off`r`nstart `"`" `"%~dp0legal-case-mind-map.html`"`r`n"
} else {
    "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0start_caseflow.ps1`" -OpenMap`r`n"
}
Set-Content -LiteralPath (Join-Path $targetRoot "Відкрити_Доказову_Мапу.cmd") -Value $mapCmdContent -Encoding ASCII
$updateCmdContent = "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0update_caseflow.ps1`" -TargetPath `"%~dp0`"`r`n"
Set-Content -LiteralPath (Join-Path $targetRoot "Оновити_VARTA.cmd") -Value $updateCmdContent -Encoding ASCII

if (-not $useExecutable) {
    & $pythonPath -m py_compile (Join-Path $targetRoot ".caseflow\app\server.py") (Join-Path $targetRoot "scripts\caseflow_process.py") (Join-Path $targetRoot "scripts\anomaly_detector.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Smoke test Python-скриптів не пройдено. Інсталяцію не фіналізовано."
    }
}

$installReport = [ordered]@{
    installed_at = if ($existingInstall -and $existingInstall.installed_at) { [string]$existingInstall.installed_at } else { (Get-Date).ToString("o") }
    updated_at = (Get-Date).ToString("o")
    install_mode = $installMode
    previous_version = $previousVersion
    version = $caseflowVersion
    data_schema = $versionManifest.data_schema
    channel = $versionManifest.channel
    target = $targetRoot
    case_number = $CaseNumber
    port = $Port
    python = $pythonPath
    seven_zip = $resolvedSevenZip
    python_version = $dependencyInfo.python
    openpyxl = $dependencyInfo.openpyxl
    pypdf = $dependencyInfo.pypdf
    executable = if ($useExecutable) { $installedExecutable } else { $null }
    executable_sha256 = if ($useExecutable) { (Get-FileHash -LiteralPath $installedExecutable -Algorithm SHA256).Hash } else { $null }
    rollback = $rollbackSnapshot
    preserved_paths = @($versionManifest.preserved_paths)
    structure = $folders
}
$installReport | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $targetRoot ".caseflow\install.json") -Encoding UTF8

$historyPath = Join-Path $targetRoot ".caseflow\update-history.json"
$history = @()
if (Test-Path -LiteralPath $historyPath -PathType Leaf) {
    try { $history = @(Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { $history = @() }
}
$history += [ordered]@{
    timestamp = (Get-Date).ToString("o")
    mode = $installMode
    from_version = $previousVersion
    to_version = $caseflowVersion
    rollback = $rollbackSnapshot
}
if ($history.Count -gt 50) { $history = @($history | Select-Object -Last 50) }
$history | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $historyPath -Encoding UTF8

$resultVerb = switch ($installMode) { "update" { "оновлено" } "repair" { "відновлено" } "downgrade" { "понижено" } default { "встановлено" } }
Write-Host "VARTA $caseflowVersion $resultVerb`: $targetRoot" -ForegroundColor Green
if ($previousVersion) { Write-Host "Попередня версія: $previousVersion; режим: $installMode" }
Write-Host "Запуск: $(Join-Path $targetRoot 'Відкрити_VARTA.cmd')"
if ($Start) {
    if ($useExecutable) {
        Start-Process -FilePath $installedExecutable -ArgumentList @("--root", $targetRoot, "--port", "$Port")
    } else {
        & (Join-Path $targetRoot "start_caseflow.ps1") -Port $Port
    }
}
