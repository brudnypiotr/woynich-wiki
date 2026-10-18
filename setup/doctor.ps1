<#
.SYNOPSIS
  woynich-wiki doctor: READ-ONLY check of this Windows machine before setup (spike S2).
.DESCRIPTION
  Changes nothing, installs nothing, needs no admin rights. Writes a plain-language summary to the console
  and a machine-readable report to doctor-report.json next to this repository (send that file back).
  Compatible with Windows PowerShell 5.1 and PowerShell 7.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File setup\doctor.ps1
#>
[CmdletBinding()]
param(
  [string]$ReportPath = '',
  [int]$TimeoutSec = 15
)

$ErrorActionPreference = 'Continue'
# $PSScriptRoot can be empty in param() defaults on Windows PowerShell 5.1: resolve the folder here, with a fallback.
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { (Get-Location).Path }
if (-not $ReportPath) { $ReportPath = Join-Path (Split-Path -Parent $ScriptDir) 'doctor-report.json' }
$results = New-Object System.Collections.Generic.List[object]

function Add-Check {
  param([string]$Area, [string]$Name, [ValidateSet('OK','WARN','FAIL','INFO')][string]$Status, [string]$Detail, [string]$Advice = '')
  $results.Add([pscustomobject]@{ area = $Area; name = $Name; status = $Status; detail = $Detail; advice = $Advice })
}

function Invoke-Tool {
  param([string]$Exe, [string[]]$ArgList)
  try {
    $cmd = Get-Command $Exe -ErrorAction Stop
    $out = & $cmd.Source @ArgList 2>&1 | Out-String
    return @{ found = $true; path = $cmd.Source; output = $out.Trim() }
  } catch {
    return @{ found = $false; path = $null; output = $_.Exception.Message }
  }
}

# ---------------------------------------------------------------- system
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
Add-Check 'system' 'Windows version' 'INFO' ("{0} build {1}, {2}" -f $os.Caption, $os.BuildNumber, $env:PROCESSOR_ARCHITECTURE)
Add-Check 'system' 'PowerShell' 'INFO' ("{0} ({1})" -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition)

$lang = $ExecutionContext.SessionState.LanguageMode
if ($lang -eq 'FullLanguage') { Add-Check 'policy' 'PowerShell language mode' 'OK' $lang }
else { Add-Check 'policy' 'PowerShell language mode' 'FAIL' $lang 'Scripts run in restricted mode (AppLocker/WDAC). Setup scripts will likely be blocked; ask IT or use the manual install guide.' }

$policies = Get-ExecutionPolicy -List | ForEach-Object { "{0}={1}" -f $_.Scope, $_.ExecutionPolicy }
$effective = Get-ExecutionPolicy
$st = 'OK'; $adv = ''
if ($effective -in @('Restricted','AllSigned')) { $st = 'WARN'; $adv = 'setup.cmd starts PowerShell with -ExecutionPolicy Bypass for this process only; if MachinePolicy/UserPolicy is set by GPO this may still be blocked.' }
Add-Check 'policy' 'Execution policy' $st ("effective={0}; {1}" -f $effective, ($policies -join ', ')) $adv

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Add-Check 'system' 'Running as admin' 'INFO' ([string]$isAdmin) 'Not needed. Setup is designed for a normal user.'

try {
  $alp = Get-AppLockerPolicy -Effective -ErrorAction Stop
  $rules = @($alp.RuleCollections | ForEach-Object { $_ }).Count
  if ($rules -gt 0) { Add-Check 'policy' 'AppLocker' 'WARN' ("$rules rule collections active") 'Executables in %LOCALAPPDATA% may be blocked. The report helps IT decide.' }
  else { Add-Check 'policy' 'AppLocker' 'OK' 'no effective rules' }
} catch { Add-Check 'policy' 'AppLocker' 'INFO' 'could not query (module missing or no rights)' }

try {
  $lp = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction Stop
  if ($lp.LongPathsEnabled -eq 1) { Add-Check 'system' 'Long paths' 'OK' 'enabled' }
  else { Add-Check 'system' 'Long paths' 'WARN' 'disabled (260-character limit)' 'Keep the repository in a short path, e.g. C:\kb\woynich-wiki.' }
} catch { Add-Check 'system' 'Long paths' 'INFO' 'unknown' }

# ---------------------------------------------------------------- folders
$repo = Split-Path -Parent $ScriptDir
$st = 'OK'; $adv = ''
if ($repo -match 'OneDrive') { $st = 'WARN'; $adv = 'Move the repository out of OneDrive (sync conflicts, files-on-demand).' }
if ($repo.Length -gt 60) { $st = 'WARN'; $adv = ($adv + ' Path is long; a shorter path avoids the 260-character limit.').Trim() }
Add-Check 'folders' 'Repository location' $st $repo $adv

$local = $env:LOCALAPPDATA
try {
  $probe = Join-Path $local ('woynich-doctor-' + [guid]::NewGuid().ToString('N') + '.tmp')
  Set-Content -Path $probe -Value 'probe' -ErrorAction Stop; Remove-Item $probe -ErrorAction SilentlyContinue
  Add-Check 'folders' 'Writable %LOCALAPPDATA%' 'OK' $local
} catch { Add-Check 'folders' 'Writable %LOCALAPPDATA%' 'FAIL' $local 'Setup installs Python per user into %LOCALAPPDATA%; this must be writable.' }

try {
  $drive = (Get-Item $repo).PSDrive
  $freeGb = [math]::Round($drive.Free / 1GB, 1)
  if ($freeGb -lt 5) { Add-Check 'folders' 'Free disk space' 'WARN' "$freeGb GB on $($drive.Name):" 'At least 5 GB recommended.' }
  else { Add-Check 'folders' 'Free disk space' 'OK' "$freeGb GB on $($drive.Name):" }
} catch { Add-Check 'folders' 'Free disk space' 'INFO' 'unknown' }

# ---------------------------------------------------------------- network
$winhttp = (netsh winhttp show proxy 2>$null | Out-String).Trim()
$ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
$proxyInfo = "WinHTTP: " + ($winhttp -replace '\s+', ' ') + "; user ProxyEnable=" + $ie.ProxyEnable + " ProxyServer=" + $ie.ProxyServer + " AutoConfigURL=" + $ie.AutoConfigURL
$envProxy = @($env:HTTP_PROXY, $env:HTTPS_PROXY) -join ' '
Add-Check 'network' 'Proxy settings' 'INFO' ($proxyInfo + "; env: " + $envProxy) 'pip and downloads reuse these settings.'

try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
$hosts = [ordered]@{
  'python.org (Python installer)' = 'https://www.python.org/ftp/python/'
  'pypi.org (Python packages)' = 'https://pypi.org/simple/pip/'
  'files.pythonhosted.org (package files)' = 'https://files.pythonhosted.org/'
  'github.com (Git for Windows, Copilot)' = 'https://github.com/'
  'api.githubcopilot.com (Copilot API)' = 'https://api.githubcopilot.com/'
  'objects.githubusercontent.com (downloads)' = 'https://objects.githubusercontent.com/'
}
foreach ($h in $hosts.GetEnumerator()) {
  try {
    $req = [Net.HttpWebRequest]::Create($h.Value)
    $req.Method = 'GET'; $req.Timeout = $TimeoutSec * 1000; $req.AllowAutoRedirect = $true
    $req.Proxy = [Net.WebRequest]::GetSystemWebProxy(); $req.Proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
    try { $resp = $req.GetResponse() } catch [Net.WebException] { $resp = $_.Exception.Response }
    $code = if ($resp) { [int]$resp.StatusCode } else { 0 }
    $issuer = ''
    try { $issuer = $req.ServicePoint.Certificate.Issuer } catch {}
    if ($resp) { $resp.Close() }
    $tls = ''
    if ($issuer -and $issuer -notmatch "DigiCert|Let's Encrypt|GlobalSign|Sectigo|Microsoft|Amazon|Google|GTS|ISRG|Fastly") { $tls = ' (certificate issued by a corporate proxy: TLS inspection)' }
    if ($code -gt 0) { Add-Check 'network' $h.Key 'OK' ("HTTP $code; issuer: $issuer$tls") }
    else { Add-Check 'network' $h.Key 'FAIL' 'no response' 'Blocked or proxy needed; use the offline wheels/ folder or ask IT.' }
  } catch {
    Add-Check 'network' $h.Key 'FAIL' $_.Exception.Message 'Blocked or proxy needed; use the offline wheels/ folder or ask IT.'
  }
}

# ---------------------------------------------------------------- tools
$py = $null
foreach ($cand in @('py', 'python', 'python3')) {
  $r = Invoke-Tool $cand @('--version')
  if ($r.found -and $r.path -notmatch 'WindowsApps' -and $r.output -match 'Python (\d+)\.(\d+)') {
    $py = @{ exe = $r.path; major = [int]$Matches[1]; minor = [int]$Matches[2]; text = $r.output }; break
  }
}
if ($py -and ($py.major -gt 3 -or ($py.major -eq 3 -and $py.minor -ge 11))) { Add-Check 'tools' 'Python 3.11+' 'OK' ("{0} at {1}" -f $py.text, $py.exe) }
elseif ($py) { Add-Check 'tools' 'Python 3.11+' 'WARN' ("{0} at {1}" -f $py.text, $py.exe) 'Too old; setup installs a private Python 3.12 for this user.' }
else { Add-Check 'tools' 'Python 3.11+' 'WARN' 'not found (the Microsoft Store alias does not count)' 'Setup installs a private Python 3.12 for this user, no admin needed.' }

$r = Invoke-Tool 'git' @('--version')
if ($r.found) { Add-Check 'tools' 'Git' 'OK' $r.output } else { Add-Check 'tools' 'Git' 'WARN' 'not found' 'Setup can unpack Portable Git into %LOCALAPPDATA%, no admin needed.' }

$r = Invoke-Tool 'copilot' @('--version')
if ($r.found) { Add-Check 'tools' 'GitHub Copilot CLI' 'OK' ($r.output -split "`n")[0] } else { Add-Check 'tools' 'GitHub Copilot CLI' 'INFO' 'not on PATH' 'Not required: the Python Copilot SDK bundles its own CLI.' }

foreach ($t in @('node', 'winget', 'gh')) {
  $r = Invoke-Tool $t @('--version')
  Add-Check 'tools' $t 'INFO' ($(if ($r.found) { ($r.output -split "`n")[0] } else { 'not found' }))
}

$r = Invoke-Tool 'cmdkey' @('/list')
if ($r.found) { Add-Check 'tools' 'Windows Credential Manager' 'OK' 'available (secrets are stored here, per user)' }
else { Add-Check 'tools' 'Windows Credential Manager' 'WARN' 'cmdkey not available' 'Secrets can fall back to environment variables.' }

try {
  $gpu = Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object { "{0} ({1} MB)" -f $_.Name, [math]::Round($_.AdapterRAM / 1MB) }
  Add-Check 'system' 'GPU (optional, local transcription)' 'INFO' ($gpu -join '; ')
} catch {}

# ---------------------------------------------------------------- report
$counts = @{ OK = 0; WARN = 0; FAIL = 0; INFO = 0 }
foreach ($c in $results) { $counts[$c.status]++ }
Write-Host ''
Write-Host 'woynich-wiki doctor (read-only check)' -ForegroundColor Cyan
Write-Host '======================================'
foreach ($c in $results) {
  $color = switch ($c.status) { 'OK' { 'Green' } 'WARN' { 'Yellow' } 'FAIL' { 'Red' } default { 'Gray' } }
  Write-Host ("[{0,-4}] {1,-38} {2}" -f $c.status, $c.name, $c.detail) -ForegroundColor $color
  if ($c.advice -and $c.status -ne 'OK') { Write-Host ("       -> {0}" -f $c.advice) -ForegroundColor DarkGray }
}
Write-Host ''
$verdict = if ($counts.FAIL -gt 0) { 'BLOCKERS FOUND: setup will probably not finish; send the report.' } elseif ($counts.WARN -gt 0) { 'READY WITH WARNINGS: setup should work; read the warnings above.' } else { 'READY: you can run setup.cmd.' }
Write-Host $verdict -ForegroundColor $(if ($counts.FAIL -gt 0) { 'Red' } elseif ($counts.WARN -gt 0) { 'Yellow' } else { 'Green' })

$report = [ordered]@{
  tool = 'woynich-wiki doctor'; version = 1; at = (Get-Date).ToString('s'); computer_hash = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$env:COMPUTERNAME))) -replace '-', '').Substring(0, 12)
  summary = $counts; verdict = $verdict; checks = $results
}
$report | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding UTF8
Write-Host "Report saved: $ReportPath (contains no passwords or personal data; computer name is hashed)"
if ($counts.FAIL -gt 0) { exit 2 } elseif ($counts.WARN -gt 0) { exit 1 } else { exit 0 }
