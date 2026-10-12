# Tray icon for the session board: the Needs you count, and a menu to jump to a session.
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$hud = Join-Path $repo 'hud.py'
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$env:PYTHONIOENCODING = 'utf-8'

$mutex = New-Object System.Threading.Mutex($false, 'Local\cc-hud-tray')
if (-not $mutex.WaitOne(0)) { exit }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -Namespace CcHud -Name Native -MemberDefinition '[DllImport("user32.dll")] public static extern bool DestroyIcon(System.IntPtr handle);'

$script:tray = New-Object System.Windows.Forms.NotifyIcon
$script:menu = New-Object System.Windows.Forms.ContextMenuStrip
$script:tray.ContextMenuStrip = $script:menu
$script:iconHandle = [System.IntPtr]::Zero

function New-CountIcon([int]$count, [bool]$urgent) {
  $bitmap = New-Object System.Drawing.Bitmap 16, 16
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = 'AntiAlias'
  $graphics.TextRenderingHint = 'AntiAliasGridFit'
  $color = if ($urgent) { [System.Drawing.Color]::FromArgb(225, 154, 44) }
           elseif ($count -gt 0) { [System.Drawing.Color]::FromArgb(52, 120, 198) }
           else { [System.Drawing.Color]::FromArgb(128, 128, 128) }
  $graphics.FillEllipse((New-Object System.Drawing.SolidBrush $color), 0, 0, 15, 15)
  if ($count -gt 0) {
    $text = if ($count -gt 9) { '9+' } else { "$count" }
    $font = New-Object System.Drawing.Font 'Segoe UI', 7, ([System.Drawing.FontStyle]::Bold)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = 'Center'
    $format.LineAlignment = 'Center'
    $graphics.DrawString($text, $font, [System.Drawing.Brushes]::White, (New-Object System.Drawing.RectangleF 0, 0, 16, 16), $format)
  }
  $graphics.Dispose()
  $handle = $bitmap.GetHicon()
  $bitmap.Dispose()
  # GetHicon hands over an OS handle that .NET never frees; without DestroyIcon every refresh leaks one.
  if ($script:iconHandle -ne [System.IntPtr]::Zero) { [CcHud.Native]::DestroyIcon($script:iconHandle) | Out-Null }
  $script:iconHandle = $handle
  [System.Drawing.Icon]::FromHandle($handle)
}

function Add-Item([string]$text, [scriptblock]$onClick, [object]$tag) {
  # ToolStrip reads a single & as a keyboard shortcut marker and hides it.
  $item = New-Object System.Windows.Forms.ToolStripMenuItem ($text -replace '&', '&&')
  $item.Tag = $tag
  if ($onClick) { $item.add_Click($onClick) } else { $item.Enabled = $false }
  [void]$script:menu.Items.Add($item)
}

function Update-Tray {
  $json = & $python $hud menu 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $json) {
    $script:tray.Icon = New-CountIcon 0 $false
    $script:tray.Text = 'cc-hud: board unavailable'
    return
  }
  $data = ($json -join "`n") | ConvertFrom-Json
  $script:tray.Icon = New-CountIcon $data.needs ($data.waiting -gt 0)
  $tip = "cc-hud: $($data.needs) need you, $($data.open) open"
  $script:tray.Text = $tip.Substring(0, [Math]::Min(63, $tip.Length))

  $script:menu.Items.Clear()
  Add-Item 'Open board' { Start-Process $this.Tag } $data.board
  foreach ($section in $data.sections) {
    if (-not $section.items) { continue }
    [void]$script:menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
    Add-Item $section.heading $null $null
    foreach ($item in $section.items) {
      if ($item.id -notmatch '^[0-9a-f-]+$') { continue }
      Add-Item "$($item.title)  $($item.age)" {
        Start-Process -FilePath $script:pythonw -ArgumentList @("`"$script:hud`"", 'go', $this.Tag) -WindowStyle Hidden
      } $item.id
    }
  }
  [void]$script:menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
  Add-Item 'Quit tray icon' { $script:tray.Visible = $false; [System.Windows.Forms.Application]::Exit() } $null
}

$script:tray.add_MouseUp({
  param($sender, $e)
  if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
    $show = [System.Windows.Forms.NotifyIcon].GetMethod('ShowContextMenu', [System.Reflection.BindingFlags]'Instance,NonPublic')
    $show.Invoke($script:tray, $null)
  }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 30000
$timer.add_Tick({ if (-not $script:menu.Visible) { Update-Tray } })
Update-Tray
$script:tray.Visible = $true
$timer.Start()
[System.Windows.Forms.Application]::Run()
$script:tray.Dispose()
$mutex.ReleaseMutex()
