<#
.SYNOPSIS
  Can this laptop read the older Office formats and the text in images? Read-only: nothing is installed or changed.

  1. Word:        make a .doc, open it read-only, save it as .docx (the conversion kb will use for .doc).
  2. PowerPoint:  the same for .ppt -> .pptx.
  3. OCR:         the Windows text recognition (WinRT) on a picture with known text; lists its languages.
  4. Packages:    pip can download xlrd and Pillow (through the proxy); nothing is installed.

  Writes local\probe-formats.json; every check says OK, FAIL or SKIP with the reason.
  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File setup\probe-formats.ps1
#>
$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Tmp = Join-Path ([IO.Path]::GetTempPath()) ("kb-probe-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
$Report = [ordered]@{ at = (Get-Date).ToString('s'); windows = [Environment]::OSVersion.VersionString; ps = $PSVersionTable.PSVersion.ToString(); checks = [ordered]@{} }

function Check([string]$name, [scriptblock]$body) {
  $t0 = Get-Date
  try {
    $detail = & $body
    $Report.checks[$name] = [ordered]@{ ok = $true; detail = "$detail"; seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
    Write-Host ("[OK]   {0}: {1}" -f $name, $detail) -ForegroundColor Green
  } catch {
    $Report.checks[$name] = [ordered]@{ ok = $false; detail = $_.Exception.Message; seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
    Write-Host ("[FAIL] {0}: {1}" -f $name, $_.Exception.Message) -ForegroundColor Red
  }
}

function Release($o) { if ($o) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($o) } catch {} } }

# ------------------------------------------------------------------ 1. Word
Check 'word' {
  $doc = Join-Path $Tmp 'probe.doc'; $docx = Join-Path $Tmp 'probe.docx'
  $w = $null; $d = $null
  try {
    $w = New-Object -ComObject Word.Application
    $w.Visible = $false; $w.DisplayAlerts = 0; $w.AutomationSecurity = 3   # no alerts, macros disabled
    $d = $w.Documents.Add(); $d.Content.Text = 'probe 123'
    $d.SaveAs2($doc, 0); $d.Close(0); Release $d                         # 0 = wdFormatDocument (97-2003)
    $d = $w.Documents.Open($doc, $false, $true)                           # ConfirmConversions off, ReadOnly
    $d.SaveAs2($docx, 16); $d.Close(0)                                    # 16 = wdFormatDocumentDefault (.docx)
    if (-not (Test-Path $docx)) { throw 'no .docx written' }
    "Word {0}: .doc -> .docx works" -f $w.Version
  } finally { if ($w) { try { $w.Quit(0) } catch {} }; Release $d; Release $w }
}

# ------------------------------------------------------------------ 2. PowerPoint
Check 'powerpoint' {
  $ppt = Join-Path $Tmp 'probe.ppt'; $pptx = Join-Path $Tmp 'probe.pptx'
  $p = $null; $pr = $null
  try {
    $p = New-Object -ComObject PowerPoint.Application
    $p.DisplayAlerts = 1                                                  # ppAlertsNone
    $p.AutomationSecurity = 3
    $pr = $p.Presentations.Add(0)                                         # WithWindow = msoFalse
    $s = $pr.Slides.Add(1, 2); $s.Shapes.Item(1).TextFrame.TextRange.Text = 'probe 123'; Release $s
    $pr.SaveAs($ppt, 1); $pr.Close(); Release $pr                         # 1 = ppSaveAsPresentation (97-2003)
    $pr = $p.Presentations.Open($ppt, -1, 0, 0)                           # ReadOnly, not Untitled, WithWindow off
    $pr.SaveAs($pptx, 24); $pr.Close()                                    # 24 = ppSaveAsOpenXMLPresentation
    if (-not (Test-Path $pptx)) { throw 'no .pptx written' }
    "PowerPoint {0}: .ppt -> .pptx works" -f $p.Version
  } finally { if ($p) { try { $p.Quit() } catch {} }; Release $pr; Release $p }
}

# ------------------------------------------------------------------ 3. OCR (Windows.Media.Ocr)
Check 'ocr' {
  Add-Type -AssemblyName System.Drawing
  $png = Join-Path $Tmp 'probe.png'
  $bmp = New-Object System.Drawing.Bitmap 900, 200
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::White)
  $font = New-Object System.Drawing.Font 'Arial', 48
  $g.DrawString('Crew rest 10 hours', $font, [System.Drawing.Brushes]::Black, 20, 50)
  $g.Dispose(); $bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()

  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, [Type]$type) { $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); [void]$task.Wait(30000); $task.Result }

  $langs = ([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }) -join ', '
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  if (-not $engine) { throw "no OCR engine for the user's languages (available: $langs)" }
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($png)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $text = (Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])).Text
  $stream.Dispose()
  if ($text -notmatch 'rest') { throw "read '$text' instead of 'Crew rest 10 hours' (languages: $langs)" }
  "read '$text'; languages: $langs"
}

# ------------------------------------------------------------------ 4. Packages through the proxy (download only)
Check 'packages' {
  $txt = Join-Path $Repo 'local\pythonw.txt'
  $py = $null
  if (Test-Path $txt) { $py = Join-Path (Split-Path -Parent ((Get-Content $txt -TotalCount 1).Trim())) 'python.exe' }
  if (-not $py -or -not (Test-Path $py)) { $py = Join-Path $Repo '.venv\Scripts\python.exe' }
  if (-not (Test-Path $py)) { $py = Join-Path $env:LOCALAPPDATA 'woynich-wiki\python312\python.exe' }
  if (-not (Test-Path $py)) { throw 'the app''s Python was not found (run setup first)' }
  $dl = Join-Path $Tmp 'wheels'
  $ErrorActionPreference = 'Continue'   # pip writes warnings to stderr; judge by the exit code
  $out = & $py -m pip download --disable-pip-version-check --no-deps --only-binary=:all: -d $dl xlrd pillow 2>&1
  $code = $LASTEXITCODE
  $ErrorActionPreference = 'Stop'
  if ($code -ne 0) { throw ("pip exit code {0}: {1}" -f $code, (($out | Select-Object -Last 3) -join ' ')) }
  "downloaded: " + ((Get-ChildItem $dl -Filter *.whl | ForEach-Object { $_.Name }) -join ', ')
}

# ------------------------------------------------------------------ report
Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
$local = Join-Path $Repo 'local'
New-Item -ItemType Directory -Force -Path $local | Out-Null
$file = Join-Path $local 'probe-formats.json'
$Report | ConvertTo-Json -Depth 4 | Set-Content -Path $file -Encoding UTF8
Write-Host ""
Write-Host "Report: $file"
