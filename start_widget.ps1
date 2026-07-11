# TimePilot widget launcher - no pywebview needed.
# Starts the Flask server hidden (if not already running), then opens an
# Edge app-mode window (no browser chrome).
#
#   pwsh .\start_widget.ps1
#
# For startup: shell:startup shortcut →
#   pwsh.exe -WindowStyle Hidden -File "C:\path\to\timepilot\start_widget.ps1"

$ErrorActionPreference = 'Stop'
$port = 5170
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Port {
    try { $c = [Net.Sockets.TcpClient]::new(); $c.Connect('127.0.0.1', $port); $c.Close(); $true }
    catch { $false }
}

if (-not (Test-Port)) {
    # Prefer a venv interpreter sitting next to the project; fall back to PATH.
    $py = @(".venv\Scripts\pythonw.exe", "venv\Scripts\pythonw.exe") |
        ForEach-Object { Join-Path $here $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $py) {
        $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cmd.Source } else { $py = 'pythonw.exe' }
    }

    Start-Process -FilePath $py -ArgumentList "`"$(Join-Path $here 'app.py')`"" -WorkingDirectory $here
    foreach ($i in 1..24) { if (Test-Port) { break }; Start-Sleep -Milliseconds 250 }
    if (-not (Test-Port)) {
        Write-Error "Server failed to start on port $port (check python/venv path: $py)"
    }
}

$edge = @("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
          "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { $edge = 'msedge.exe' }

Start-Process -FilePath $edge -ArgumentList "--app=http://127.0.0.1:$port", "--window-size=520,760"
