<#
.SYNOPSIS
  Creates the "Wiki" shortcuts (desktop and Start menu) for this copy, with an icon. No admin rights needed.
.DESCRIPTION
  A .cmd file cannot have its own icon, so the shortcut carries it. The icon comes from the knowledge base's branding
  (instance\branding\icon.ico or icon.png, kept outside Git) and falls back to the neutral setup\app.ico.
  Run again after adding branding: setup.cmd does, or powershell -ExecutionPolicy Bypass -File setup\shortcut.ps1
#>
[CmdletBinding()]
param([string]$Repo = (Split-Path -Parent $PSScriptRoot), [string]$Name = 'Wiki')

$ErrorActionPreference = 'Stop'
$Base = Join-Path $env:LOCALAPPDATA 'woynich-wiki'
New-Item -ItemType Directory -Force -Path $Base | Out-Null
$instance = if ($env:KB_INSTANCE) { $env:KB_INSTANCE } else { Join-Path $Repo 'instance' }
$branding = Join-Path $instance 'branding'
$icon = Join-Path $Base 'app.ico'

function Write-PngIcon([string]$Source, [string]$Dest) {
  # One 256 px PNG inside an .ico (Windows Vista+ reads it and scales it down for small sizes).
  Add-Type -AssemblyName System.Drawing
  $img = [System.Drawing.Image]::FromFile($Source)
  try {
    $bmp = New-Object System.Drawing.Bitmap 256, 256
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $scale = [Math]::Min(256 / $img.Width, 256 / $img.Height)
    $w = [int]($img.Width * $scale); $h = [int]($img.Height * $scale)
    $g.DrawImage($img, [int]((256 - $w) / 2), [int]((256 - $h) / 2), $w, $h)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    $png = $ms.ToArray()
  } finally { $img.Dispose() }
  $fs = [System.IO.File]::Create($Dest)
  try {
    $bw = New-Object System.IO.BinaryWriter $fs
    $bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]1)           # header: icon, 1 image
    $bw.Write([byte]0); $bw.Write([byte]0); $bw.Write([byte]0); $bw.Write([byte]0)  # 256x256, no palette
    $bw.Write([UInt16]1); $bw.Write([UInt16]32); $bw.Write([UInt32]$png.Length); $bw.Write([UInt32]22)
    $bw.Write($png); $bw.Flush()
  } finally { $fs.Dispose() }
}

$source = 'neutral'
$ico = Join-Path $branding 'icon.ico'
$png = @('icon.png', 'icon.jpg', 'icon.jpeg') | ForEach-Object { Join-Path $branding $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
try {
  if (Test-Path $ico) { Copy-Item $ico $icon -Force; $source = 'branding' }
  elseif ($png) { Write-PngIcon $png $icon; $source = 'branding' }
  else { Copy-Item (Join-Path $PSScriptRoot 'app.ico') $icon -Force }
} catch {
  Write-Host "  could not use the branding icon ($($_.Exception.Message)); using the neutral one"
  Copy-Item (Join-Path $PSScriptRoot 'app.ico') $icon -Force; $source = 'neutral'
}

$launcher = Join-Path $Repo "$Name.cmd"
$shell = New-Object -ComObject WScript.Shell
$made = @()
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'))) {
  if (-not $dir -or -not (Test-Path $dir)) { continue }
  $lnk = $shell.CreateShortcut((Join-Path $dir "$Name.lnk"))
  $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
  $lnk.Arguments = "/c `"`"$launcher`"`""
  $lnk.WorkingDirectory = $Repo
  $lnk.IconLocation = "$icon,0"
  $lnk.Description = 'Wiki: project knowledge base'
  $lnk.Save()
  $made += $dir
}
[pscustomobject]@{ icon = $source; shortcuts = $made }
