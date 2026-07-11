# Creates TimePilot shortcuts (Desktop + Startup + Start Menu) with the custom
# icon, pointing at the venv's pythonw so no console window appears.
#
# Shortcuts are stamped with the app's AppUserModelID (Bud.TimePilot) so that
# pinning TimePilot to the taskbar keeps the TimePilot icon instead of
# reverting to the generic Python icon.
#
#   .\install_shortcuts.ps1                    # all three shortcuts
#   .\install_shortcuts.ps1 -OnTop             # widget launches always-on-top
#   .\install_shortcuts.ps1 -NoStartup         # skip the login autostart
#   .\install_shortcuts.ps1 -Arguments "--framed"   # extra desktop.py args
#
# Works in Windows PowerShell 5.1 and pwsh 7+. Re-run any time to update;
# delete the .lnk files to undo.

param(
    [switch]$NoDesktop,
    [switch]$NoStartup,
    [switch]$NoStartMenu,
    [switch]$OnTop,
    [string]$Arguments = ""
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$appId = "Bud.TimePilot"   # must match SetCurrentProcessExplicitAppUserModelID in desktop.py

if ($OnTop) { $Arguments = ($Arguments + " --on-top").Trim() }

# --- find pythonw (prefer a venv next to the project) ---
$py = $null
foreach ($rel in @(".venv\Scripts\pythonw.exe", "venv\Scripts\pythonw.exe")) {
    $cand = Join-Path $here $rel
    if (Test-Path $cand) { $py = $cand; break }
}
if (-not $py) {
    $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) { throw "pythonw.exe not found - create a venv in $here or add Python to PATH." }

$icon = Join-Path $here "static\timepilot.ico"

# --- COM interop to stamp AppUserModelID onto a .lnk ---
if (-not ("TP2.Aumid" -as [type])) {
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace TP2 {
  [StructLayout(LayoutKind.Sequential)]
  public struct PropertyKey { public Guid fmtid; public int pid;
    public PropertyKey(Guid g, int p){ fmtid = g; pid = p; } }

  // 64-bit PROPVARIANT: vt at offset 0, data pointer at offset 8
  [StructLayout(LayoutKind.Explicit)]
  public struct PropVariant {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr ptr;
  }

  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IPropertyStore {
    int GetCount(out uint cProps);
    int GetAt(uint iProp, out PropertyKey pkey);
    int GetValue(ref PropertyKey key, out PropVariant pv);
    int SetValue(ref PropertyKey key, ref PropVariant pv);
    int Commit();
  }

  public static class Aumid {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
    static extern int SHGetPropertyStoreFromParsingName(string path, IntPtr pbc,
      int flags, ref Guid riid, out IPropertyStore store);

    public static void Set(string lnkPath, string appId) {
      Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
      IPropertyStore store;
      int hr = SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, 2, ref iid, out store);
      if (hr != 0) throw new Exception("SHGetPropertyStore failed: 0x" + hr.ToString("X"));
      PropertyKey key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
      PropVariant pv = new PropVariant();
      pv.vt = 31;                                        // VT_LPWSTR
      pv.ptr = Marshal.StringToCoTaskMemUni(appId);
      try {
        int hr2 = store.SetValue(ref key, ref pv);
        if (hr2 != 0) throw new Exception("SetValue failed: 0x" + hr2.ToString("X"));
        store.Commit();
      } finally {
        Marshal.FreeCoTaskMem(pv.ptr);
        Marshal.ReleaseComObject(store);
      }
    }
  }
}
"@
}

$ws = New-Object -ComObject WScript.Shell
function New-Lnk([string]$path) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $py
    $s.Arguments = ("`"$(Join-Path $here 'desktop.py')`" $Arguments").Trim()
    $s.WorkingDirectory = $here
    if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
    $s.Description = "TimePilot - tasks, timer & time entry"
    $s.Save()
    [TP2.Aumid]::Set($path, $appId)
    Write-Host "Created  $path"
}

if (-not $NoDesktop)   { New-Lnk (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TimePilot.lnk') }
if (-not $NoStartup)   { New-Lnk (Join-Path ([Environment]::GetFolderPath('Startup')) 'TimePilot.lnk') }
if (-not $NoStartMenu) { New-Lnk (Join-Path ([Environment]::GetFolderPath('Programs')) 'TimePilot.lnk') }

Write-Host "Using interpreter: $py"
Write-Host ""
Write-Host "Taskbar pinning: unpin any old TimePilot/Python pin first, launch TimePilot,"
Write-Host "then right-click the taskbar icon -> Pin. With the Start Menu shortcut carrying"
Write-Host "the app ID, the pin now keeps the TimePilot icon."
