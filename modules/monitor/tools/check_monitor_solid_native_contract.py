from pathlib import Path
import argparse,os,sys,tempfile,subprocess,json,shutil
root=Path(__file__).resolve().parents[1] if __name__=="__main__" else Path.cwd()
a=argparse.ArgumentParser()
a.add_argument("--root",default=str(root))
args=a.parse_args()
root=Path(args.root)
source=root/"native/src/DesktopSolidColorSource.cs"
harness=root/"tools/MonitorSolidDecisionContract.cs"
text=source.read_text(encoding="utf-8")
required=[
 "IDesktopWallpaperReadOnly","GetMonitorDevicePathCount","GetMonitorDevicePathAt",
 "GetWallpaper(monitor, out wallpaper)","GetBackgroundColor(out color)",
 "IsCurrentDesktop(desktopId)","ShouldUseSolid(current,true,false,false)",
 "ShouldUseInheritedSolid(targetActive,targetHasWallpaper,currentSolid)",
 "Marshal.FinalReleaseComObject(instance)"
]
missing=[x for x in required if x not in text]
if missing:raise SystemExit("NATIVE_SOLID_SOURCE_CONTRACT_MISSING:"+",".join(missing))
if not harness.is_file():raise SystemExit("NATIVE_SOLID_UNIT_TEST_MISSING")
if os.name!="nt":
 print("SOLID_COM_SOURCE_CONTRACT_PASS portable; native execution Windows-only")
 sys.exit(0)
csc=Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
if not csc.exists():raise SystemExit("WINDOWS_CSC_NOT_FOUND")
with tempfile.TemporaryDirectory(prefix="bct-monitor-solid-com-") as temp:
 exe=Path(temp)/"NativeColorDecisionTest.exe"
 argv=[str(csc),"/nologo","/target:exe","/out:"+str(exe),str(source),str(harness),
       "/reference:System.dll","/reference:System.Core.dll","/reference:System.Drawing.dll",
       "/reference:System.Windows.Forms.dll"]
 compiled=subprocess.run(argv,capture_output=True,text=True,errors="replace",timeout=55)
 if compiled.returncode:raise SystemExit("NATIVE_SOLID_BUILD_FAILED:"+compiled.stdout[-1500:]+compiled.stderr[-1500:])
 run=subprocess.run([str(exe)],capture_output=True,text=True,errors="replace",timeout=20)
 if run.returncode or run.stdout.count("PASS ")!=9:
  raise SystemExit("NATIVE_SOLID_UNIT_TEST_FAILED:"+run.stdout+run.stderr)
 print("SOLID_COM_SOURCE_AND_WINDOWS_DECISION_PASS",run.stdout.count("PASS "))
