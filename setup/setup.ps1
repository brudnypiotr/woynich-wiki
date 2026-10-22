<#
.SYNOPSIS
  woynich-wiki setup for Windows, for a normal user without admin rights. Safe to run again (idempotent).
.DESCRIPTION
  1. Finds Python 3.11+ or installs a private Python 3.12 for this user (python.org installer, per-user, quiet).
     Fallback: the official embeddable zip.
  2. Creates .venv in the repository and installs packages (uses the system proxy; offline from .\wheels if present).
  3. Finds Git or unpacks Portable Git (git-scm / git-for-windows) into %LOCALAPPDATA%.
  4. Downloads the Copilot runtime used by the Python SDK (no Node.js needed).
  5. Creates kb.cmd; connects a copy unpacked from a ZIP to the official repository (setup\sources.json, "update"), so
     Update in the app works; creates the app shortcuts with an icon (setup\shortcut.ps1).
  6. Runs a short self-test (5 smoke tests; -FullTest runs all). Writes setup.log.
  Downloads are checked against setup\sources.json (SHA-256). Replace URLs with company mirrors if needed.
.EXAMPLE
  setup.cmd                 (double-click)
  setup.cmd -Offline        (install packages only from .\wheels)
  setup.cmd -FullTest       (run every test, not only the smoke tests)
#>
[CmdletBinding()]
param(
  [switch]$Offline,
  [switch]$SkipGit,
  [switch]$SkipCopilot,
  [switch]$NoUserPath,
  [switch]$FullTest
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

function Invoke-Native {
  # Run an external program and return its exit code. Windows PowerShell 5.1 would otherwise turn any stderr
  # line (warnings, progress) into a terminating error while ErrorActionPreference is Stop.
  param([string]$Exe, [string[]]$ArgList)
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $Exe @ArgList 2>&1 | ForEach-Object { "$_" } | Out-Host; return $LASTEXITCODE }
  finally { $ErrorActionPreference = $old }
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
  # Windows PowerShell 5.1 turns any stderr line of a native program into a terminating error when
  # ErrorActionPreference is Stop, so probe with Continue and read the version from stdout only.
  $ErrorActionPreference = 'Continue'
  foreach ($exe in $candidates) {
    if (-not (Test-Path $exe)) { continue }
    # No double quotes in the code: Windows PowerShell 5.1 strips them from native arguments.
    $pyArgs = @('-c', 'import sys; print(sys.version_info[:2])')
    if ((Split-Path $exe -Leaf) -eq 'py.exe') { $pyArgs = @('-3') + $pyArgs }
    try {
      $out = (& $exe @pyArgs 2>&1 | ForEach-Object { "$_" }) -join "`n"
      if ($out -match '\((\d+), (\d+)\)') {
        $v = "$($Matches[1]).$($Matches[2])"
        if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
          return @{ exe = $exe; version = $v; embeddable = (Test-Path (Join-Path (Split-Path $exe) 'python312._pth')) }
        }
        Write-Host "  found Python $v at $exe (too old, need 3.11+)"
      } else {
        Write-Host "  cannot run $exe : $out"
      }
    } catch { Write-Host "  cannot run $exe : $($_.Exception.Message)" }
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
    for ($try = 1; $try -le 4; $try++) {
      $p = Start-Process -FilePath $installer -ArgumentList $argList -Wait -PassThru
      if ($p.ExitCode -ne 1618) { break }
      # 1618 = another installation (Windows Update, Intune, ...) is running: wait and retry
      Write-Host "Another installation is in progress (code 1618); waiting 45 s (attempt $try of 4) ..." -ForegroundColor Yellow
      Start-Sleep -Seconds 45
    }
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
    $null = Invoke-Native (Join-Path $target 'python.exe') @($getpip, '--no-warn-script-location')
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
    if ((Invoke-Native $py.exe $mk) -ne 0) { throw 'could not create the virtual environment' }
    Step 'Virtual environment' 'OK' (Join-Path $Repo '.venv')
  } else {
    Step 'Virtual environment' 'OK' 'already present'
  }
  $pipCode = Invoke-Native $venvPy $pipArgs   # pip writes warnings to stderr; judge by the exit code
  if ($pipCode -ne 0) { throw "pip exit code $pipCode" }
  Step 'Python packages' 'OK' 'requirements.txt installed'
  # Make `import kb` work from any folder (the embeddable Python ignores PYTHONPATH): a .pth file in site-packages.
  # Shared by all clones (the last setup wins); kb.cmd does not rely on it (see below).
  $ErrorActionPreference = 'Continue'
  $site = (& $venvPy -c "import sysconfig; print(sysconfig.get_paths()['purelib'])" 2>$null | Select-Object -Last 1)
  $ErrorActionPreference = 'Stop'
  if ($site) { $site = "$site".Trim() }
  if ($site -and (Test-Path $site)) {
    Set-Content -Path (Join-Path $site 'woynich-wiki.pth') -Value $Repo -Encoding ASCII
    Step 'Python path' 'OK' "kb importable ($site)"
  }
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
if (-not $gitExe -and (Test-Path (Join-Path $Base 'git\cmd\git.exe'))) {
  $gitExe = Get-Item (Join-Path $Base 'git\cmd\git.exe')
  $env:Path = (Join-Path $Base 'git\cmd') + ';' + $env:Path   # this window too (self-test, kb update --attach), not only new ones
}
if ($gitExe) {
  $gitPath = if ($gitExe.Source) { $gitExe.Source } else { $gitExe.FullName }
  $null = Invoke-Native $gitPath @('-C', $Repo, 'config', 'core.hooksPath', '.githooks')
  Step 'Git hooks' 'OK' 'pre-commit guard enabled (blocks secrets and invalid records)'
}

# ------------------------------------------------------------------ 4. Copilot runtime (SDK)
if ($SkipCopilot) { Step 'Copilot runtime' 'SKIP' 'skipped by option' }
else {
  if ((Invoke-Native $venvPy @('-m', 'copilot', 'download-runtime')) -eq 0) { Step 'Copilot runtime' 'OK' 'downloaded and verified by the Copilot SDK' }
  else { Step 'Copilot runtime' 'WARN' 'download failed; the SDK will retry on first use (needs github.com)' }
}

# ------------------------------------------------------------------ 5. kb.cmd + self-test
# kb.cmd puts its own copy of the repository first on the module path. The embeddable Python ignores PYTHONPATH and
# is shared by every clone; its woynich-wiki.pth points at whichever clone ran setup last, so `-m kb` alone would run
# that clone's code (and its instance) from every kb.cmd.
$shim = @"
@echo off
rem Runs from any folder, so relative file paths (kb add .\file.pdf) keep working.
setlocal
set "PYTHONUTF8=1"
"$venvPy" -c "import sys; sys.path.insert(0, r'%~dp0.'); from kb.cli import main; sys.exit(main())" %*
exit /b %ERRORLEVEL%
"@
Set-Content -Path (Join-Path $Repo 'kb.cmd') -Value $shim -Encoding ASCII
Step 'Command' 'OK' 'kb.cmd created (run: kb --help)'

# ------------------------------------------------------------------ 6. updates + shortcut
if ($SkipGit -or -not $gitExe) { Step 'Updates' 'WARN' 'no Git: Update in the app will not work until setup.cmd runs with Git' }
else {
  if ((Invoke-Native (Join-Path $Repo 'kb.cmd') @('update', '--attach')) -eq 0) {
    $null = Invoke-Native $gitPath @('-C', $Repo, 'config', 'core.hooksPath', '.githooks')   # a ZIP copy has Git only now
    Step 'Updates' 'OK' 'connected to the official repository (Update in the app, update.cmd)'
  }
  else { Step 'Updates' 'WARN' 'could not reach the repository (internet or proxy?); run setup.cmd again later to enable Update' }
}
$brandZip = Join-Path $Repo 'branding.zip'
if (Test-Path $brandZip) {   # a colleague's branding pack put next to setup.cmd
  if ((Invoke-Native (Join-Path $Repo 'kb.cmd') @('branding', 'import', $brandZip)) -eq 0) { Step 'Branding' 'OK' 'branding.zip imported into branding\' }
  else { Step 'Branding' 'WARN' 'could not import branding.zip; import it later in Settings, Project branding' }
}
try {
  $sc = & (Join-Path $ScriptDir 'shortcut.ps1') -Repo $Repo
  Step 'Shortcut' 'OK' ("{0} on the desktop and in the Start menu ({1} icon)" -f $sc.name, $sc.icon)
} catch { Step 'Shortcut' 'WARN' ("could not create the shortcut: $($_.Exception.Message); start Wiki.cmd instead") }

$testArgs = if ($FullTest) { @() } else { @('-m', 'smoke') }
$what = if ($FullTest) { 'all tests (a few minutes on Windows: antivirus checks every file and process)' } else { 'smoke tests: instance, app, About, a PDF to a cited answer, update' }
Write-Host "Self-test: $what ..." -ForegroundColor Cyan
$t0 = Get-Date
Push-Location $Repo
try {
  # Straight to the console, not through Invoke-Native's line pipe: with -v pytest prints each test's name when it
  # starts and PASSED/FAILED with the progress in % when it ends, so a slow test shows what it is busy with.
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  & $venvPy -m pytest -v -p no:cacheprovider --color=yes @testArgs
  $code = $LASTEXITCODE
  $ErrorActionPreference = $old
  $took = '{0:N0} s' -f ((Get-Date) - $t0).TotalSeconds
  if ($code -eq 0) { Step 'Self-test' 'OK' "PASSED ($took)" } else { Step 'Self-test' 'WARN' "FAILED: some tests failed ($took); see setup.log" }
} finally { Pop-Location }

Write-Host ''
$failed = @($script:Steps | Where-Object { $_.status -eq 'FAIL' }).Count
$warned = @($script:Steps | Where-Object { $_.status -eq 'WARN' }).Count
if ($failed) { Write-Host 'Setup finished with errors.' -ForegroundColor Red }
elseif ($warned) { Write-Host 'Setup finished with warnings.' -ForegroundColor Yellow }
else { Write-Host 'Setup finished.' -ForegroundColor Green }
Write-Host 'Next step: start the app from the desktop shortcut (or Wiki.cmd in this folder).'
Write-Host '  It opens the app in your browser; keep its window open. New versions: Update in the app (or update.cmd).'
Write-Host '  The first start opens Welcome: a ready knowledge base, GitHub Copilot sign-in, the model, Jira (and optional steps).'
Write-Host '  Another knowledge base: "Wiki.cmd" C:\kb\other-instance'
Write-Host 'In a terminal instead: kb login (Copilot sign-in), kb llm-smoke (model check), kb serve.'
Write-Host "Each copy of the repository runs its own code and its own instance\ through its own kb.cmd ($Repo)."
$script:Steps | ConvertTo-Json | Set-Content (Join-Path $Base 'setup-result.json') -Encoding UTF8
try { Stop-Transcript | Out-Null } catch { Write-Verbose 'no transcript' }
if ($failed) { exit 2 } else { exit 0 }
