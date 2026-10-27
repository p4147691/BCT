"""Verify the official read-only Windows background-state contract."""
from pathlib import Path
import argparse, os, sys, tempfile, subprocess

root=Path(__file__).resolve().parents[1] if __name__=="__main__" else Path.cwd()
parser=argparse.ArgumentParser()
parser.add_argument("--root",default=str(root))
args=parser.parse_args()
root=Path(args.root)
source=root/"native/src/DesktopBackgroundStateSource.cs"
visual=root/"native/src/DesktopVisualSnapshot.cs"
harness=root/"tools/MonitorBackgroundStateDecisionContract.cs"
text=source.read_text(encoding="utf-8")
visual_text=visual.read_text(encoding="utf-8")

required=[
 "IDesktopWallpaperReadOnly","GetMonitorDevicePathCount","GetMonitorDevicePathAt",
 "GetWallpaper(monitor, out wallpaper)","GetBackgroundColor(out color)",
 "TryGet(out DesktopGlobalBackgroundState state)",
 "ShouldUseSolid(monitorCount, emptyWallpaperCount, colorAvailable)",
 "windows-desktopwallpaper-global-state","Marshal.FinalReleaseComObject(instance)"
]
missing=[item for item in required if item not in text]
if missing: raise SystemExit("NATIVE_BACKGROUND_STATE_CONTRACT_MISSING:"+",".join(missing))
for forbidden in ["GetPixel(","BackgroundType","CurrentVirtualDesktop","VirtualDesktopIDs","Registry."]:
 if forbidden in text: raise SystemExit("NATIVE_BACKGROUND_STATE_HEURISTIC_FORBIDDEN:"+forbidden)
if "api.SetWallpaper(" in text or "api.SetBackgroundColor(" in text:
 raise SystemExit("NATIVE_BACKGROUND_STATE_WRITE_FORBIDDEN")
for required_visual in [
 "DesktopBackgroundStateSource.TryGet(out backgroundState)",
 "backgroundState.IsSolid",
 "ColorTranslator.FromHtml(backgroundState.BaseColor)",
 '{ "baseColor", backgroundState.BaseColor }'
]:
 if required_visual not in visual_text: raise SystemExit("NATIVE_BACKGROUND_RENDER_CONTRACT_MISSING:"+required_visual)
if not harness.is_file(): raise SystemExit("NATIVE_BACKGROUND_STATE_UNIT_TEST_MISSING")
if os.name!="nt":
 print("BACKGROUND_STATE_SOURCE_CONTRACT_PASS portable; native execution Windows-only")
 sys.exit(0)
csc=Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
if not csc.exists(): raise SystemExit("WINDOWS_CSC_NOT_FOUND")
with tempfile.TemporaryDirectory(prefix="bct-monitor-background-state-") as temp:
 exe=Path(temp)/"BackgroundStateDecisionTest.exe"
 argv=[str(csc),"/nologo","/target:exe","/out:"+str(exe),str(source),str(harness),
       "/reference:System.dll","/reference:System.Core.dll"]
 compiled=subprocess.run(argv,capture_output=True,text=True,errors="replace",timeout=55)
 if compiled.returncode: raise SystemExit("NATIVE_BACKGROUND_STATE_BUILD_FAILED:"+compiled.stdout[-1500:]+compiled.stderr[-1500:])
 run=subprocess.run([str(exe)],capture_output=True,text=True,errors="replace",timeout=20)
 if run.returncode or run.stdout.count("PASS ")!=5:
  raise SystemExit("NATIVE_BACKGROUND_STATE_UNIT_TEST_FAILED:"+run.stdout+run.stderr)
 print("BACKGROUND_STATE_SOURCE_AND_WINDOWS_DECISION_PASS",run.stdout.count("PASS "))
