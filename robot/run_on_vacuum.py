"""Run a local shell script on the robot over the pinned SSH key; save output next to it."""
import datetime
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
script = ROOT / sys.argv[1]
out = ROOT / (script.stem + "_output.txt")
ssh = [
    r"C:\WINDOWS\System32\OpenSSH\ssh.exe", "-F", "NUL", "-T",
    "-i", str(ROOT / "vacuum_diagnostic_key"), "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=" + str(ROOT / "vacuum_known_hosts"),
    "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    "-o", "MACs=+hmac-sha1", "-o", "ConnectTimeout=8", "root@" + os.environ.get("PORSZI_ROBOT_IP", "192.168.1.126"),
    "sh -s",
]
body = script.read_bytes().replace(b"\r\n", b"\n")
started = datetime.datetime.now().isoformat(timespec="seconds")
try:
    r = subprocess.run(ssh, input=body, capture_output=True, timeout=600)
    text = f"# {script.name} started {started}, exit={r.returncode}\n" + r.stdout.decode("utf-8", "replace")
    if r.stderr:
        text += "\n# STDERR\n" + r.stderr.decode("utf-8", "replace")
except Exception as exc:
    text = f"# {script.name} started {started}\n# FAILED: {type(exc).__name__}: {exc}\n"
text += "\n# DONE " + datetime.datetime.now().isoformat(timespec="seconds") + "\n"
out.write_text(text, encoding="utf-8")
print(text)
