import os
import pathlib
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(r"D:\BCT\runtime\modules\chrome-auto-proxy")
HELPER = ROOT / "helper.py"

def helper_alive():
    try:
        with socket.create_connection(("127.0.0.1", 25346), timeout=0.6):
            return True
    except OSError:
        return False

def main():
    if helper_alive():
        return 0
    pythonw = pathlib.Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else pathlib.Path(sys.executable))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    env = os.environ.copy()
    env.pop("RUNNER_TRACKING_ID", None)
    p = subprocess.Popen(
        [exe, str(HELPER)],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
        env=env,
    )
    for _ in range(20):
        time.sleep(0.25)
        if helper_alive():
            return 0
        if p.poll() is not None:
            return 1
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
