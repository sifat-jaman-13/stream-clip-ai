import pathlib
import subprocess

base = pathlib.Path(__file__).resolve().parent
script = base / "run_streamsnip.cmd"
if not script.is_file():
    raise SystemExit("StreamSnip AI launcher files are missing.")
subprocess.Popen(["cmd.exe", "/d", "/k", str(script)], cwd=str(base), creationflags=0)
