import pathlib
import subprocess
import sys

base = pathlib.Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
script = base / "run_streamsnip.cmd"
if not script.is_file():
    raise SystemExit("StreamSnip AI launcher files are missing.")
subprocess.Popen(["cmd.exe", "/d", "/k", str(script)], cwd=str(base), creationflags=0)
