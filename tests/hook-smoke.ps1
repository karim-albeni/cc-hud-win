# Runs real hook payloads through hooks/hud_event.py against a scratch database and checks the rows it leaves.
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo '.venv\Scripts\python.exe'
$hud = Join-Path $repo 'hud.py'
$hook = Join-Path $repo 'hooks\hud_event.py'
$query = Join-Path $PSScriptRoot 'query.py'
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('cc-hud-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $scratch | Out-Null
$env:HUD_DB = Join-Path $scratch 'hud.db'
& $py $hud ls | Out-Null

function Fire([string]$payload) { $payload | & $py $hook }
function Sql([string]$sql) { (& $py $query $env:HUD_DB $sql) -join "`n" }
function Row([string]$expr, [string]$sid = 's1') { Sql "SELECT $expr FROM items WHERE session_id = '$sid'" }
function Check([string]$what, [string]$expected, [string]$actual) {
  if ($expected -cne $actual) {
    Write-Host "FAIL: ${what}: expected '$expected', got '$actual'"
    exit 1
  }
  Write-Host "ok: $what"
}

Fire '{"session_id":"s1","cwd":"/tmp/w","hook_event_name":"UserPromptSubmit","prompt":"  see https://github.com/acme/web/pull/7 for O''Brien  "}'
Check 'a prompt sets working' 'working' (Row 'live')
Check 'the PR link in a prompt is picked up' 'acme/web#7' (Row 'gh_ref')
Check 'quotes survive and whitespace is trimmed' "see https://github.com/acme/web/pull/7 for O'Brien" (Row 'first_prompt')

Fire '{"session_id":"s1","hook_event_name":"PermissionRequest","tool_name":"Bash"}'
Check 'a permission request waits' 'waiting|permission: Bash' (Row "live || '|' || live_detail")

Fire '{"session_id":"s1","hook_event_name":"PostToolUse","agent_id":"x1"}'
Check "a subagent's tool use keeps the prompt visible" 'waiting' (Row 'live')

Fire '{"session_id":"s1","hook_event_name":"Notification","notification_type":"idle_prompt","message":"waiting for input"}'
Check 'an idle reminder is idle, not waiting' 'idle' (Row 'live')

Fire '{"session_id":"s1","hook_event_name":"SessionEnd","reason":"clear"}'
Check '/clear hands the old session on instead of closing it' 'detached|cleared' (Row "live || '|' || state")

Fire '{"session_id":"s1","hook_event_name":"UserPromptSubmit","prompt":"back again"}'
Check 'typing reopens it' 'open|1' (Row "state || '|' || (done_at IS NULL)")

Fire '{"session_id":"s1","hook_event_name":"SessionEnd","reason":"prompt_input_exit"}'
Check 'closing the tab only detaches' 'detached|open' (Row "live || '|' || state")

Fire '{}'
Fire '{"hook_event_name":"Stop"}'
Check 'payloads without a session add nothing' '1' (Sql 'SELECT count(*) FROM items')

Fire '{"session_id":"s2","cwd":"/tmp/w","hook_event_name":"UserPromptSubmit","prompt":"ship https://github.com/acme/web/pull/9"}'
& $py $hud note 'after the release, bump the app' -s s2
& $py $hud step add 'Trigger the downstream release' -s s2 | Out-Null
Fire '{"session_id":"s2","cwd":"/tmp/w","hook_event_name":"SessionEnd","reason":"clear"}'
Fire '{"session_id":"s3","cwd":"/tmp/w","hook_event_name":"SessionStart","source":"clear"}'
Check 'the session after /clear continues the thread' 's2' (Row 'thread_id' 's3')
Check 'it carries the note and the PR' 'after the release, bump the app|acme/web#9' (Row "note || '|' || gh_ref" 's3')
Check "the thread's steps come along" '1. [ ] Trigger the downstream release' (@(& $py $hud step ls -s s3)[0])

Fire '{"session_id":"s3","cwd":"/tmp/w","hook_event_name":"SessionEnd","reason":"clear"}'
Fire '{"session_id":"s4","cwd":"/tmp/w","hook_event_name":"SessionStart","source":"clear"}'
Check "a second /clear stays in the first session's thread" 's2' (Row 'thread_id' 's4')

Fire '{"session_id":"s5","cwd":"/tmp/elsewhere","hook_event_name":"SessionStart","source":"clear"}'
Check 'a /clear in another folder starts its own thread' '' (Row 'thread_id' 's5')

Fire '{"session_id":"s6","cwd":"/tmp/v","hook_event_name":"SessionStart","source":"startup"}'
& $py $hud done s6 | Out-Null
Fire '{"session_id":"s6","cwd":"/tmp/v","hook_event_name":"SessionEnd","reason":"clear"}'
Fire '{"session_id":"s7","cwd":"/tmp/v","hook_event_name":"SessionStart","source":"clear"}'
Check '/done before /clear stays done and starts nothing' 'done|' ((Row 'state' 's6') + '|' + (Row 'thread_id' 's7'))

Fire '{"session_id":"r1","cwd":"/tmp/u","hook_event_name":"UserPromptSubmit","prompt":"I usually type: review https://github.com/acme/web/pull/7/changes"}'
Sql "UPDATE items SET gh_login = 'someone', gh_checked_at = 1, pr_event = 'ci passed', pr_checked_at = 1 WHERE session_id = 'r1'" | Out-Null
& $py $hud ref none -s r1 | Out-Null
Check 'ref none drops the guessed PR, its face and its status' '||||2' (Row "coalesce(gh_ref, '') || '|' || coalesce(gh_url, '') || '|' || coalesce(gh_login, '') || '|' || coalesce(pr_event, '') || '|' || gh_scanned" 'r1')
Fire '{"session_id":"r1","cwd":"/tmp/u","hook_event_name":"UserPromptSubmit","prompt":"and https://github.com/acme/web/issues/8"}'
Check 'a later link does not override a ref set by hand' '' (Row 'gh_ref' 'r1')

& $py $hud ref https://github.com/acme/api/pull/12/changes -s r1 | Out-Null
Check 'ref takes a PR URL' 'acme/api#12|https://github.com/acme/api/pull/12|1' (Row "gh_ref || '|' || gh_url || '|' || (gh_checked_at IS NULL)" 'r1')
& $py $hud ref 'acme/api#13' -s r1 | Out-Null
Check 'ref takes owner/repo#N' 'acme/api#13|' (Row "gh_ref || '|' || coalesce(gh_url, '')" 'r1')
& $py $hud ref 'not a ref' -s r1 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host 'FAIL: ref accepted garbage'; exit 1 }
Check 'a bad ref changes nothing' 'acme/api#13' (Row 'gh_ref' 'r1')

Fire '{"session_id":"r1","cwd":"/tmp/u","hook_event_name":"SessionEnd","reason":"clear"}'
Fire '{"session_id":"r2","cwd":"/tmp/u","hook_event_name":"SessionStart","source":"clear"}'
Fire '{"session_id":"r2","cwd":"/tmp/u","hook_event_name":"UserPromptSubmit","prompt":"now https://github.com/acme/web/pull/9"}'
Check 'a ref set by hand survives /clear' 'acme/api#13|2' (Row "gh_ref || '|' || gh_scanned" 'r2')

Fire '{"session_id":"s2","cwd":"/tmp/w","hook_event_name":"UserPromptSubmit","prompt":"also https://github.com/acme/web/pull/99"}'
Fire '{"session_id":"s2","cwd":"/tmp/w","hook_event_name":"SessionEnd","reason":"clear"}'
Fire '{"session_id":"s8","cwd":"/tmp/w","hook_event_name":"SessionStart","source":"clear"}'
Check 'a guessed ref does not pin the session after /clear' 'acme/web#9|' (Row "gh_ref || '|' || coalesce(gh_scanned, '')" 's8')

Remove-Item $scratch -Recurse -Force
Write-Host 'all smoke checks passed'
