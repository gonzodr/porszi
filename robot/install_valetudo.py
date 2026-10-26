"""Upload Valetudo 2026.10.0 to the robot, then run valetudo_install.sh. Output: valetudo_install_output.txt"""
import hashlib, os, pathlib, subprocess, sys, datetime, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent
EXPECTED_MD5 = "5fe5153cfb63ba60605daaefdd214863"
log = []
def say(s):
    print(s, flush=True); log.append(s)
ssh = [r"C:\WINDOWS\System32\OpenSSH\ssh.exe", "-F", "NUL", "-T",
    "-i", str(ROOT / "vacuum_diagnostic_key"), "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=" + str(ROOT / "vacuum_known_hosts"),
    "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    "-o", "MACs=+hmac-sha1", "-o", "ConnectTimeout=8", "root@" + os.environ.get("PORSZI_ROBOT_IP", "192.168.1.126")]
try:
    say("# started " + datetime.datetime.now().isoformat(timespec="seconds"))
    binf = ROOT / "valetudo-armv7.upx"
    if not binf.exists():
        url = "https://github.com/Hypfer/Valetudo/releases/download/2026.10.0/valetudo-armv7.upx"
        say("downloading " + url)
        urllib.request.urlretrieve(url, binf)
    data = binf.read_bytes()
    md5 = hashlib.md5(data).hexdigest()
    say(f"local md5 {md5}")
    if md5 != EXPECTED_MD5:
        raise SystemExit("Local binary checksum mismatch, stopping.")
    r = subprocess.run(ssh + ["cat > /mnt/UDISK/valetudo.new && md5sum /mnt/UDISK/valetudo.new"], input=data, capture_output=True, timeout=600)
    say("upload exit=%d %s %s" % (r.returncode, r.stdout.decode(errors="replace").strip(), r.stderr.decode(errors="replace").strip()))
    if r.returncode or EXPECTED_MD5 not in r.stdout.decode(errors="replace"):
        raise SystemExit("Upload verification failed, nothing was changed on the robot.")
    body = (ROOT / "valetudo_install.sh").read_bytes().replace(b"\r\n", b"\n")
    r = subprocess.run(ssh + ["sh -s"], input=body, capture_output=True, timeout=300)
    say("install exit=%d" % r.returncode)
    say(r.stdout.decode(errors="replace"))
    if r.stderr: say("STDERR: " + r.stderr.decode(errors="replace"))
except SystemExit as e:
    say("STOPPED: %s" % e)
except Exception as e:
    say("FAILED: %s: %s" % (type(e).__name__, e))
say("# DONE " + datetime.datetime.now().isoformat(timespec="seconds"))
(ROOT / "valetudo_install_output.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
