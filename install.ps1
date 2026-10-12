<#
Usage: .\install.ps1              install or update (safe to re-run)
       .\install.ps1 -Uninstall
Run with: powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$repo = $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$hud = Join-Path $repo 'hud.py'
$hudHome = Join-Path $HOME '.claude\hud'
$settings = Join-Path $HOME '.claude\settings.json'
$commands = Join-Path $HOME '.claude\commands'
$tasks = 'server', 'snapshot', 'digest', 'tray'
$utf8 = New-Object System.Text.UTF8Encoding $false

function Invoke-Checked([string]$what, [scriptblock]$command) {
  & $command
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

function Remove-Ours {
  if (Test-Path $settings) { Invoke-Checked 'removing the hooks' { & $python (Join-Path $repo 'settings_hooks.py') remove $settings } }
}

if ($Uninstall) {
  if (Test-Path $python) { Remove-Ours } else { Write-Warning "$python is missing; skipped removing the hooks from $settings" }
  foreach ($name in $tasks) {
    Stop-ScheduledTask -TaskName "cc-hud-$name" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "cc-hud-$name" -Confirm:$false -ErrorAction SilentlyContinue
  }
  foreach ($name in 'done', 'steps') {
    $file = Join-Path $commands "$name.md"
    if ((Test-Path $file) -and (Select-String -Path $file -SimpleMatch 'hud.py' -Quiet)) { Remove-Item $file }
  }
  Remove-Item 'HKCU:\Software\Classes\cc-hud' -Recurse -ErrorAction SilentlyContinue
  if (Get-Command code -ErrorAction SilentlyContinue) { & code --uninstall-extension karimalbeni.cc-hud-win | Out-Null }
  & cmdkey.exe /delete:cc-hud-teams-webhook | Out-Null
  Write-Host "Uninstalled. Your data is still in $hudHome, and your settings from before the first install in $settings.bak-cc-hud."
  exit 0
}

if ($repo -match ' ') { throw "Move the repo to a path without spaces; /done and /steps permissions match on the path." }
foreach ($bin in 'poetry', 'claude', 'code') {
  if (-not (Get-Command $bin -ErrorAction SilentlyContinue)) { throw "missing: $bin" }
}
$persistentDb = [Environment]::GetEnvironmentVariable('HUD_DB', 'User')
if ($env:HUD_DB -and $env:HUD_DB -ne $persistentDb) {
  throw "HUD_DB is set in this shell only. Scheduled tasks would not see it. Run: setx HUD_DB `"$env:HUD_DB`", open a new shell, and re-run."
}

Push-Location $repo
try {
  Invoke-Checked 'poetry config' { poetry config virtualenvs.in-project true --local }
  Invoke-Checked 'poetry install' { poetry install --without dev }
} finally { Pop-Location }

New-Item -ItemType Directory -Force $hudHome, $commands | Out-Null
Invoke-Checked 'creating the database' { & $python $hud ls | Out-Null }

if (-not (Test-Path $settings)) { [System.IO.File]::WriteAllText($settings, '{}', $utf8) }
if (-not (Test-Path "$settings.bak-cc-hud")) {
  # Keep the copy from before the first install; later runs would only back up our own edits.
  Copy-Item $settings "$settings.bak-cc-hud"
}
$py = $python -replace '\\', '/'
$hook = (Join-Path $repo 'hooks\hud_event.py') -replace '\\', '/'
# Quotes are added by settings_hooks.py: Windows PowerShell 5.1 strips embedded quotes from native arguments.
$hookArguments = @($py, $hook)
if ($env:HUD_DB) { $hookArguments += '--db', ($env:HUD_DB -replace '\\', '/') }
Invoke-Checked 'adding the hooks' { & $python (Join-Path $repo 'settings_hooks.py') add $settings @hookArguments }

$hudCommand = "$py $($hud -replace '\\', '/')"
foreach ($name in 'done', 'steps') {
  $dest = Join-Path $commands "$name.md"
  if ((Test-Path $dest) -and -not (Select-String -Path $dest -SimpleMatch 'hud.py' -Quiet)) {
    Write-Warning "skipped /${name}: $dest already exists and isn't ours"
    continue
  }
  $text = [System.IO.File]::ReadAllText((Join-Path $repo "commands\$name.md")).Replace('__HUD__', $hudCommand)
  [System.IO.File]::WriteAllText($dest, $text, $utf8)
}

$marker = Join-Path $hudHome '.backfilled'
if (-not (Test-Path $marker)) {
  $days = if ($env:HUD_BACKFILL_DAYS) { $env:HUD_BACKFILL_DAYS } else { 30 }
  Invoke-Checked 'backfill' { & $python $hud backfill --days $days }
  New-Item -ItemType File $marker | Out-Null
}

$vsix = Join-Path $repo 'dist\cc-hud-win.vsix'
Invoke-Checked 'building the extension' { & $python (Join-Path $repo 'vscode-extension\build_vsix.py') $vsix | Out-Null }
Invoke-Checked 'installing the extension' { & code --install-extension $vsix --force | Out-Null }

$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
function Register-HudTask([string]$name, $triggers, [string]$execute, [string]$arguments, $settingsSet) {
  $action = New-ScheduledTaskAction -Execute $execute -Argument $arguments -WorkingDirectory $repo
  Stop-ScheduledTask -TaskName "cc-hud-$name" -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName "cc-hud-$name" -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName "cc-hud-$name" -Action $action -Trigger $triggers -Principal $principal `
    -Settings $settingsSet | Out-Null
}
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
# Task Scheduler does not restart a process that exits after launch; this repeat does, and IgnoreNew makes it a no-op while running.
$keepAlive = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$longRunning = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$short = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew

Register-HudTask 'server' @($logon, $keepAlive) $pythonw "`"$hud`" serve" $longRunning
Register-HudTask 'snapshot' (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)) `
  $pythonw "`"$hud`" snapshot" $short
Register-HudTask 'digest' @((New-ScheduledTaskTrigger -Daily -At '09:00'), (New-ScheduledTaskTrigger -Daily -At '13:30')) `
  $pythonw "`"$hud`" digest" $short
Register-HudTask 'tray' @($logon) 'powershell.exe' `
  "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $repo 'tray\hud-tray.ps1')`"" $longRunning

Start-ScheduledTask -TaskName 'cc-hud-server'
Start-ScheduledTask -TaskName 'cc-hud-tray'

$protocol = 'HKCU:\Software\Classes\cc-hud'
New-Item -Path "$protocol\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path $protocol -Name '(default)' -Value 'URL:cc-hud'
Set-ItemProperty -Path $protocol -Name 'URL Protocol' -Value ''
Set-ItemProperty -Path "$protocol\shell\open\command" -Name '(default)' -Value "`"$pythonw`" `"$hud`" open-link `"%1`""

Write-Host 'Installed. Board: http://localhost:7777 (open it with the tray icon, or: .venv\Scripts\python.exe hud.py board)'
Write-Host 'Next: reload your VS Code windows, create the Teams Workflow, then run: .venv\Scripts\python.exe hud.py set-webhook'
