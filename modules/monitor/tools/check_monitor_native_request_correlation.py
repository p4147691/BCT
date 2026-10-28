from pathlib import Path
import argparse
import json
import struct
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Compile Monitor Native host and verify requestId framing")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    refs = Path(r"C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.0")
    if not csc.is_file():
        raise SystemExit("WINDOWS_CSC_NOT_FOUND")
    sources = [root / "native" / "src" / name for name in (
        "MonitorDesktopHost.cs", "DesktopVisualSnapshot.cs", "DesktopBackgroundStateSource.cs",
        "MonitorDragPreviewOverlay.cs", "MonitorExternalWindowDrop.cs", "MonitorWallpaperRegistryWatcher.cs")]
    if not all(path.is_file() for path in sources):
        raise SystemExit("NATIVE_SOURCE_MISSING")

    with tempfile.TemporaryDirectory(prefix="bct-monitor-native-correlation-") as folder:
        exe = Path(folder) / "DesktopWindowMonitorControlHost.exe"
        compile_result = subprocess.run([
            str(csc), "/nologo", "/target:exe", "/platform:anycpu", "/optimize+", "/out:" + str(exe),
            *map(str, sources), "/reference:System.dll", "/reference:System.Core.dll",
            "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
            "/reference:System.Web.Extensions.dll", "/reference:" + str(refs / "UIAutomationClient.dll"),
            "/reference:" + str(refs / "UIAutomationTypes.dll")
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        if compile_result.returncode:
            raise SystemExit((compile_result.stdout + compile_result.stderr)[-2000:])

        framed = bytearray()
        expected = {"probe-a", "probe-b"}
        for request_id in expected:
            payload = json.dumps({"type": "correlationContractProbe", "requestId": request_id}).encode("utf-8")
            framed += struct.pack("<I", len(payload)) + payload
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.run([str(exe)], input=bytes(framed), capture_output=True,
                                 timeout=15, creationflags=creation_flags)
        if process.returncode:
            raise SystemExit("NATIVE_HOST_EXIT_" + str(process.returncode))
        found = set()
        offset = 0
        while offset + 4 <= len(process.stdout):
            size = struct.unpack_from("<I", process.stdout, offset)[0]
            offset += 4
            if size <= 0 or offset + size > len(process.stdout):
                raise SystemExit("INVALID_NATIVE_FRAME")
            response = json.loads(process.stdout[offset:offset + size].decode("utf-8"))
            offset += size
            if response.get("requestId") in expected:
                found.add(response["requestId"])
        if found != expected:
            raise SystemExit("REQUEST_ID_ECHO_MISMATCH " + repr(found))
    print("PASS: compiled Native host preserves requestId on every framed response")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
