<#
.SYNOPSIS
  woynich-wiki setup for Windows, for a normal user without admin rights. Safe to run again (idempotent).
.DESCRIPTION
  1. Finds Python 3.11+ or installs a private Python 3.12 for this user (python.org installer, per-user, quiet).
     Fallback: the official embeddable zip.
  2. Creates .venv in the repository and installs packages (uses the system proxy; offline from .\wheels if present).
  3. Finds Git or unpacks Portable Git (git-scm / git-for-windows) into %LOCALAPPDATA%.
  4. Downloads the Copilot runtime used by the Python SDK (no Node.js needed).
  5. Creates kb.cmd and runs a self-test. Writes setup.log.
  Downloads are checked against setup\sources.json (SHA-256). Replace URLs with company mirrors if needed.
.EXAMPLE
  setup.cmd                 (double-click)
  setup.cmd -Offline        (install packages only from .\wheels)
#>
[CmdletBinding()]
param(
  [switch]$Offline,
  [switch]$SkipGit,
  [switch]$SkipCopilot,
  [switch]$NoUserPath
)

$ErrorActionPreference = 'Stop'
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { Join-Path (Get-Location).Path 'setup' }
$Repo = Split-Path -Parent $ScriptDir
$Base = Join-Path $env:LOCALAPPDATA 'woynich-wiki'
$Downloads = Join-Path $Base 'downloads'
$Log = Join-Path $Repo 'setup.log'
$Sources = Get-Content (Join-Path $ScriptDir 'sources.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $Base, $Downloads | Out-Null
try { Start-Transcript -Path $Log -Force | Out-Null } catch { Write-Verbose 'transcript unavailable' }
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { Write-Verbose 'TLS setting unchanged' }

$script:Steps = New-Object System.Collections.Generic.List[object]
function Step([string]$Name, [string]$Status, [string]$Detail) {
  $script:Steps.Add([pscustomobject]@{ step = $Name; status = $Status; detail = $Detail })
  $color = switch ($Status) { 'OK' { 'Green' } 'SKIP' { 'Gray' } 'WARN' { 'Yellow' } default { 'Red' } }
  Write-Host ("[{0,-4}] {1}: {2}" -f $Status, $Name, $Detail) -ForegroundColor $color
}

function Get-File([string]$Url, [string]$Sha256, [string]$Name) {
  $dest = Join-Path $Downloads $Name
  if ((Test-Path $dest) -and $Sha256 -and ((Get-FileHash $dest -Algorithm SHA256).Hash -eq $Sha256.ToUpper())) { return $dest }
  Write-Host "Downloading $Name ..."
  $proxy = [Net.WebRequest]::GetSystemWebProxy(); $proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
  $wc = New-Object Net.WebClient; $wc.Proxy = $proxy
  $wc.DownloadFile($Url, $dest)
  if ($Sha256) {
    $got = (Get-FileHash $dest -Algorithm SHA256).Hash
    if ($got -ne $Sha256.ToUpper()) { Remove-Item $dest -Force; throw "Checksum mismatch for $Name (expected $Sha256, got $got). The download may be blocked or altered by a proxy." }
  }
  return $dest
}

function Find-Python {
  $candidates = @(
    (Join-Path $Base 'python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe')
  )
  foreach ($c in @('py', 'python')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $candidates += $cmd.Source }
  }
  foreach ($exe in $candidates) {
    if (-not (Test-Path $exe)) { continue }
    $pyArgs = @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
    if ((Split-Path $exe -Leaf) -eq 'py.exe') { $pyArgs = @('-3') + $pyArgs }
    try {
      $v = (& $exe @pyArgs 2>$null | Out-String).Trim()
      if ($v -match '^(\d+)\.(\d+)$' -and ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11))) {
        return @{ exe = $exe; version = $v; embeddable = (Test-Path (Join-Path (Split-Path $exe) 'python312._pth')) }
      }
    } catch { Write-Verbose "cannot run $exe" }
  }
  return $null
}

Write-Host ''
Write-Host 'woynich-wiki setup (no admin rights needed)' -ForegroundColor Cyan
Write-Host "Repository: $Repo"
Write-Host "Private tools folder: $Base"
Write-Host ''

# ------------------------------------------------------------------ 1. Python
$py = Find-Python
if ($py) {
  Step 'Python' 'OK' ("{0} ({1})" -f $py.version, $py.exe)
} else {
  $target = Join-Path $Base 'python312'
  try {
    $installer = Get-File $Sources.python_installer.url $Sources.python_installer.sha256 'python-installer.exe'
    $argList = @('/quiet', 'InstallAllUsers=0', "TargetDir=$target", 'PrependPath=0', 'Include_launcher=0', 'Include_test=0', 'Shortcuts=0', 'AssociateFiles=0')
    $p = Start-Process -FilePath $installer -ArgumentList $argList -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "installer exit code $($p.ExitCode)" }
  } catch {
    Write-Host "Per-user installer failed ($($_.Exception.Message)); trying the embeddable package." -ForegroundColor Yellow
    $zip = Get-File $Sources.python_embed.url $Sources.python_embed.sha256 'python-embed.zip'
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $target -Force
    $pth = Join-Path $target 'python312._pth'
    (Get-Content $pth) -replace '^#\s*import site', 'import site' | Set-Content $pth -Encoding ASCII
    Add-Content $pth 'Lib\site-packages'
    $getpip = Get-File $Sources.get_pip.url $null 'get-pip.py'
    & (Join-Path $target 'python.exe') $getpip --no-warn-script-location | Out-Host
  }
  $py = Find-Python
  if (-not $py) { Step 'Python' 'FAIL' 'could not install Python. Run doctor.cmd and send doctor-report.json.'; Stop-Transcript | Out-Null; exit 2 }
  Step 'Python' 'OK' ("installed {0} ({1})" -f $py.version, $py.exe)
}

# ------------------------------------------------------------------ 2. venv + packages
$venvPy = Join-Path $Repo '.venv\Scripts\python.exe'
$pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $Repo 'requirements.txt'))
$wheels = Join-Path $Repo 'wheels'
if ($Offline -or ((Test-Path $wheels) -and (Get-ChildItem $wheels -Filter *.whl -ErrorAction SilentlyContinue))) {
  $pipArgs += @('--no-index', '--find-links', $wheels)
}
try {
  if ($py.embeddable) {
    $venvPy = $py.exe   # the embeddable package has no venv module; packages go into it directly
    Step 'Virtual environment' 'WARN' 'embeddable Python: packages installed into the private Python itself'
  } elseif (-not (Test-Path $venvPy)) {
    $mk = @('-m', 'venv', (Join-Path $Repo '.venv'))
    if ((Split-Path $py.exe -Leaf) -eq 'py.exe') { $mk = @('-3') + $mk }
    & $py.exe @mk | Out-Host
    Step 'Virtual environment' 'OK' (Join-Path $Repo '.venv')
  } else {
    Step 'Virtual environment' 'OK' 'already present'
  }
  & $venvPy @pipArgs | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "pip exit code $LASTEXITCODE" }
  Step 'Python packages' 'OK' 'requirements.txt installed'
} catch {
  Step 'Python packages' 'FAIL' ($_.Exception.Message + '. Behind a proxy without internet? Put .whl files into .\wheels and run setup.cmd -Offline.')
  Stop-Transcript | Out-Null; exit 2
}

# ------------------------------------------------------------------ 3. Git
if ($SkipGit) { Step 'Git' 'SKIP' 'skipped by option' }
else {
  $git = Get-Command git -ErrorAction SilentlyContinue
  $gitDir = Join-Path $Base 'git'
  if ($git) { Step 'Git' 'OK' $git.Source }
  elseif (Test-Path (Join-Path $gitDir 'cmd\git.exe')) { Step 'Git' 'OK' (Join-Path $gitDir 'cmd\git.exe') }
  else {
    try {
      $sfx = Get-File $Sources.portable_git.url $Sources.portable_git.sha256 'PortableGit.7z.exe'
      $p = Start-Process -FilePath $sfx -ArgumentList @("-o$gitDir", '-y') -Wait -PassThru
      if ($p.ExitCode -ne 0) { throw "extract exit code $($p.ExitCode)" }
      Step 'Git' 'OK' ("Portable Git unpacked to $gitDir")
    } catch { Step 'Git' 'WARN' ("could not unpack Portable Git: $($_.Exception.Message)") }
  }
  $gitCmd = Join-Path $gitDir 'cmd'
  if ((Test-Path $gitCmd) -and -not $NoUserPath) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (($userPath -split ';') -notcontains $gitCmd) {
      [Environment]::SetEnvironmentVariable('Path', (($userPath, $gitCmd) -join ';').Trim(';'), 'User')
      Step 'PATH' 'OK' 'Portable Git added to your user PATH (open a new window to use it)'
    }
  }
}

$gitExe = (Get-Command git -ErrorAction SilentlyContinue)
if (-not $gitExe -and (Test-Path (Join-Path $Base 'git\cmd\git.exe'))) { $gitExe = Get-Item (Join-Path $Base 'git\cmd\git.exe') }
if ($gitExe) {
  $gitPath = if ($gitExe.Source) { $gitExe.Source } else { $gitExe.FullName }
  & $gitPath -C $Repo config core.hooksPath .githooks
  Step 'Git hooks' 'OK' 'pre-commit guard enabled (blocks secrets and invalid records)'
}

# ------------------------------------------------------------------ 4. Copilot runtime (SDK)
if ($SkipCopilot) { Step 'Copilot runtime' 'SKIP' 'skipped by option' }
else {
  & $venvPy -m copilot download-runtime | Out-Host
  if ($LASTEXITCODE -eq 0) { Step 'Copilot runtime' 'OK' 'downloaded and verified by the Copilot SDK' }
  else { Step 'Copilot runtime' 'WARN' 'download failed; the SDK will retry on first use (needs github.com)' }
}

# ------------------------------------------------------------------ 5. kb.cmd + self-test
$shim = @"
@echo off
setlocal
cd /d "%~dp0"
"$venvPy" -m kb %*
exit /b %ERRORLEVEL%
"@
Set-Content -Path (Join-Path $Repo 'kb.cmd') -Value $shim -Encoding ASCII
Step 'Command' 'OK' 'kb.cmd created (run: kb --help)'

Push-Location $Repo
try {
  & $venvPy -m pytest -q 2>&1 | Out-Host
  if ($LASTEXITCODE -eq 0) { Step 'Self-test' 'OK' 'all tests passed' } else { Step 'Self-test' 'WARN' 'some tests failed; see setup.log' }
} finally { Pop-Location }

Write-Host ''
$failed = @($script:Steps | Where-Object { $_.status -eq 'FAIL' }).Count
$warned = @($script:Steps | Where-Object { $_.status -eq 'WARN' }).Count
if ($failed) { Write-Host 'Setup finished with errors.' -ForegroundColor Red }
elseif ($warned) { Write-Host 'Setup finished with warnings.' -ForegroundColor Yellow }
else { Write-Host 'Setup finished.' -ForegroundColor Green }
Write-Host 'Next steps:'
Write-Host '  1. kb login        (sign in to GitHub Copilot once, in the browser)'
Write-Host '  2. kb llm-smoke    (checks that scripts can use the model; send instance\reports\llm-smoke.json)'
$script:Steps | ConvertTo-Json | Set-Content (Join-Path $Base 'setup-result.json') -Encoding UTF8
try { Stop-Transcript | Out-Null } catch { Write-Verbose 'no transcript' }
if ($failed) { exit 2 } else { exit 0 }
