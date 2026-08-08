[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$repositoryCandidate = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$packageRoot = if (Test-Path -LiteralPath (Join-Path $repositoryCandidate "caseflow\version.json") -PathType Leaf) {
    $repositoryCandidate
} else {
    $PSScriptRoot
}
$versionPath = Join-Path $packageRoot "caseflow\version.json"
$packageVersion = if (Test-Path -LiteralPath $versionPath -PathType Leaf) {
    [string](Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
} else { "?" }

$form = New-Object System.Windows.Forms.Form
$form.Text = "VARTA $packageVersion — встановлення та оновлення"
$form.StartPosition = "CenterScreen"
$form.ClientSize = New-Object System.Drawing.Size(680, 510)
$form.MinimumSize = New-Object System.Drawing.Size(696, 549)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$form.BackColor = [System.Drawing.Color]::FromArgb(33, 34, 44)
$form.ForeColor = [System.Drawing.Color]::FromArgb(248, 248, 242)

function Add-Label([string]$text, [int]$x, [int]$y, [int]$width = 610) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $text
    $label.Location = New-Object System.Drawing.Point($x, $y)
    $label.Size = New-Object System.Drawing.Size($width, 24)
    $label.ForeColor = $form.ForeColor
    $form.Controls.Add($label)
    return $label
}

$title = Add-Label "VARTA $packageVersion + Доказова мапа" 28 24
$title.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 20)
$title.Size = New-Object System.Drawing.Size(620, 42)
$subtitle = Add-Label "Нова версія замінює лише програму; документи, Реєстр, статуси й налаштування зберігаються." 30 68
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(200, 202, 212)

Add-Label "Папка справи" 30 112 | Out-Null
$target = New-Object System.Windows.Forms.TextBox
$target.Text = $PSScriptRoot
$target.Location = New-Object System.Drawing.Point(30, 138)
$target.Size = New-Object System.Drawing.Size(520, 30)
$form.Controls.Add($target)
$browse = New-Object System.Windows.Forms.Button
$browse.Text = "Огляд…"
$browse.Location = New-Object System.Drawing.Point(560, 136)
$browse.Size = New-Object System.Drawing.Size(88, 32)
$form.Controls.Add($browse)

Add-Label "Номер справи" 30 184 285 | Out-Null
Add-Label "Локальний порт" 348 184 180 | Out-Null
$caseNumber = New-Object System.Windows.Forms.TextBox
$caseNumber.Text = ""
$caseNumber.Location = New-Object System.Drawing.Point(30, 210)
$caseNumber.Size = New-Object System.Drawing.Size(285, 30)
$form.Controls.Add($caseNumber)
$port = New-Object System.Windows.Forms.NumericUpDown
$port.Minimum = 1024
$port.Maximum = 65535
$port.Value = 8768
$port.Location = New-Object System.Drawing.Point(348, 210)
$port.Size = New-Object System.Drawing.Size(120, 30)
$form.Controls.Add($port)

$desktop = New-Object System.Windows.Forms.CheckBox
$desktop.Text = "Створити два ярлики на робочому столі"
$desktop.Checked = $true
$desktop.Location = New-Object System.Drawing.Point(30, 264)
$desktop.Size = New-Object System.Drawing.Size(420, 28)
$desktop.ForeColor = $form.ForeColor
$form.Controls.Add($desktop)
$start = New-Object System.Windows.Forms.CheckBox
$start.Text = "Відкрити VARTA після встановлення"
$start.Checked = $true
$start.Location = New-Object System.Drawing.Point(30, 298)
$start.Size = New-Object System.Drawing.Size(420, 28)
$start.ForeColor = $form.ForeColor
$form.Controls.Add($start)

$status = Add-Label "Готово до встановлення." 30 346
$status.ForeColor = [System.Drawing.Color]::FromArgb(139, 233, 253)
$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Style = "Marquee"
$progress.MarqueeAnimationSpeed = 0
$progress.Location = New-Object System.Drawing.Point(30, 378)
$progress.Size = New-Object System.Drawing.Size(618, 18)
$form.Controls.Add($progress)

$install = New-Object System.Windows.Forms.Button
$install.Text = "Встановити"
$install.Location = New-Object System.Drawing.Point(430, 428)
$install.Size = New-Object System.Drawing.Size(104, 38)
$install.BackColor = [System.Drawing.Color]::FromArgb(80, 250, 123)
$install.ForeColor = [System.Drawing.Color]::FromArgb(33, 34, 44)
$install.FlatStyle = "Flat"
$form.Controls.Add($install)
$close = New-Object System.Windows.Forms.Button
$close.Text = "Закрити"
$close.Location = New-Object System.Drawing.Point(544, 428)
$close.Size = New-Object System.Drawing.Size(104, 38)
$form.Controls.Add($close)

function Update-InstallMode {
    $statePath = Join-Path $target.Text ".caseflow\install.json"
    $installedVersion = $null
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try { $installedVersion = [string](Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json).version } catch {}
    }
    if (-not $installedVersion) {
        $install.Text = "Встановити"
        $status.Text = "Готово до чистого встановлення VARTA $packageVersion."
        return
    }
    try {
        $current = [version]$installedVersion
        $incoming = [version]$packageVersion
        if ($current -lt $incoming) {
            $install.Text = "Оновити"
            $status.Text = "Буде оновлено $installedVersion → $packageVersion з можливістю відкату."
        } elseif ($current -eq $incoming) {
            $install.Text = "Відновити"
            $status.Text = "VARTA $packageVersion вже встановлено; буде виконано repair."
        } else {
            $install.Text = "Заблоковано"
            $status.Text = "Встановлена новіша версія $installedVersion; пониження не виконується."
        }
    } catch {
        $install.Text = "Відновити"
        $status.Text = "Версію чинної інсталяції не розпізнано; буде виконано repair."
    }
}

$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Виберіть папку справи"
    $dialog.SelectedPath = $target.Text
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $target.Text = $dialog.SelectedPath; Update-InstallMode }
})
$target.Add_Leave({ Update-InstallMode })
$close.Add_Click({ $form.Close() })

$install.Add_Click({
    $install.Enabled = $false
    $close.Enabled = $false
    $progress.MarqueeAnimationSpeed = 30
    $status.Text = "Перевіряю пакет, зупиняю VARTA та зберігаю копію для відкату…"
    $form.Refresh()
    try {
        $installer = Join-Path $PSScriptRoot "install_caseflow.ps1"
        & $installer -TargetPath $target.Text -CaseNumber $caseNumber.Text -Port ([int]$port.Value)
        if ($LASTEXITCODE -notin @(0, $null)) { throw "Інсталятор завершився з кодом $LASTEXITCODE" }
        if ($desktop.Checked) {
            $desktopPath = [Environment]::GetFolderPath("Desktop")
            $shell = New-Object -ComObject WScript.Shell
            foreach ($item in @(
                @{ Name = "VARTA.lnk"; Target = "Відкрити_VARTA.cmd"; Description = "VARTA — кабінет справи" },
                @{ Name = "Доказова мапа.lnk"; Target = "Відкрити_Доказову_Мапу.cmd"; Description = "Доказова мапа справи" }
            )) {
                $shortcut = $shell.CreateShortcut((Join-Path $desktopPath $item.Name))
                $shortcut.TargetPath = Join-Path $target.Text $item.Target
                $shortcut.WorkingDirectory = $target.Text
                $shortcut.Description = $item.Description
                $shortcut.Save()
            }
        }
        $progress.MarqueeAnimationSpeed = 0
        $progress.Value = 100
        $status.Text = "Гото. VARTA $packageVersion встановлено/оновлено; дані справи збережено."
        if ($start.Checked) { Start-Process -FilePath (Join-Path $target.Text "Відкрити_VARTA.cmd") }
        [System.Windows.Forms.MessageBox]::Show("VARTA $packageVersion готово. Попередню версію можна повернути через rollback_caseflow.ps1.", "VARTA", "OK", "Information") | Out-Null
    } catch {
        $progress.MarqueeAnimationSpeed = 0
        $progress.Value = 0
        $status.Text = "Помилка: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Помилка встановлення", "OK", "Error") | Out-Null
    } finally {
        $install.Enabled = $true
        $close.Enabled = $true
    }
})

Update-InstallMode
[void]$form.ShowDialog()
