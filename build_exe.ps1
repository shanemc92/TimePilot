# Builds a portable TimePilot.exe with PyInstaller.
# Run from an activated venv that has requirements.txt installed:
#
#   pip install pyinstaller
#   .\build_exe.ps1              # one-file portable exe -> dist\TimePilot.exe
#   .\build_exe.ps1 -OneDir      # folder build (faster startup, friendlier to AV)
#
# The exe creates/uses a data\ folder NEXT TO ITSELF (settings.json, tasks.json, etc.,
# window.json), so the whole thing is portable: move the exe, move the folder.
#
# Notes:
# - One-file exes unpack to %TEMP% at launch, so startup takes a second or two.
# - Some AV/EDR flags unsigned one-file PyInstaller exes; -OneDir builds are
#   flagged far less often. Worth knowing before it lands on a managed endpoint.

param(
    [switch]$OneDir,
    [switch]$Debug,                # console build: shows the real traceback on launch failure
    [switch]$Sign,                 # sign dist exe after build
    [string]$Thumbprint = "",      # cert thumbprint (CurrentUser\My); omit to auto-pick a code-signing cert
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$mode = if ($OneDir) { "--onedir" } else { "--onefile" }
$window = if ($Debug) { "--console" } else { "--windowed" }

# Guard against the classic failure: PyInstaller installed globally freezes the
# wrong environment (no flask/pywebview inside). Require it in THIS interpreter.
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { throw "PyInstaller not in the active environment. Activate the venv, then: pip install pyinstaller" }
python -c "import flask, webview" 2>$null
if ($LASTEXITCODE -ne 0) { throw "flask/pywebview not importable in the active environment - activate the project venv first." }

python -m PyInstaller --noconfirm --clean $mode $window --name TimePilot `
    --icon "static\timepilot.ico" `
    --version-file "version_info.txt" `
    --add-data "static;static" `
    --hidden-import clr `
    --hidden-import app `
    --hidden-import webview.platforms.winforms `
    --hidden-import webview.platforms.edgechromium `
    --exclude-module webview.platforms.android `
    --exclude-module webview.platforms.cocoa `
    --exclude-module webview.platforms.gtk `
    --exclude-module webview.platforms.qt `
    --collect-all webview `
    --collect-all clr_loader `
    --collect-all pythonnet `
    --collect-all icalendar `
    --collect-all recurring_ical_events `
    --hidden-import x_wr_timezone `
    --collect-all dateutil `
    --collect-data tzdata `
    desktop.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed ($LASTEXITCODE)" }

if ($OneDir) {
    Write-Host "`nBuilt: dist\TimePilot\TimePilot.exe (ship the whole TimePilot folder)"
} else {
    Write-Host "`nBuilt: dist\TimePilot.exe (single portable file)"
}
Write-Host "First run creates data\ next to the exe. Shortcut/pin icon is baked in."

if ($Sign) {
    $exe = if ($OneDir) { "dist\TimePilot\TimePilot.exe" } else { "dist\TimePilot.exe" }
    if (-not $Thumbprint) {
        $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Select-Object -First 1
        if (-not $cert) { throw "No code-signing cert in CurrentUser\My. Pass -Thumbprint or install one." }
        $Thumbprint = $cert.Thumbprint
        Write-Host "Signing with: $($cert.Subject) ($Thumbprint)"
    }
    & signtool sign /fd SHA256 /td SHA256 /tr $TimestampUrl /sha1 $Thumbprint $exe
    if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE). Is Windows SDK signtool on PATH?" }
    & signtool verify /pa $exe
    Write-Host "Signed and timestamped: $exe"
}
