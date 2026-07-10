param(
  [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$WebDir = Join-Path $RootDir "web"
$TauriDir = Join-Path $WebDir "src-tauri"

Push-Location $WebDir
try {
  $Version = node -p "require('./package.json').version"

  if (-not $SkipChecks) {
    npm run check
  }

  npm run tauri:build

  $ReleaseDir = Join-Path $TauriDir "target\release"
  $Executable = Join-Path $ReleaseDir "mistrelay-pc-client.exe"
  if (-not (Test-Path $Executable)) {
    throw "Release executable not found: $Executable"
  }

  $PortableDir = Join-Path $ReleaseDir "bundle\portable"
  New-Item -ItemType Directory -Force -Path $PortableDir | Out-Null

  $PortableZip = Join-Path $PortableDir "MistRelay-PC-Client-$Version-windows-x64-portable.zip"
  if (Test-Path $PortableZip) {
    Remove-Item $PortableZip -Force
  }
  Compress-Archive -Path $Executable -DestinationPath $PortableZip -Force

  Write-Host "Portable package: $PortableZip"
  Write-Host "Installer output directory: $(Join-Path $ReleaseDir 'bundle\nsis')"
}
finally {
  Pop-Location
}
